"""Outbound webhook delivery adapters (kind ``webhook_delivery``).

The sandbox makes no network calls: it records each delivery as
``would_deliver`` so the demo can show and replay it.
"""

from __future__ import annotations

from typing import Any

from ...platform.adapters import Adapter


class SandboxWebhookDelivery(Adapter):
    kind = "webhook_delivery"
    name = "sandbox-webhooks"
    mode = "sandbox"
    description = "Records signed webhook deliveries without sending them."

    def deliver(self, url: str, headers: dict[str, str], body: str) -> dict[str, Any]:
        return {"status": "would_deliver", "mode": self.mode}


class ProductionWebhookDelivery(Adapter):
    kind = "webhook_delivery"
    name = "https-webhooks"
    mode = "production"
    description = "HTTPS delivery worker with retries. Requires egress configuration."

    def deliver(self, url: str, headers: dict[str, str], body: str) -> dict[str, Any]:
        self.not_configured("an egress-restricted delivery worker (allow-listed outbound HTTPS, SSRF protection and a retry queue)")
