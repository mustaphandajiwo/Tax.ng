"""Starlette adapter: HTTP in, ``dispatch`` out, plus static files and headers.

Kept deliberately thin. See handlers.py for the API itself.
"""

from __future__ import annotations

import json
import logging

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as HttpRequest
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .. import config
from ..services import Services, build_services
from .handlers import Request, dispatch

log = logging.getLogger("taxng")

# Strict policy for the public origin. The authenticated app (app.tax.ng,
# Phase 2) gets the same policy with no third-party sources at all (ADR-06).
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):  # type: ignore[override]
        response: Response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response


def create_app(services: Services | None = None) -> Starlette:
    services = services or build_services()
    if config.DEV_SECRET:
        log.warning("TAXNG_SECRET is not set; using the development secret.")

    async def api(request: HttpRequest) -> Response:
        body: dict = {}
        if request.method == "POST":
            raw = await request.body()
            if len(raw) > config.MAX_BODY_BYTES:
                return JSONResponse({"error": "payload_too_large"}, status_code=413)
            if raw:
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    return JSONResponse({"error": "invalid_json"}, status_code=400)
                if not isinstance(parsed, dict):
                    return JSONResponse({"error": "invalid_json", "message": "expected an object"}, status_code=400)
                body = parsed
        status, data = dispatch(
            services,
            Request(method=request.method, path=request.url.path, query=dict(request.query_params), body=body),
        )
        return JSONResponse(data, status_code=status, headers={"Cache-Control": "no-store"})

    routes: list = [Route("/api/{path:path}", api, methods=["GET", "POST"])]
    if config.WEB_DIST.exists():
        routes.append(Mount("/", StaticFiles(directory=config.WEB_DIST, html=True)))
    else:
        async def no_frontend(request: HttpRequest) -> Response:
            return PlainTextResponse("Frontend not built. Run: make web", status_code=503)

        routes.append(Route("/", no_frontend))

    return Starlette(routes=routes, middleware=[Middleware(SecurityHeaders)])
