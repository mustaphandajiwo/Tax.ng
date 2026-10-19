"""Advisory module: adviser directory, verification, bookings and engagements (PRD Phase 2, ADV-01 to ADV-05, GOV-04).

``init`` registers the "register" adapter kind (CITN and ICAN membership
checks), publishes :class:`~.service.AdvisoryService` as
``services.modules["advisory"]`` and, when billing is available, registers the
"advertising" payment handler for sponsored listings. Because modules
initialise in name order (advisory before billing), ``post_init`` and the
checkout path register the handler again if needed; registration happens once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...store import register_events

if TYPE_CHECKING:
    from ...services import Services

# AN-01: whitelisted, non-personal analytics properties only.
register_events(
    {
        "adviser_directory_viewed": {"specialism", "state"},
        "adviser_application_submitted": set(),
        "adviser_booking_requested": set(),
        "adviser_booking_decided": {"decision"},
        "adviser_placement_started": set(),
    }
)


def init(services: Services) -> None:
    from .adapters import ProductionRegister, SandboxRegister
    from .advisers import register_payment_handler
    from .service import AdvisoryService

    services.adapters.register(SandboxRegister, ProductionRegister)
    services.modules["advisory"] = AdvisoryService(services)
    register_payment_handler(services)


def post_init(services: Services) -> None:
    """Second-phase hook (see the recommended change to ``services.py``): wire billing once every module exists."""
    from .advisers import register_payment_handler

    register_payment_handler(services)
