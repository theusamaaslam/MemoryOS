from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, mcp, memory
from app.core.cache import redis_client
from app.core.config import settings
from app.core.db import initialize_database
from app.core.logging import configure_logging, log_requests
from app.core.metrics import metrics_middleware, metrics_response
from app.core.security import rate_limit, security_headers
from app.services.embeddings import embedding_service


app = FastAPI(
    title="MemoryOS API",
    version="0.1.0",
    description="Enterprise-grade, MCP-native, self-improving memory platform for AI agents.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(metrics_middleware)
app.middleware("http")(log_requests)
app.middleware("http")(security_headers)
app.middleware("http")(rate_limit)

app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(memory.router, prefix=settings.api_prefix)
app.include_router(mcp.router, prefix=settings.api_prefix)


@app.on_event("startup")
def startup() -> None:
    configure_logging()
    initialize_database()
    redis_client.ping()
    embedding_service.warmup()


@app.get("/")
def root() -> dict:
    return {
        "name": settings.app_name,
        "status": "ok",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "features": [
            "session_memory",
            "event_memory",
            "knowledge_graph",
            "long_term_memory",
            "reflection",
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
