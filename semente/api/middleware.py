"""Shared HTTP middleware — the behaviour every interface inherits.

Mounted once by :class:`semente.api.app.SementeApp`, so the REST, WhatsApp
and A2A routers all get the same request id, the same one-line access log and
the same opaque 500 (no interface can leak an internal error message).
"""

from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from semente.logging import log_error, log_info

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Tag each request with an id, log it once, and normalize failures."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid4().hex
        request.state.request_id = request_id
        started = perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 — the client gets a generic 500
            log_error(
                f"http: unhandled error on {request.method} {request.url.path} "
                f"(request_id={request_id}): {exc}",
                exc_info=True,
            )
            response = JSONResponse(
                {"detail": "Internal server error", "request_id": request_id},
                status_code=500,
            )
        elapsed_ms = (perf_counter() - started) * 1000
        response.headers[REQUEST_ID_HEADER] = request_id
        log_info(
            f"http: {request.method} {request.url.path} -> {response.status_code} "
            f"in {elapsed_ms:.0f}ms (request_id={request_id})"
        )
        return response
