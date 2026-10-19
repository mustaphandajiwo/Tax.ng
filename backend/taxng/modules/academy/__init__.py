"""Academy module: courses, enrolment, graded quizzes, certificates, seats and CPD (PRD section 8)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...store import register_events

if TYPE_CHECKING:
    from ...services import Services

register_events({"academy_enrolled": {"course", "source"}, "academy_certificate_issued": {"course"}})


def init(services: Services) -> None:
    from .service import Academy

    services.modules["academy"] = Academy(services)


def post_init(services: Services) -> None:
    """Runs after every module's init once services.py supports it (see the report).

    Billing sorts after academy, so at ``init`` time billing is not registered
    yet. Touching ``.billing`` registers the "course" payment handler. Until
    the shared hook lands, the handler is registered lazily on the first
    academy request.
    """
    _ = services.modules["academy"].billing
