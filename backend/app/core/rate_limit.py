"""Rate limiting.

Uses ``slowapi`` with a Redis storage backend when Redis is configured so the
limits hold across workers, falling back to in-memory counters otherwise.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.errors import error_body
from app.core.logging import get_logger

logger = get_logger(__name__)


def _key(request: Request) -> str:
    """Rate-limit by authenticated subject when known, else by client IP."""
    actor = getattr(request.state, "actor_id", None)
    if actor:
        return f"user:{actor}"
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return f"ip:{forwarded.split(',')[0].strip()}"
    return f"ip:{get_remote_address(request)}"


def _build_limiter() -> Limiter:
    storage_uri = settings.redis_url if settings.env != "test" else None
    if storage_uri:
        try:
            import redis
            r = redis.from_url(storage_uri, socket_connect_timeout=0.2, socket_timeout=0.2)
            r.ping()
        except Exception:
            logger.warning("rate_limit_storage_fallback_memory")
            storage_uri = None
    return Limiter(
        key_func=_key,
        default_limits=[settings.rate_limit_default],
        storage_uri=storage_uri,
        headers_enabled=True,
    )


limiter = _build_limiter()


async def rate_limit_handler(request: Request, exc: Exception) -> JSONResponse:
    detail = getattr(exc, "detail", "Rate limit exceeded")
    logger.warning(
        "rate_limited",
        extra={"path": request.url.path, "key": _key(request), "limit": str(detail)},
    )
    return JSONResponse(
        status_code=429,
        content=error_body(
            "rate_limited",
            "Too many requests. Please slow down and retry shortly.",
            {"limit": str(detail)},
            getattr(request.state, "request_id", None),
        ),
        headers={"Retry-After": "60"},
    )


def install_rate_limiting(app: FastAPI) -> None:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)
