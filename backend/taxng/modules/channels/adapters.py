"""WhatsApp delivery adapters (CH-02)."""

from __future__ import annotations

from typing import Any

from ...platform.adapters import Adapter


class SandboxWhatsApp(Adapter):
    kind = "whatsapp"
    name = "sandbox-whatsapp"
    mode = "sandbox"
    description = "Writes bot replies to the message outbox (channel whatsapp). Nothing is sent to a phone."

    def send(self, notifier: Any, recipient_ref: str, phone: str, body: str) -> str:
        # The outbox records a pseudonymous reference, never the phone number.
        return notifier.send("whatsapp", recipient_ref, body)


class ProductionWhatsApp(Adapter):
    kind = "whatsapp"
    name = "production-whatsapp"
    mode = "production"
    description = "WhatsApp Business API through a business solution provider (BSP)."

    def send(self, notifier: Any, recipient_ref: str, phone: str, body: str) -> str:
        self.not_configured(
            "a WhatsApp Business API provider (BSP) account, a verified business phone number and approved message templates"
        )
