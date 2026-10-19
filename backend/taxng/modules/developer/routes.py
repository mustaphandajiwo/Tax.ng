"""Developer endpoints for the signed-in app: API keys, webhooks, ERP import and reconciliation.

The public API (/api/v1) is registered from public_api.py.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import TYPE_CHECKING, Any

from ...api.router import Request, route
from ...platform.access import CAN_ADMIN, CAN_EDIT, ORG_ROLES, Forbidden, NotFoundError, Principal, require_org, require_user
from ...platform.errors import Invalid
from ...platform.util import iso, new_id
from . import public_api  # noqa: F401  (registers /api/v1 routes)
from .connectors import FileConnector, LiveApiConnector, load_profiles, source_for
from .service import RETRY_SCHEDULE_SECONDS, SCOPES, WEBHOOK_EVENTS, Developer

if TYPE_CHECKING:
    from ...services import Services

MAX_IMPORT_BYTES = 2 * 1024 * 1024


def _svc(services: Services) -> Developer:
    return services.modules["developer"]


def _member(request: Request, org_id: str, roles: tuple[str, ...] = ORG_ROLES) -> Principal:
    p = require_user(request.principal)
    if p.via != "session":
        raise Forbidden("Manage integrations from a signed-in session")
    require_org(p, org_id, roles)
    return p


@route("GET", "/api/developer/catalogue")
def catalogue(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Public: scopes, webhook events, ERP profiles and modes, for the developer pages."""
    profiles = load_profiles(services)
    return 200, {
        "scopes": [{"id": k, "description": v} for k, v in SCOPES.items()],
        "events": [{"id": k, "description": v} for k, v in WEBHOOK_EVENTS.items()],
        "retry_schedule_seconds": list(RETRY_SCHEDULE_SECONDS),
        "erp_profiles": [
            {"id": pid, "label": p["label"], "status": p.get("status"), "mapping_status": p.get("mapping_status"), "live_sync": p.get("live_sync"), "columns": p["columns"]}
            for pid, p in profiles.items()
        ],
        "openapi_url": "/api/v1/openapi.json",
        "modes": {k: services.adapters.get(k).mode for k in ("einvoicing", "webhook_delivery") if k in services.adapters.kinds()},
    }


