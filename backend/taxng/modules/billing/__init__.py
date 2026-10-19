"""Billing module: commercial payments only (PRD section 9). See service.py."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .adapters import ProductionPsp, SandboxPsp
from .service import Billing

if TYPE_CHECKING:
    from ...services import Services


def init(services: Services) -> None:
    services.adapters.register(SandboxPsp, ProductionPsp)
    billing = Billing(services)
    billing.register_payment_handler("subscription", billing.activate_subscription)
    services.modules["billing"] = billing
