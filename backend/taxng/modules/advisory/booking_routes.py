"""Booking, consent and engagement endpoints (ADV-02, ADV-03, ADV-05).

Client endpoints act only on the caller's own bookings and engagements; adviser
endpoints only on requests and engagements addressed to the caller's listing.
Anything else is a 404. Reading client data without a current consent is a 403.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...api.router import Request, route
from ...platform.access import require_user
from .routes import svc

if TYPE_CHECKING:
    from ...services import Services


# ------------------------------------------------------------------ client
@route("GET", "/api/advisory/intake-options")
def intake_options(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """ADV-02: what the client can choose to share before booking (from compliance.account_summary)."""
    p = require_user(request.principal)
    return 200, {"items": svc(services).bookings.intake_options(p.user_id)}


@route("POST", "/api/advisory/bookings")
def request_booking(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """ADV-02: records the pre-engagement consent, then the booking request with only the selected fields."""
    p = require_user(request.principal)
    booking = svc(services).bookings.request(p.user_id, request.body)
    services.store.record_event("adviser_booking_requested")
    return 201, booking


@route("GET", "/api/advisory/bookings")
def my_bookings(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    return 200, {"items": svc(services).bookings.client_bookings(p.user_id)}


@route("POST", "/api/advisory/bookings/{booking_id}/cancel")
def cancel_booking(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    return 200, svc(services).bookings.cancel(p.user_id, params["booking_id"])


@route("GET", "/api/advisory/engagements")
def my_engagements(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    return 200, {"items": svc(services).bookings.client_engagements(p.user_id)}


@route("POST", "/api/advisory/engagements/{engagement_id}/consent")
def grant_access(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """ADV-03: grant the adviser scoped read access to the latest health-check report."""
    p = require_user(request.principal)
    return 200, svc(services).bookings.grant(p.user_id, params["engagement_id"], request.body)


@route("DELETE", "/api/advisory/engagements/{engagement_id}/consent")
def revoke_access(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    return 200, svc(services).bookings.revoke(p.user_id, params["engagement_id"])


@route("GET", "/api/advisory/engagements/{engagement_id}/access-log")
def access_log(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    return 200, {"items": svc(services).bookings.access_log(p.user_id, params["engagement_id"])}


@route("POST", "/api/advisory/engagements/{engagement_id}/end")
def end_engagement(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Client or adviser ends the engagement; any delegated access is revoked."""
    p = require_user(request.principal)
    return 200, svc(services).bookings.end(p.user_id, params["engagement_id"])


@route("GET", "/api/advisory/consents")
def my_consents(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    return 200, svc(services).bookings.user_consents(p.user_id)


@route("POST", "/api/advisory/consents/{kind}")
def set_consent(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Marketing and findings-matching consents, each separate from booking consents (ADV-05)."""
    p = require_user(request.principal)
    return 200, svc(services).bookings.set_user_consent(p.user_id, params["kind"], request.body.get("granted"))


@route("GET", "/api/advisory/suggestions")
def suggestions(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """ADV-05: findings-based suggestions, empty with ``consent_required`` unless consent is given."""
    p = require_user(request.principal)
    return 200, svc(services).bookings.suggestions(p.user_id)


# ------------------------------------------------------------------ adviser portal
@route("GET", "/api/advisory/adviser/bookings")
def adviser_bookings(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    s = svc(services)
    return 200, {"items": s.bookings.adviser_bookings(s.adviser_for(p.user_id))}


@route("GET", "/api/advisory/adviser/bookings/{booking_id}")
def adviser_booking(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """One request with the client's shared intake. Every read is audited."""
    p = require_user(request.principal)
    s = svc(services)
    return 200, s.bookings.adviser_booking(s.adviser_for(p.user_id), params["booking_id"])


@route("POST", "/api/advisory/adviser/bookings/{booking_id}/decision")
def adviser_decision(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Accept (creates the engagement) or decline a request."""
    p = require_user(request.principal)
    s = svc(services)
    decision = str(request.body.get("decision", ""))
    result = s.bookings.decide(s.adviser_for(p.user_id), params["booking_id"], decision, str(request.body.get("note") or ""))
    services.store.record_event("adviser_booking_decided", {"decision": decision})
    return 200, result


@route("GET", "/api/advisory/adviser/engagements")
def adviser_engagements(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    s = svc(services)
    return 200, {"items": s.bookings.adviser_engagements(s.adviser_for(p.user_id))}


@route("GET", "/api/advisory/adviser/engagements/{engagement_id}/report")
def adviser_report(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """ADV-03: the client's report under an active engagement consent (403 otherwise). Audited."""
    p = require_user(request.principal)
    s = svc(services)
    return 200, s.bookings.adviser_report(s.adviser_for(p.user_id), params["engagement_id"])