# ------------------------------------------------------------------ API keys
@route("GET", "/api/orgs/{org_id}/api-keys")
def list_keys(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    _member(request, params["org_id"], CAN_ADMIN)
    return 200, {"items": _svc(services).list_keys(params["org_id"])}


@route("POST", "/api/orgs/{org_id}/api-keys")
def create_key(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = _member(request, params["org_id"], CAN_ADMIN)
    b = request.body
    return 201, _svc(services).create_key(params["org_id"], p.user_id, b.get("name"), b.get("scopes"), b.get("rate_per_minute"))


@route("POST", "/api/orgs/{org_id}/api-keys/{key_id}/revoke")
def revoke_key(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = _member(request, params["org_id"], CAN_ADMIN)
    return 200, _svc(services).revoke_key(params["org_id"], params["key_id"], p.user_id)


# ------------------------------------------------------------------ webhooks
@route("GET", "/api/orgs/{org_id}/webhooks")
def list_webhooks(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    _member(request, params["org_id"], CAN_ADMIN)
    svc = _svc(services)
    return 200, {"items": svc.list_endpoints(params["org_id"]), "mode": svc.delivery.mode}


@route("POST", "/api/orgs/{org_id}/webhooks")
def add_webhook(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = _member(request, params["org_id"], CAN_ADMIN)
    return 201, _svc(services).add_endpoint(params["org_id"], p.user_id, request.body.get("url"), request.body.get("events"))


@route("POST", "/api/orgs/{org_id}/webhooks/{endpoint_id}/disable")
def disable_webhook(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = _member(request, params["org_id"], CAN_ADMIN)
    return 200, _svc(services).disable_endpoint(params["org_id"], params["endpoint_id"], p.user_id)


@route("GET", "/api/orgs/{org_id}/webhook-deliveries")
def deliveries(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    _member(request, params["org_id"], CAN_ADMIN)
    svc = _svc(services)
    return 200, {"items": svc.deliveries(params["org_id"]), "mode": svc.delivery.mode}


@route("POST", "/api/orgs/{org_id}/webhook-deliveries/{delivery_id}/replay")
def replay(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = _member(request, params["org_id"], CAN_ADMIN)
    return 200, _svc(services).replay(params["org_id"], params["delivery_id"], p.user_id)


# ----------------------------------------------------------------------- ERP
def _import_text(body: dict[str, Any]) -> str:
    if body.get("data_base64"):
        try:
            raw = base64.b64decode(str(body["data_base64"]), validate=True)
        except (binascii.Error, ValueError):
            raise Invalid("data_base64: not valid base64") from None
    else:
        raw = str(body.get("content") or "").encode()
    if len(raw) > MAX_IMPORT_BYTES:
        raise Invalid("content: files up to 2 MB")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Invalid("content: save the export as UTF-8 text") from None


@route("POST", "/api/orgs/{org_id}/erp/import")
def erp_import(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = _member(request, params["org_id"], CAN_EDIT)
    einvoicing = services.modules.get("einvoicing")
    if einvoicing is None:
        raise NotFoundError("E-invoicing is not available")
    body = request.body
    profiles = load_profiles(services)
    profile_id = str(body.get("profile") or "")
    profile = profiles.get(profile_id)
    if profile is None:
        raise Invalid(f"profile: choose one of {', '.join(profiles)}")
    filename = str(body.get("filename") or "")[:200] or None
    fmt = str(body.get("format") or (filename.rsplit(".", 1)[-1].lower() if filename and "." in filename else "csv"))
    connector = FileConnector()
    rows = connector.fetch({"format": fmt, "text": _import_text(body)})
    invoices = connector.map(rows, profile)
    if not invoices:
        raise Invalid(f"content: no rows had a value in the {profile['columns']['external_id']} column")
    source = source_for(profile_id)
    result = einvoicing.import_invoices(params["org_id"], p.user_id, invoices, source=source)
    import_id = new_id("imp")
    services.db.insert(
        "erp_imports",
        {
            "id": import_id,
            "org_id": params["org_id"],
            "profile": profile_id,
            "source": source,
            "filename": filename,
            "rows": len(rows),
            "counts_json": json.dumps(result["counts"]),
            "created_by": p.user_id,
            "created_at": iso(),
        },
    )
    _svc(services).emit(params["org_id"], "erp.import.completed", {"import_id": import_id, "profile": profile_id, "counts": result["counts"]})
    return 201, {"import_id": import_id, "profile": profile_id, "rows": len(rows), **result}


@route("POST", "/api/orgs/{org_id}/erp/sync/{profile}")
def erp_live_sync(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Live ERP sync: needs licensed API access, so this answers 503 integration_not_configured."""
    _member(request, params["org_id"], CAN_EDIT)
    profile = load_profiles(services).get(params["profile"])
    if profile is None:
        raise NotFoundError("Unknown ERP profile")
    LiveApiConnector(params["profile"], profile).fetch({})
    return 200, {}


@route("GET", "/api/orgs/{org_id}/erp/reconciliation")
def reconciliation(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    _member(request, params["org_id"])
    einvoicing = services.modules.get("einvoicing")
    if einvoicing is None:
        raise NotFoundError("E-invoicing is not available")
    connector = FileConnector()
    reports = [connector.reconcile(services, params["org_id"], s) for s in einvoicing.sources(params["org_id"], "erp:")]
    imports = services.db.query(
        "SELECT id, profile, source, filename, rows, counts_json, created_at FROM erp_imports WHERE org_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 50",
        (params["org_id"],),
    )
    return 200, {
        "sources": reports,
        "imports": [{**{k: v for k, v in r.items() if k != "counts_json"}, "counts": json.loads(r["counts_json"])} for r in imports],
        "mode": einvoicing.adapter.mode,
    }
