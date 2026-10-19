"""Channels module: WhatsApp bot (CH-02) and localisation (CH-04, CH-05)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...store import register_events

if TYPE_CHECKING:
    from ...services import Services
    from .i18n import Localisation
    from .whatsapp import WhatsAppBot

register_events({"whatsapp_message": {"kind"}})


@dataclass
class Channels:
    whatsapp: WhatsAppBot
    i18n: Localisation


def init(services: Services) -> None:
    from .adapters import ProductionWhatsApp, SandboxWhatsApp
    from .i18n import Localisation
    from .whatsapp import WhatsAppBot

    services.adapters.register(SandboxWhatsApp, ProductionWhatsApp)
    services.modules["channels"] = Channels(WhatsAppBot(services), Localisation(services))
