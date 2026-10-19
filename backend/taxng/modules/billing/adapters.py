"""Payment service provider adapters (kind ``payments``). Commercial payments only.

The sandbox creates a checkout session and, when the demo "complete payment"
page is used, produces the signed webhook a provider would send. Billing
verifies that signature before anything is marked paid. No money moves.
"""

from __future__ import annotations

from typing import Any

from ...platform.adapters import Adapter
from ...platform.util import canonical_json, iso, sha256, sign

PRODUCTION_NEEDS = "a contract with a licensed Nigerian payment service provider (CBN-licensed), live API keys and a webhook signing secret"


class SandboxPsp(Adapter):
    kind = "payments"
    name = "sandbox-psp"
    mode = "sandbox"
    description = "Simulated checkout and signed webhooks. No money moves."

    def create_session(self, checkout: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider_ref": "SBXPSP-" + sha256(checkout["checkout_id"])[:14].upper(),
            "url": f"/app/#/billing/checkout/{checkout['checkout_id']}",
            "mode": self.mode,
        }

    def simulate_webhook(self, payment: dict[str, Any], outcome: str, secret: str) -> tuple[dict[str, Any], str]:
        """What the provider would POST after its hosted page redirects back."""
        event = "charge.success" if outcome == "paid" else "charge.failed"
        payload = {
            "id": "sbxevt_" + sha256(payment["checkout_id"] + event)[:16],
            "event": event,
            "created_at": iso(),
            "data": {
                "reference": payment["checkout_id"],
                "provider_ref": payment["provider_ref"],
                "amount_kobo": payment["amount_kobo"],
                "currency": payment["currency"],
            },
            "mode": self.mode,
        }
        return payload, sign(secret, canonical_json(payload))


class ProductionPsp(Adapter):
    kind = "payments"
    name = "licensed-psp"
    mode = "production"
    description = "Licensed Nigerian payment service provider. Requires a contract and keys."

    def create_session(self, checkout: dict[str, Any]) -> dict[str, Any]:
        self.not_configured(PRODUCTION_NEEDS)

    def simulate_webhook(self, payment: dict[str, Any], outcome: str, secret: str) -> tuple[dict[str, Any], str]:
        self.not_configured("the sandbox provider: payment simulation is not available in production")
