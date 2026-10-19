"""E-invoicing module (PRD 5, EINV-01 to EINV-03). See service.py."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .adapters import ProductionNrsEInvoicing, SandboxNrsEInvoicing
from .service import EInvoicing

if TYPE_CHECKING:
    from ...services import Services


def init(services: Services) -> None:
    services.adapters.register(SandboxNrsEInvoicing, ProductionNrsEInvoicing)
    services.modules["einvoicing"] = EInvoicing(services)
