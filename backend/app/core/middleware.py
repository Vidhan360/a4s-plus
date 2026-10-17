"""Request correlation, security headers and audit middleware."""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.config import settings
from app.core.logging import get_logger, request_id_ctx

logger = get_logger("app.request")

#: Header name used for correlation across frontend, backend and logs.
REQUEST_ID_HEADER = "X-Request-ID"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    # The API serves JSON only; a restrictive CSP is therefore safe here.
    "Content-Security-Policy": ("default-src 'none'; frame-ancestors 'none'; base-uri 'none'"),
}

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request ID, time the request and emit one structured log line."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if 8 <= len(incoming) <= 64 else str(uuid.uuid4())
        request.state.request_id = request_id
        token = request_id_ctx.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            raise
        finally:
            request_id_ctx.reset(token)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers["Server-Timing"] = f"app;dur={duration_ms}"
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
                "client": request.client.host if request.client else None,
            },
        )
        return response


DOCS_PATHS = ("/api/docs", "/api/redoc", "/docs", "/redoc")
DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.jsdelivr.net; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._headers = dict(SECURITY_HEADERS)
        if settings.is_production:
            self._headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        is_docs = request.url.path in DOCS_PATHS
        for key, value in self._headers.items():
            if key == "Content-Security-Policy" and is_docs:
                response.headers[key] = DOCS_CSP
            else:
                response.headers.setdefault(key, value)
        return response


class AuditMiddleware(BaseHTTPMiddleware):
    """Write an append-only audit record for every mutating API request.

    Route handlers may also log domain-specific audit entries; this middleware
    guarantees baseline coverage so a mutation can never go unrecorded.
    """

    SKIP_PATHS = ("/health", "/healthz", "/readyz", "/docs", "/openapi.json", "/redoc")

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        path = request.url.path
        if request.method not in MUTATING_METHODS or path.startswith(self.SKIP_PATHS):
            return response
        # Auth routes write richer, purpose-built audit entries themselves.
        if path.endswith(("/auth/login", "/auth/refresh")):
            return response
        try:
            from app.services.audit_service import AuditService, audit_context

            ctx = audit_context(request)
            actor = getattr(request.state, "actor_id", None)
            if actor is None and response.status_code < 400:
                return response  # unauthenticated non-error mutation: nothing to link
            await AuditService.log_background(
                actor_user_id=actor,
                action=f"{request.method} {path}",
                resource_type=_resource_type(path),
                resource_id=None,
                result=(
                    "SUCCESS"
                    if response.status_code < 400
                    else ("DENIED" if response.status_code in (401, 403) else "ERROR")
                ),
                ip=ctx["ip"],
                user_agent=ctx["user_agent"],
                metadata={
                    "status": response.status_code,
                    "request_id": getattr(request.state, "request_id", None),
                },
            )
        except Exception:  # auditing must never break the response path
            logger.exception("audit_middleware_failed", extra={"path": path})
        return response


def _resource_type(path: str) -> str:
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 3 and parts[0] == "api":
        return parts[2]
    return parts[-1] if parts else "unknown"
