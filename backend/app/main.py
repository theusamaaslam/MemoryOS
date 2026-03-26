import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastmcp.utilities.lifespan import combine_lifespans

from app.api.routes import auth, conversations, mcp, memory
from app.api.routes.mcp_sse import mcp_http_app, mcp_sse_app
from app.core.cache import rate_limit_check, redis_client
from app.core.config import settings
from app.core.db import initialize_database
from app.core.logging import configure_logging
from app.core.metrics import REQUEST_COUNT, REQUEST_LATENCY, metrics_response
from app.services.embeddings import embedding_service


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    configure_logging()
    initialize_database()
    redis_client.ping()
    try:
        embedding_service.warmup_embeddings()
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger("memoryos").warning(
            "Embedding warmup failed (%s). Semantic search will be unavailable until a valid "
            "MEMORYOS_HUGGINGFACE_TOKEN is set and the service is restarted.",
            exc,
        )
    try:
        embedding_service.warmup_reranker()
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger("memoryos").warning(
            "Reranker warmup failed (%s). Retrieval will stay available, but the first reranked recall may incur "
            "cold-start latency until the reranker model downloads successfully.",
            exc,
        )
    yield


app = FastAPI(
    title="MemoryOS API",
    version="0.1.0",
    description="Enterprise-grade, MCP-native, self-improving memory platform for AI agents.",
    lifespan=combine_lifespans(app_lifespan, mcp_http_app.lifespan),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def http_pipeline(request: Request, call_next) -> Response:
    client = request.headers.get("X-Forwarded-For", "")
    ip = client.split(",")[0].strip() if client else (request.client.host if request.client else "unknown")
    allowed, retry_after = rate_limit_check(f"ratelimit:{ip}", settings.rate_limit_per_minute)
    if not allowed:
        return Response(
            content='{"detail":"Rate limit exceeded"}',
            status_code=429,
            headers={"Retry-After": str(retry_after)},
            media_type="application/json",
        )

    started = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - started
    path = request.url.path

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; connect-src 'self' http: https:; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
        "font-src 'self' https://fonts.gstatic.com; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net;"
    )

    REQUEST_COUNT.labels(request.method, path, str(response.status_code)).inc()
    REQUEST_LATENCY.labels(request.method, path).observe(duration)
    logging.info(
        json.dumps(
            {
                "event": "http_request",
                "method": request.method,
                "path": path,
                "status_code": response.status_code,
                "duration_ms": round(duration * 1000, 2),
            }
        )
    )
    return response

app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(memory.router, prefix=settings.api_prefix)
app.include_router(conversations.router, prefix=settings.api_prefix)
app.include_router(conversations.admin_router, prefix=settings.api_prefix)
app.include_router(mcp.router, prefix=settings.api_prefix)

app.mount("/mcp", mcp_http_app)
app.mount("/sse", mcp_sse_app)
app.mount("/mcp-sse", mcp_sse_app)


@app.get("/")
def root() -> dict:
    return {
        "name": settings.app_name,
        "status": "ok",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "mcp_http": "/mcp",
        "mcp_sse": "/sse",
        "mcp_sse_legacy_alias": "/mcp-sse",
        "features": [
            "session_memory",
            "event_memory",
            "knowledge_graph",
            "long_term_memory",
            "reflection",
            "conversations",
            "admin_control_room",
            "mcp",
            "ingestion",
        ],
    }


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/metrics")
def metrics() -> object:
    return metrics_response()
