"""Framework-free routing: ``Request`` in, ``Reply`` out.

Handlers are plain functions ``(services, request, params) -> Reply | (status, body)``
registered with ``@route(method, pattern)``. ``dispatch`` resolves the caller
(session cookie or API key), applies the CSRF guard, runs the handler and maps
errors to HTTP statuses:

    InputError, Invalid ("field: message")  -> 422 {"error": "invalid_input", "fields": {...}}
    ParameterError                          -> 422 {"error": "rule_not_in_force"}
    Unauthorized                            -> 401
    Forbidden                               -> 403
    NotFound / NotFoundError                -> 404
    Conflict                                -> 409
    NotConfigured (production adapter)      -> 503 {"error": "integration_not_configured"}
    ProviderUnavailable (upstream failure)  -> 503 {"error": "integration_unavailable"}

The Starlette adapter (app.py) and the tests both call ``dispatch``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..calculators import InputError
from ..platform.access import Forbidden, NotFoundError, Principal, Unauthorized, principal_from_user
from ..platform.adapters import NotConfigured, ProviderUnavailable
from ..platform.auth import SESSION_COOKIE
from ..platform.errors import Conflict, Invalid
from ..rules import ParameterError

if TYPE_CHECKING:
    from ..services import Services

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "taxng"


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)  # lower-case names
    cookies: dict[str, str] = field(default_factory=dict)
    principal: Principal | None = None
    raw_body: bytes | None = None  # exact bytes received, for webhook signatures


@dataclass
class Cookie:
    name: str
    value: str
    max_age: int | None = None  # seconds; 0 deletes
    http_only: bool = True
    same_site: str = "lax"
    path: str = "/"


@dataclass
class Reply:
    status: int
    body: Any = None
    cookies: list[Cookie] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    raw: bytes | None = None  # file downloads, RSS
    content_type: str | None = None

    def __iter__(self) -> Iterator[Any]:
        """Lets tests write ``status, body = dispatch(...)``."""
        yield self.status
        yield self.body

    def __getitem__(self, index: int) -> Any:
        return (self.status, self.body)[index]


class NotFound(LookupError):
    pass


Handler = Callable[["Services", Request, dict[str, str]], "Reply | tuple[int, Any]"]
_ROUTES: list[tuple[str, re.Pattern[str], Handler]] = []


def route(method: str, pattern: str) -> Callable[[Handler], Handler]:
    regex = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[A-Za-z0-9_.\-]+)", pattern) + "$")

    def register(fn: Handler) -> Handler:
        _ROUTES.append((method, regex, fn))
        return fn

    return register


def routes() -> list[tuple[str, str]]:
    return [(m, r.pattern) for m, r, _ in _ROUTES]


def _fields(exc: Exception) -> dict[str, str]:
    name, sep, message = str(exc).partition(": ")
    return {name: message} if sep else {"_": str(exc)}


def _resolve_principal(services: Services, request: Request) -> None:
    if request.principal is not None:
        return
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        user = services.auth.user_for_token(token)
        if user:
            memberships = services.db.query("SELECT org_id, role FROM memberships WHERE user_id = ?", (user["id"],))
            request.principal = principal_from_user(user, memberships)
            return
    auth_header = request.headers.get("authorization", "")
    resolver = services.hooks.get("api_key")
    # API keys authenticate the versioned public API only; session routes never
    # accept them, so a key cannot reach account or workspace endpoints.
    if auth_header.lower().startswith("bearer ") and resolver and request.path.startswith("/api/v1/"):
        request.principal = resolver(services, auth_header[7:].strip())


def dispatch(services: Services, request: Request) -> Reply:
    _resolve_principal(services, request)
    allowed: list[str] = []
    for method, regex, fn in _ROUTES:
        match = regex.match(request.path)
        if not match:
            continue
        if method != request.method:
            allowed.append(method)
            continue
        if (
            request.method in UNSAFE_METHODS
            and SESSION_COOKIE in request.cookies
            and request.headers.get(CSRF_HEADER) != CSRF_VALUE
        ):
            return Reply(403, {"error": "csrf", "message": f"Send header X-Requested-With: {CSRF_VALUE}"})
        try:
            result = fn(services, request, match.groupdict())
        except InputError as exc:
            return Reply(422, {"error": "invalid_input", "fields": exc.errors})
        except Invalid as exc:
            return Reply(422, {"error": "invalid_input", "fields": _fields(exc)})
        except ParameterError as exc:
            return Reply(422, {"error": "rule_not_in_force", "message": str(exc)})
        except Unauthorized as exc:
            return Reply(401, {"error": "unauthorized", "message": str(exc)})
        except Forbidden as exc:
            return Reply(403, {"error": "forbidden", "message": str(exc)})
        except (NotFound, NotFoundError) as exc:
            return Reply(404, {"error": "not_found", "message": str(exc)})
        except Conflict as exc:
            return Reply(409, {"error": "conflict", "message": str(exc)})
        except NotConfigured as exc:
            return Reply(503, {"error": "integration_not_configured", "message": str(exc)})
        except ProviderUnavailable as exc:
            return Reply(503, {"error": "integration_unavailable", "message": str(exc)})
        return result if isinstance(result, Reply) else Reply(result[0], result[1])
    if allowed:
        return Reply(405, {"error": "method_not_allowed", "allowed": allowed})
    return Reply(404, {"error": "not_found", "message": f"No route for {request.path}"})
