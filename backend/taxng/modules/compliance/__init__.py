"""Compliance module: taxpayer profile, obligations engine and tax health check (PRD Phase 2, HC-01 to HC-07).

``init`` loads the obligation rules (``rules/obligations``) and the question
bank (``content/compliance/questions.yaml``), validating both against the
parameter tree, and publishes :class:`~.service.ComplianceService` as
``services.modules["compliance"]``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...store import register_events

if TYPE_CHECKING:
    from ...services import Services

# AN-01: whitelisted, non-personal analytics properties only.
register_events(
    {
        "health_check_started": {"year"},
        "health_check_completed": {"year"},
    }
)


def init(services: Services) -> None:
    from .service import ComplianceService

    services.modules["compliance"] = ComplianceService(services)
