"""Versioned public API (/api/v1, Phase 4, Annex A9).

Every operation runs through ``v1()``, which gives the API one behaviour:

* API-key authentication (``Authorization: Bearer tng_test_...``); session
  cookies are not accepted here.
* Scope check, then a per-key token-bucket rate limit (429 with Retry-After).
* ``Idempotency-Key`` on POSTs: the same key and body replay the stored
  response; the same key with a different body is a 409.
* ``X-Correlation-Id`` echoed (or generated) on every response, success or error.
* One error shape: ``{"error": code, "message", "fields"?, "correlation_id"}``.

The operations are documented in openapi.py; keep the two in step.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ...api.router import NotFound, Reply, Request, route
from ...calculators import CALCULATORS, InputError
from ...platform.access import Forbidden, NotFoundError, Unauthorized
from ...platform.adapters import NotConfigured
from ...platform.errors import Conflict, Invalid
from ...platform.util import canonical_json, new_id, sha256
from ...rules import ParameterError
from .openapi import document

if TYPE_CHECKING:
    from ...services import Services
    from .service import Developer

log = logging.getLogger("taxng.api.v1")
CORRELATION_RE = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")
V1Handler = Callable[["Services", Request, dict[str, str], dict[str, Any] | None], tuple[int, Any]]


def _error(status: int, code: str, message: str, cid: str, headers: dict[str, str], fields: dict[str, str] | None = None) -> Reply:
    body: dict[str, Any] = {"error": code, "message": message, "correlation_id": cid}
    if fields:
        body["fields"] = fields
    return Reply(status, body, headers=headers)


def _map(exc: Exception) -> tuple[int, str, str, dict[str, str] | None] | None:
    if isinstance(exc, InputError):
        return 422, "invalid_input", "Some fields are invalid", exc.errors
    if isinstance(exc, Invalid):
        name, sep, message = str(exc).partition(": ")
        return 422, "invalid_input", "Some fields are invalid", {name: message} if sep else {"_": str(exc)}
    if isinstance(exc, ParameterError):
        return 422, "rule_not_in_force", str(exc), None
    if isinstance(exc, Unauthorized):
        return 401, "unauthorized", str(exc), None
    if isinstance(exc, Forbidden):
        return 403, "forbidden", str(exc), None
    if isinstance(exc, (NotFound, NotFoundError)):
        return 404, "not_found", str(exc), None
    if isinstance(exc, Conflict):
        return 409, "conflict", str(exc), None
    if isinstance(exc, NotConfigured):
        return 503, "integration_not_configured", str(exc), None
    return None


def v1(method: str, path: str, scope: str | None, *, idempotent: bool = False) -> Callable[[V1Handler], V1Handler]:
    """``scope=None``: public. ``scope=""``: any valid key. Otherwise the key must hold ``scope``."""

    def wrap(fn: V1Handler) -> V1Handler:
        @route(method, path)
        def handler(services: Services, request: Request, params: dict[str, str]) -> Reply:
            incoming = request.headers.get("x-correlation-id", "")
            cid = incoming if CORRELATION_RE.match(incoming) else new_id("corr")
            headers = {"X-Correlation-Id": cid, "X-TaxNG-API-Version": "v1"}
            dev: Developer = services.modules["developer"]
            key: dict[str, Any] | None = None
            idem: tuple[str, str] | None = None
            try:
                if scope is not None:
                    p = request.principal
                    key = dev.key_row(p.user_id) if p is not None and p.via == "api_key" else None
                    if key is None:
                        return _error(401, "unauthorized", "Send a valid API key: Authorization: Bearer <key>", cid, headers)
                    allowed, remaining, retry_after = dev.limiter.take(key["id"], key["rate_per_minute"])
                    headers.update({"X-RateLimit-Limit": str(key["rate_per_minute"]), "X-RateLimit-Remaining": str(remaining)})
                    if not allowed:
                        headers["Retry-After"] = str(retry_after)
                        return _error(429, "rate_limited", f"Rate limit of {key['rate_per_minute']} requests per minute reached", cid, headers)
                    if scope and scope not in p.scopes:  # type: ignore[union-attr]
                        return _error(403, "insufficient_scope", f"This API key lacks the {scope} scope", cid, headers)
                    raw_key = request.headers.get("idempotency-key")
                    if idempotent and raw_key is not None:
                        raw_key = raw_key.strip()
                        if not 1 <= len(raw_key) <= 100:
                            return _error(422, "invalid_input", "Some fields are invalid", cid, headers, {"Idempotency-Key": "use 1 to 100 characters"})
                        request_hash = sha256(canonical_json([method, request.path, request.body]))
                        stored = dev.idempotent_lookup(key["id"], raw_key)
                        if stored:
                            if stored["request_hash"] != request_hash:
                                return _error(409, "idempotency_conflict", "This Idempotency-Key was used with a different request", cid, headers)
                            return Reply(stored["status"], json.loads(stored["response_json"]), headers={**headers, "Idempotent-Replayed": "true"})
                        idem = (raw_key, request_hash)
                status, body = fn(services, request, params, key)
                if idem and key:
                    dev.idempotent_store(key["id"], idem[0], idem[1], status, body)
                return Reply(status, body, headers=headers)
            except Exception as exc:  # noqa: BLE001 - mapped to the error taxonomy below
                mapped = _map(exc)
                if mapped is None:
                    log.exception("v1 handler failed (correlation %s)", cid)
                    return _error(500, "internal_error", "Something went wrong", cid, headers)
                status, code, message, fields = mapped
                reply = _error(status, code, message, cid, headers, fields)
                if idem and key and status < 500:
                    dev.idempotent_store(key["id"], idem[0], idem[1], status, reply.body)
                return reply

        return fn

    return wrap


def _einvoicing(services: Services) -> Any:
    svc = services.modules.get("einvoicing")
    if svc is None:
        raise NotConfigured("einvoicing module is not installed")
    return svc


@v1("GET", "/api/v1/openapi.json", None)
def openapi_json(services: Services, request: Request, params: dict[str, str], key: dict[str, Any] | None) -> tuple[int, Any]:
    mode = services.adapters.get("einvoicing").mode if "einvoicing" in services.adapters.kinds() else "sandbox"
    return 200, document(mode)


@v1("GET", "/api/v1/key", "")
def whoami(services: Services, request: Request, params: dict[str, str], key: dict[str, Any] | None) -> tuple[int, Any]:
    assert key is not None
    view = services.modules["developer"].key_view(key)
    return 200, {k: view[k] for k in ("id", "prefix", "org_id", "scopes", "rate_per_minute", "mode")}


@v1("POST", "/api/v1/calculate/{calculator}", "calculators:read")
def calculate(services: Services, request: Request, params: dict[str, str], key: dict[str, Any] | None) -> tuple[int, Any]:
    calc = CALCULATORS.get(params["calculator"])
    if calc is None:
        raise NotFound(f"Unknown calculator {params['calculator']}")
    return 200, calc(request.body, services.tree).to_dict()


@v1("GET", "/api/v1/parameters/{name}", "rules:read")
def parameter(services: Services, request: Request, params: dict[str, str], key: dict[str, Any] | None) -> tuple[int, Any]:
    tree, name = services.tree, params["name"]
    if not tree.has(name):
        raise NotFound(f"Unknown parameter {name}")
    raw = request.query.get("on")
    try:
        on = dt.date.fromisoformat(raw) if raw else dt.date.today()
    except ValueError:
        raise InputError({"on": "must be a date (YYYY-MM-DD)"}) from None
    info = tree.info(name)
    card: dict[str, Any] = {
        "name": name,
        "on": on.isoformat(),
        "description": info.description,
        "unit": info.unit,
        "review_status": info.review_status,
        "reference": info.reference,
        "rules_version": tree.version,
        "in_force": True,
    }
    try:
        if tree.is_scale(name):
            card["scale"] = [{"threshold": str(b.threshold), "rate": str(b.rate)} for b in tree.scale(name, on)]
        else:
            value = tree.value(name, on)
            card["value"] = value if isinstance(value, (list, bool)) else str(value)
    except ParameterError:
        card["in_force"] = False
    return 200, card


@v1("GET", "/api/v1/einvoices", "einvoices:read")
def list_einvoices(services: Services, request: Request, params: dict[str, str], key: dict[str, Any] | None) -> tuple[int, Any]:
    assert key is not None
    return 200, _einvoicing(services).list(key["org_id"], request.query.get("status") or None)


@v1("POST", "/api/v1/einvoices", "einvoices:write", idempotent=True)
def create_einvoice(services: Services, request: Request, params: dict[str, str], key: dict[str, Any] | None) -> tuple[int, Any]:
    assert key is not None
    return 201, _einvoicing(services).create(key["org_id"], key["id"], request.body, source="api")


@v1("GET", "/api/v1/einvoices/{invoice_id}", "einvoices:read")
def get_einvoice(services: Services, request: Request, params: dict[str, str], key: dict[str, Any] | None) -> tuple[int, Any]:
    assert key is not None
    return 200, _einvoicing(services).get(key["org_id"], params["invoice_id"])


@v1("POST", "/api/v1/einvoices/{invoice_id}/submit", "einvoices:write", idempotent=True)
def submit_einvoice(services: Services, request: Request, params: dict[str, str], key: dict[str, Any] | None) -> tuple[int, Any]:
    assert key is not None
    idem = request.headers.get("idempotency-key")
    return 200, _einvoicing(services).submit(key["org_id"], params["invoice_id"], key["id"], idempotency_key=f"api:{idem.strip()}" if idem else None)
