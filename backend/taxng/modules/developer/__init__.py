"""Developer platform (Phase 4): API keys, public API, webhooks and ERP connectors. See service.py."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .adapters import ProductionWebhookDelivery, SandboxWebhookDelivery
from .service import Developer

if TYPE_CHECKING:
    from ...services import Services


def init(services: Services) -> None:
    services.adapters.register(SandboxWebhookDelivery, ProductionWebhookDelivery)
    developer = Developer(services)
    services.modules["developer"] = developer
    services.hooks["api_key"] = developer.resolve
