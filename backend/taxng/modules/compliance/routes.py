"""Compliance endpoints: taxpayer profile and tax health check (HC-01 to HC-07).

All endpoints are personal: they need a signed-in user and only ever touch the
caller's own rows (``user_id = principal.user_id``). Another user's check is a
404, never a 403, so ids cannot be probed.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from ...api.router import Reply, Request, route
from ...platform.access import require_user
from ...platform.errors import Invalid
from .service import ComplianceService

if TYPE_CHECKING:
    from ...services import Services


def _svc(services: Services) -> ComplianceService:
    return services.modules["compliance"]


@route("GET", "/api/compliance/profile")
def get_profile(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """HC-01: the caller's saved profile facts and any contradictions in them."""
    p = require_user(request.principal)
    svc = _svc(services)
    profile = svc.get_profile(p.user_id)
    return 200, {**profile, "contradictions": svc.bank.active_contradictions(profile["facts"], svc.today())}


@route("PUT", "/api/compliance/profile")
def put_profile(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """HC-01: update profile facts. ``{"facts": {key: value | null}}``; null removes a fact."""
    p = require_user(request.principal)
    facts = request.body.get("facts")
    if not isinstance(facts, dict):
        raise Invalid("facts: must be an object")
    return 200, _svc(services).save_profile(p.user_id, facts)


@route("DELETE", "/api/compliance/profile")
def delete_profile(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Data minimisation: remove the saved profile."""
    p = require_user(request.principal)
    _svc(services).delete_profile(p.user_id)
    return 200, {"status": "deleted"}


@route("GET", "/api/compliance/obligations")
def my_obligations(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """HC-01/HC-02: obligations for the caller's profile in ``?year=``, with undetermined ones listed."""
    p = require_user(request.principal)
    svc = _svc(services)
    year = svc.parse_year(request.query.get("year", svc.today().year))
    return 200, {"year": year, **svc.evaluate(svc.get_profile(p.user_id)["facts"], year)}


@route("GET", "/api/compliance/checks")
def list_checks(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    return 200, {"items": _svc(services).list_checks(p.user_id)}


@route("POST", "/api/compliance/checks")
def start_check(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Start a health check for ``year``, or resume the open one (saved progress)."""
    p = require_user(request.principal)
    svc = _svc(services)
    year = svc.parse_year(request.body.get("year", svc.today().year))
    created, state = svc.start_check(p.user_id, year)
    if created:
        services.store.record_event("health_check_started", {"year": year})
    return (201 if created else 200), state


@route("GET", "/api/compliance/checks/{check_id}")
def get_check(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """HC-02: questionnaire state (visible questions, statuses, contradictions, obligations)."""
    p = require_user(request.principal)
    return 200, _svc(services).state(p.user_id, params["check_id"])


@route("PUT", "/api/compliance/checks/{check_id}/answers")
def save_answers(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """Save answers ``{"answers": {question_id: value | null}}``; profile questions update the profile."""
    p = require_user(request.principal)
    return 200, _svc(services).save_answers(p.user_id, params["check_id"], request.body.get("answers"))


@route("POST", "/api/compliance/checks/{check_id}/complete")
def complete_check(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    """HC-03 to HC-07: compute findings by dimension and freeze the report. 409 while contradictions remain."""
    p = require_user(request.principal)
    report = _svc(services).complete(p.user_id, params["check_id"])
    services.store.record_event("health_check_completed", {"year": report["year"]})
    return 200, report


@route("GET", "/api/compliance/checks/{check_id}/report")
def get_report(services: Services, request: Request, params: dict[str, str]) -> Reply:
    """HC-07: the report as JSON; ``?download=1`` returns it as a file."""
    p = require_user(request.principal)
    report = _svc(services).report(p.user_id, params["check_id"])
    if request.query.get("download") in ("1", "true"):
        return Reply(
            200,
            raw=json.dumps(report, indent=2, sort_keys=True).encode(),
            content_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="taxng-health-check-{report["year"]}.json"',
                "Cache-Control": "private, no-store",
            },
        )
    return Reply(200, report)


@route("DELETE", "/api/compliance/checks/{check_id}")
def delete_check(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    _svc(services).delete_check(p.user_id, params["check_id"])
    return 200, {"status": "deleted"}
