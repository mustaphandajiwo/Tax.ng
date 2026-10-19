"""Billing endpoints: plans, subscriptions, checkout, provider webhook, payments and receipts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...api.router import Request, route
from ...platform.access import CAN_ADMIN, Forbidden, NotFoundError, Principal, require_org, require_user
from .service import Billing

if TYPE_CHECKING:
    from ...services import Services


def _svc(services: Services) -> Billing:
    return services.modules["billing"]


def _session(request: Request) -> Principal:
    p = require_user(request.principal)
    if p.via != "session":
        raise Forbidden("Billing needs a signed-in session")
    return p


def _scope(request: Request, p: Principal) -> str | None:
    """Organisation billing is owner-only; without org_id the caller's personal billing is used."""
    org_id = str(request.query.get("org_id") or request.body.get("org_id") or "") or None
    if org_id:
        require_org(p, org_id, CAN_ADMIN)
    return org_id


@route("GET", "/api/billing/plans")
def plans(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    svc = _svc(services)
    return 200, {"items": svc.list_plans(), "mode": svc.adapter.mode, "note": "Commercial services only. Tax is paid to the tax authority directly, never through tax.ng."}


@route("GET", "/api/billing/subscriptions")
def subscriptions(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = _session(request)
    org_id = _scope(request, p)
    return 200, {"items": _svc(services).subscriptions(user_id=p.user_id, org_id=org_id)}


@route("POST", "/api/billing/subscriptions")
def subscribe(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = _session(request)
    org_id = _scope(request, p)
    quantity = request.body.get("quantity", 1)
    return 201, _svc(services).subscribe(actor_id=p.user_id, plan_id=str(request.body.get("plan_id", "")), org_id=org_id, quantity=quantity)


@route("POST", "/api/billing/subscriptions/{sub_id}/cancel")
def cancel_subscription(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = _session(request)
    svc = _svc(services)
    sub = svc._sub(params["sub_id"])
    if sub["org_id"]:
        require_org(p, sub["org_id"], CAN_ADMIN)
    elif sub["user_id"] != p.user_id:
        raise NotFoundError("Subscription not found")
    return 200, svc.cancel_subscription(sub, p.user_id)


@route("GET", "/api/billing/checkout/{checkout_id}")
def get_checkout(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = _session(request)
    svc = _svc(services)
    row = svc.payment_by_checkout(params["checkout_id"])
    if not svc.can_see(p.user_id, p.memberships, row):
        raise NotFoundError("Checkout not found")
    return 200, svc.checkout_view(row)


@route("POST", "/api/billing/checkout/{checkout_id}/complete")
def complete_checkout(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Sandbox only: simulates the provider's hosted page and delivers its signed webhook."""
    p = _session(request)
    return 200, _svc(services).simulate(params["checkout_id"], p.user_id, str(request.body.get("outcome", "paid")))


@route("POST", "/api/billing/webhooks/psp")
def psp_webhook(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Inbound provider webhook. No session: the HMAC signature (X-PSP-Signature) is the authentication."""
    return 200, _svc(services).handle_webhook(request.body, request.headers.get("x-psp-signature", ""))


@route("GET", "/api/billing/payments")
def payments(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = _session(request)
    org_id = _scope(request, p)
    svc = _svc(services)
    return 200, {"items": svc.payments(user_id=p.user_id, org_id=org_id), "mode": svc.adapter.mode}


@route("GET", "/api/billing/receipts/{receipt_id}")
def receipt(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = _session(request)
    svc = _svc(services)
    row = svc.receipt(params["receipt_id"])
    if not svc.can_see(p.user_id, p.memberships, row):
        raise NotFoundError("Receipt not found")
    return 200, svc.receipt_view(row)
