"""E-invoicing endpoints for the signed-in app. The public API lives in modules/developer/public_api.py."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...api.router import Request, route
from ...platform.access import CAN_EDIT, ORG_ROLES, Forbidden, Principal, require_org, require_user
from .service import EInvoicing

if TYPE_CHECKING:
    from ...services import Services


def _svc(services: Services) -> EInvoicing:
    return services.modules["einvoicing"]


def _member(request: Request, org_id: str, roles: tuple[str, ...] = ORG_ROLES) -> Principal:
    """Signed-in members only. API keys use /api/v1."""
    p = require_user(request.principal)
    if p.via != "session":
        raise Forbidden("Use the public API (/api/v1) with an API key")
    require_org(p, org_id, roles)
    return p


@route("GET", "/api/orgs/{org_id}/einvoices")
def list_invoices(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    _member(request, params["org_id"])
    return 200, _svc(services).list(params["org_id"], request.query.get("status") or None)


@route("POST", "/api/orgs/{org_id}/einvoices")
def create_invoice(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = _member(request, params["org_id"], CAN_EDIT)
    return 201, _svc(services).create(params["org_id"], p.user_id, request.body)


@route("GET", "/api/orgs/{org_id}/einvoices/{invoice_id}")
def get_invoice(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    _member(request, params["org_id"])
    return 200, _svc(services).get(params["org_id"], params["invoice_id"])


@route("PUT", "/api/orgs/{org_id}/einvoices/{invoice_id}")
def update_invoice(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = _member(request, params["org_id"], CAN_EDIT)
    return 200, _svc(services).update(params["org_id"], params["invoice_id"], p.user_id, request.body)


@route("POST", "/api/orgs/{org_id}/einvoices/{invoice_id}/validate")
def validate_invoice(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = _member(request, params["org_id"], CAN_EDIT)
    return 200, _svc(services).validate(params["org_id"], params["invoice_id"], p.user_id)


@route("POST", "/api/orgs/{org_id}/einvoices/{invoice_id}/submit")
def submit_invoice(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = _member(request, params["org_id"], CAN_EDIT)
    key = request.headers.get("idempotency-key") or request.body.get("idempotency_key")
    return 200, _svc(services).submit(params["org_id"], params["invoice_id"], p.user_id, idempotency_key=str(key) if key else None)


@route("POST", "/api/orgs/{org_id}/einvoices/{invoice_id}/retry")
def retry_invoice(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Exception queue: re-validate and resubmit a rejected or failed invoice."""
    p = _member(request, params["org_id"], CAN_EDIT)
    return 200, _svc(services).submit(params["org_id"], params["invoice_id"], p.user_id)


@route("POST", "/api/orgs/{org_id}/einvoices/{invoice_id}/cancel")
def cancel_invoice(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = _member(request, params["org_id"], CAN_EDIT)
    return 200, _svc(services).cancel(params["org_id"], params["invoice_id"], p.user_id, str(request.body.get("reason", "")))


@route("POST", "/api/orgs/{org_id}/einvoices/{invoice_id}/credit-note")
def credit_note(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = _member(request, params["org_id"], CAN_EDIT)
    return 201, _svc(services).credit_note(params["org_id"], params["invoice_id"], p.user_id, str(request.body.get("reason", "")))


@route("GET", "/api/orgs/{org_id}/einvoicing/exceptions")
def exception_queue(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    _member(request, params["org_id"])
    return 200, _svc(services).exceptions(params["org_id"])


@route("POST", "/api/orgs/{org_id}/einvoicing/sync")
def sync_status(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Status sync job. In the sandbox this produces and applies the signed NRS callbacks."""
    _member(request, params["org_id"], CAN_EDIT)
    return 200, _svc(services).sync(params["org_id"])


@route("POST", "/api/orgs/{org_id}/einvoicing/submit-validated")
def submit_validated(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = _member(request, params["org_id"], CAN_EDIT)
    source = str(request.body.get("source") or "") or None
    return 200, _svc(services).submit_validated(params["org_id"], p.user_id, source=source)


@route("POST", "/api/einvoicing/callbacks/nrs")
def nrs_callback(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Inbound status callback from NRS. No session: the HMAC signature is the authentication."""
    return 200, _svc(services).apply_callback(request.body, request.headers.get("x-nrs-signature", ""))
