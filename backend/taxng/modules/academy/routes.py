"""Academy endpoints. Public: catalogue, outline, certificate verification. Signed in: learning."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...api.router import Request, route
from ...platform.access import CAN_ADMIN, require_org, require_staff, require_user

if TYPE_CHECKING:
    from ...services import Services
    from .service import Academy


def _academy(services: Services) -> Academy:
    academy: Academy = services.modules["academy"]
    _ = academy.billing  # registers the payment handler once billing exists
    return academy


# ------------------------------------------------------------------- public
@route("GET", "/api/academy/courses")
def catalogue(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    a = _academy(services)
    return 200, {"items": [a.summary(c) for c in a.courses.values()], "payments_available": a.payments_available()}


@route("GET", "/api/academy/courses/{course_id}")
def outline(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    a = _academy(services)
    body = a.outline(a.course(params["course_id"]))
    body["my_enrolment"] = None
    if request.principal is not None:
        row = services.db.one(
            "SELECT * FROM academy_enrolments WHERE user_id = ? AND course_id = ?", (request.principal.user_id, params["course_id"])
        )
        body["my_enrolment"] = a.enrolment_view(a._reconcile("academy_enrolments", row)) if row else None
    return 200, body


@route("GET", "/api/academy/certificates/{code}")
def verify_certificate(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    return 200, _academy(services).verify_certificate(params["code"])


# --------------------------------------------------------------- learners
@route("POST", "/api/academy/courses/{course_id}/enrol")
def enrol(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    cohort = request.body.get("cohort_id")
    return 201, _academy(services).enrol(p.user_id, params["course_id"], str(cohort) if cohort else None)


@route("GET", "/api/academy/me/enrolments")
def my_enrolments(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    return 200, {"items": _academy(services).my_enrolments(p.user_id)}


@route("GET", "/api/academy/enrolments/{enrolment_id}")
def player(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    return 200, _academy(services).player(p.user_id, params["enrolment_id"])


@route("POST", "/api/academy/enrolments/{enrolment_id}/lessons/{lesson_id}/complete")
def complete_lesson(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    return 200, _academy(services).complete_lesson(p.user_id, params["enrolment_id"], params["lesson_id"])


@route("POST", "/api/academy/enrolments/{enrolment_id}/quizzes/{quiz_id}/attempts")
def attempt(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    return 201, _academy(services).grade(p.user_id, params["enrolment_id"], params["quiz_id"], request.body.get("answers"))


@route("POST", "/api/academy/enrolments/{enrolment_id}/certificate")
def certificate(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    p = require_user(request.principal)
    name = str(request.body.get("name") or p.name or "")
    return 201, _academy(services).issue_certificate(p.user_id, params["enrolment_id"], name)


# ------------------------------------------------------ institutional seats
@route("GET", "/api/academy/orgs/{org_id}/seats")
def list_seats(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    require_org(request.principal, params["org_id"], CAN_ADMIN)
    members = services.db.query(
        "SELECT u.id, u.email, u.name, m.role FROM memberships m JOIN users u ON u.id = m.user_id WHERE m.org_id = ? ORDER BY u.email",
        (params["org_id"],),
    )
    return 200, {"items": _academy(services).seat_pools(params["org_id"]), "members": members}


@route("POST", "/api/academy/orgs/{org_id}/seats")
def buy_seats(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    require_org(request.principal, params["org_id"], CAN_ADMIN)
    return 201, _academy(services).buy_seats(
        request.principal.user_id, params["org_id"], str(request.body.get("course_id", "")), request.body.get("seats")  # type: ignore[union-attr]
    )


@route("POST", "/api/academy/orgs/{org_id}/seats/{pool_id}/assign")
def assign_seat(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    require_org(request.principal, params["org_id"], CAN_ADMIN)
    return 201, _academy(services).assign_seat(
        request.principal.user_id, params["org_id"], params["pool_id"], str(request.body.get("user_id", ""))  # type: ignore[union-attr]
    )


# ------------------------------------------------------------ staff: CPD
@route("POST", "/api/academy/courses/{course_id}/cpd")
def approve_cpd(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    staff = require_staff(request.principal, "editor", "legal_reviewer")
    return 201, _academy(services).approve_cpd(
        staff.user_id, params["course_id"], str(request.body.get("body", "")), str(request.body.get("reference", ""))
    )


@route("POST", "/api/academy/courses/{course_id}/cpd/withdraw")
def withdraw_cpd(services: Services, request: Request, params: dict[str, str]) -> tuple[int, Any]:
    staff = require_staff(request.principal, "editor", "legal_reviewer")
    _academy(services).withdraw_cpd(staff.user_id, params["course_id"])
    return 200, {"status": "withdrawn"}
