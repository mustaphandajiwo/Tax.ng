"""Advisory endpoints: public directory, adviser listings, staff review and sponsored placement (ADV-01, ADV-04, GOV-04).

Booking, consent and engagement endpoints live in ``booking_routes`` and are
registered by the import at the bottom of this file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...api.router import NotFound, Reply, Request, route
from ...platform.access import require_staff, require_user
from .policy import CONSENT_TEXT, ENGAGEMENT_SCOPES, PRACTITIONER_NOTICE, SPECIALISMS, STATES
from .service import AdvisoryService

if TYPE_CHECKING:
    from ...services import Services


def svc(services: Services) -> AdvisoryService:
    return services.modules["advisory"]


# ------------------------------------------------------------------ public
@route("GET", "/api/advisory/meta")
def meta(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Reference data and wording for the directory and booking forms."""
    return 200, {
        "specialisms": [{"id": k, "label": v} for k, v in SPECIALISMS.items()],
        "states": list(STATES),
        "practitioner_notice": PRACTITIONER_NOTICE,
        "consent_text": CONSENT_TEXT,
        "engagement_scopes": [{"id": k, "label": v} for k, v in ENGAGEMENT_SCOPES.items()],
        "register_mode": services.adapters.get("register").mode,
    }


@route("GET", "/api/advisory/directory")
def directory(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """ADV-04: approved advisers by relevance; paid placement only in the separate ``sponsored`` slot.

    Matching uses only the search parameters, never health-check findings (ADV-05).
    """
    specialism = request.query.get("specialism") or None
    state = request.query.get("state") or None
    result = svc(services).advisers.directory(specialism, state)
    services.store.record_event("adviser_directory_viewed", {"specialism": specialism or "", "state": state or ""})
    return 200, {**result, "sponsored_label": "Sponsored listing", "practitioner_notice": PRACTITIONER_NOTICE}


@route("GET", "/api/advisory/directory/{adviser_id}")
def directory_entry(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    advisers = svc(services).advisers
    row = advisers.row(params["adviser_id"])
    if row["status"] != "approved":
        raise NotFound("Adviser not found")
    return 200, {**advisers.public_view(row), "practitioner_notice": PRACTITIONER_NOTICE}


# ------------------------------------------------------------------ the caller's own listing
@route("POST", "/api/advisory/advisers")
def apply(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """ADV-01: apply to be listed. Register checks run at once; staff approve afterwards."""
    p = require_user(request.principal)
    advisers = svc(services).advisers
    row = advisers.apply(p.user_id, request.body)
    services.store.record_event("adviser_application_submitted")
    return 201, advisers.owner_view(row)


@route("GET", "/api/advisory/advisers/me")
def my_listing(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    advisers = svc(services).advisers
    return 200, advisers.owner_view(advisers.mine(p.user_id))


@route("PUT", "/api/advisory/advisers/me")
def update_listing(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Edit the listing. A changed membership number returns it to review and re-runs verification."""
    p = require_user(request.principal)
    advisers = svc(services).advisers
    return 200, advisers.owner_view(advisers.update_mine(p.user_id, request.body))


@route("POST", "/api/advisory/advisers/me/verify")
def reverify(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """ADV-01: annual re-verification, started by the adviser."""
    p = require_user(request.principal)
    advisers = svc(services).advisers
    row = advisers.mine(p.user_id)
    return 200, advisers.verify(row["id"], actor_id=p.user_id)


@route("GET", "/api/advisory/advisers/me/placements")
def my_placements(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    advisers = svc(services).advisers
    return 200, {"items": advisers.placements(advisers.mine(p.user_id)["id"])}


@route("POST", "/api/advisory/advisers/me/placements")
def buy_placement(services: Services, request: Request, params: dict[str, str]) -> Reply:
    """ADV-04: start a sponsored listing purchase through billing (purpose "advertising").

    Returns 503 ``billing_unavailable`` when the billing module is not installed.
    """
    p = require_user(request.principal)
    result = svc(services).advisers.start_placement(p.user_id)
    if not result["available"]:
        return Reply(503, {"error": "billing_unavailable", "message": result["message"]})
    services.store.record_event("adviser_placement_started")
    return Reply(201, result)


# ------------------------------------------------------------------ staff review
@route("GET", "/api/advisory/admin/advisers")
def staff_list(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    require_staff(request.principal, "support")
    return 200, {"items": svc(services).advisers.for_staff(request.query.get("status") or None)}


@route("POST", "/api/advisory/admin/advisers/{adviser_id}/decision")
def staff_decision(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Approve (needs a current verification), reject or suspend a listing."""
    staff = require_staff(request.principal, "support")
    advisers = svc(services).advisers
    row = advisers.decide(params["adviser_id"], staff.user_id, str(request.body.get("decision", "")), str(request.body.get("note") or ""))
    return 200, advisers.staff_view(row)


@route("POST", "/api/advisory/admin/advisers/{adviser_id}/verify")
def staff_verify(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    staff = require_staff(request.principal, "support")
    return 200, svc(services).advisers.verify(params["adviser_id"], actor_id=staff.user_id)


from . import booking_routes  # noqa: E402,F401  (registers the booking and engagement routes)
