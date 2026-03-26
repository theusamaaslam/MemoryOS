from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from app.core.cache import rate_limit_check
from app.core.config import settings


async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; connect-src 'self' http: https:; img-src 'self' data:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; font-src 'self' https://fonts.gstatic.com; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net;"
    return response


async def rate_limit(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
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
    return await call_next(request)
