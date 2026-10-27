"""Outbound notifications (email, SMS, WhatsApp) through a provider adapter.

Every message is written to the ``outbox`` table first. The sandbox provider
stops there; a production provider also sends it. In demo mode the outbox can
be read at ``GET /api/dev/outbox`` so OTP codes are visible without email.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from ..db import Database
from .adapters import Adapter, ProviderUnavailable
from .util import iso, new_id


class SandboxMessaging(Adapter):
    kind = "messaging"
    name = "sandbox-messaging"
    mode = "sandbox"
    description = "Stores messages in the outbox only. Nothing is sent."

    def deliver(self, channel: str, recipient: str, subject: str, body: str) -> None:
        return None


log = logging.getLogger("taxng.notify")

RESEND_ENDPOINT = "https://api.resend.com/emails"


class ProductionMessaging(Adapter):
    """Sends email through Resend's HTTPS API (stdlib only, no SDK).

    Configure with ``TAXNG_RESEND_API_KEY`` and ``TAXNG_MAIL_FROM`` (a sender on a
    domain verified in Resend, e.g. ``tax.ng <no-reply@tax.ng>``). SMS and
    WhatsApp stay unconfigured until a gateway and WhatsApp BSP are contracted.
    """

    kind = "messaging"
    name = "production-messaging"
    mode = "production"
    description = "Email via Resend. SMS gateway and WhatsApp Business API not yet contracted."

    def __init__(self) -> None:
        self.api_key = os.environ.get("TAXNG_RESEND_API_KEY", "").strip()
        self.sender = os.environ.get("TAXNG_MAIL_FROM", "").strip()

    def is_configured(self) -> bool:
        return bool(self.api_key and self.sender)

    def deliver(self, channel: str, recipient: str, subject: str, body: str) -> None:
        if channel != "email":
            self.not_configured(f"a {channel} provider (only email is wired)")
        if not self.is_configured():
            self.not_configured("TAXNG_RESEND_API_KEY and TAXNG_MAIL_FROM")
        payload = json.dumps(
            {"from": self.sender, "to": [recipient], "subject": subject or "tax.ng", "text": body}
        ).encode("utf-8")
        req = urllib.request.Request(
            RESEND_ENDPOINT,
            data=payload,
            method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status >= 300:
                    raise ProviderUnavailable(f"email provider returned HTTP {resp.status}")
        except urllib.error.HTTPError as exc:
            # Never log the message body: it can carry a sign-in code.
            log.error("Email delivery failed: HTTP %s", exc.code)
            raise ProviderUnavailable(f"email provider returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            log.error("Email delivery failed: %s", exc.reason)
            raise ProviderUnavailable("email provider unreachable") from exc


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
