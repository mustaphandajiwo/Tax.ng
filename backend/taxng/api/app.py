"""Starlette adapter: HTTP in, ``dispatch`` out, plus static files and headers.

Kept deliberately thin. See router.py for the dispatch contract.
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
from .router import Request, dispatch

log = logging.getLogger("taxng")

# Strict policy for both origins (ADR-06). The signed-in app (/app, app.tax.ng
# in production) never loads third-party code, and ad creatives on the public
# site are served from our own origin.
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
    if services.demo_mode:
        log.warning("Demo mode is on: the message outbox is readable at /api/dev/outbox. Set TAXNG_DEMO=0 in production.")

    async def api(request: HttpRequest) -> Response:
        body: dict = {}
        raw = b""
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            limit = config.MAX_UPLOAD_BODY_BYTES if request.url.path.endswith(config.UPLOAD_PATH_SUFFIX) else config.MAX_BODY_BYTES
            raw = await request.body()
            if len(raw) > limit:
                return JSONResponse({"error": "payload_too_large"}, status_code=413)
            if raw:
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    return JSONResponse({"error": "invalid_json"}, status_code=400)
                if not isinstance(parsed, dict):
                    return JSONResponse({"error": "invalid_json", "message": "expected an object"}, status_code=400)
                body = parsed
        reply = dispatch(
            services,
            Request(
                method=request.method,
                path=request.url.path,
                query=dict(request.query_params),
                body=body,
                headers={k.lower(): v for k, v in request.headers.items()},
                cookies=dict(request.cookies),
                raw_body=raw or None,
            ),
        )
        headers = {"Cache-Control": "no-store", **reply.headers}
        if reply.raw is not None:
            response: Response = Response(reply.raw, status_code=reply.status, media_type=reply.content_type, headers=headers)
        else:
            response = JSONResponse(reply.body, status_code=reply.status, headers=headers)
        for c in reply.cookies:
            response.set_cookie(
                c.name,
                c.value,
                max_age=c.max_age,
                path=c.path,
                httponly=c.http_only,
                samesite=c.same_site,  # type: ignore[arg-type]
                secure=not services.demo_mode,
            )
        return response

    routes: list = [Route("/api/{path:path}", api, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])]
    if config.WEB_DIST.exists():
        routes.append(Mount("/", StaticFiles(directory=config.WEB_DIST, html=True)))
    else:

        async def no_frontend(request: HttpRequest) -> Response:
            return PlainTextResponse("Frontend not built. Run: make web", status_code=503)

        routes.append(Route("/", no_frontend))

    return Starlette(routes=routes, middleware=[Middleware(SecurityHeaders)])
