"""Outbound notifications (email, SMS, WhatsApp) through a provider adapter.

Every message is written to the ``outbox`` table first. The sandbox provider
stops there; a production provider also sends it. In demo mode the outbox can
be read at ``GET /api/dev/outbox`` so OTP codes are visible without email.
"""

from __future__ import annotations

from typing import Any

from ..db import Database
from .adapters import Adapter
from .util import iso, new_id


class SandboxMessaging(Adapter):
    kind = "messaging"
    name = "sandbox-messaging"
    mode = "sandbox"
    description = "Stores messages in the outbox only. Nothing is sent."

    def deliver(self, channel: str, recipient: str, subject: str, body: str) -> None:
        return None


class ProductionMessaging(Adapter):
    kind = "messaging"
    name = "production-messaging"
    mode = "production"
    description = "Email (SMTP/ESP), SMS gateway and WhatsApp Business API. Requires provider credentials."

    def deliver(self, channel: str, recipient: str, subject: str, body: str) -> None:
        self.not_configured("messaging provider credentials (email, SMS and WhatsApp Business API)")


class Notifier:
    def __init__(self, db: Database, provider: Adapter) -> None:
        self.db = db
        self.provider = provider

    def send(self, channel: str, recipient: str, body: str, *, subject: str = "") -> str:
        message_id = new_id("msg")
        self.db.insert(
            "outbox",
            {
                "id": message_id,
                "channel": channel,
                "recipient": recipient,
                "subject": subject,
                "body": body,
                "provider": self.provider.name,
                "mode": self.provider.mode,
                "created_at": iso(),
            },
        )
        self.provider.deliver(channel, recipient, subject, body)  # type: ignore[attr-defined]
        return message_id

    def recent(self, recipient: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if recipient:
            return self.db.query(
                "SELECT * FROM outbox WHERE recipient = ? ORDER BY created_at DESC, rowid DESC LIMIT ?", (recipient, limit)
            )
        return self.db.query("SELECT * FROM outbox ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,))
