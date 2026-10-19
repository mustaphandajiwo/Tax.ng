"""NRS e-invoicing adapters (kind ``einvoicing``).

The sandbox stands in for the NRS e-invoicing (Merchant Buyer Solution) API.
It is deterministic: the same submission always gets the same sandbox
reference, IRN-style number and signed QR payload. Status arrives later, as a
signed callback that the service verifies before it changes an invoice. In the
sandbox the callback is produced on demand by the status sync job.

Sandbox rule: an invoice whose buyer TIN ends in ``0000`` is rejected.
"""

from __future__ import annotations

import base64
import re
from typing import Any

from ...platform.adapters import Adapter
from ...platform.util import canonical_json, sha256, sign

PRODUCTION_NEEDS = (
    "NRS accreditation as a system integrator or access point provider, NRS API credentials "
    "and signing certificates (confirm the accreditation window with NRS)"
)


class SandboxNrsEInvoicing(Adapter):
    kind = "einvoicing"
    name = "sandbox-nrs-einvoicing"
    mode = "sandbox"
    description = (
        "Simulates NRS e-invoicing: sandbox IRN-style references, signed QR payloads and asynchronous "
        "status callbacks. Nothing is sent to NRS."
    )
    QR_KEY = "taxng-sandbox-nrs-qr"  # sandbox only; production QR codes are signed with NRS-issued keys

    def submit(self, doc: dict[str, Any]) -> dict[str, Any]:
        digest = sha256(canonical_json(doc)).upper()
        irn = f"{doc['invoice_number']}-SBX{digest[16:24]}-{str(doc['issue_date']).replace('-', '')}"
        qr_body = base64.urlsafe_b64encode(
            canonical_json(
                {
                    "irn": irn,
                    "supplier_tin": doc["supplier_tin"],
                    "buyer_tin": doc["buyer_tin"],
                    "issue_date": doc["issue_date"],
                    "vat": doc["totals"].get("vat"),
                    "gross": doc["totals"].get("gross"),
                    "mode": self.mode,
                }
            ).encode()
        ).decode().rstrip("=")
        return {
            "submission_ref": f"SBXSUB-{digest[:16]}",
            "irn": irn,
            "qr_payload": f"{qr_body}.{sign(self.QR_KEY, qr_body)[:32]}",
            "status": "received",
            "mode": self.mode,
        }

    def status_callback(self, submission: dict[str, Any], key: str) -> tuple[dict[str, Any], str]:
        """Builds the signed status callback NRS would POST to us later."""
        rejected = re.sub(r"\D", "", submission["buyer_tin"]).endswith("0000")
        status = "rejected" if rejected else "accepted"
        payload = {
            "event_id": "sbxcb_" + sha256(submission["submission_ref"] + status)[:16],
            "submission_ref": submission["submission_ref"],
            "irn": submission["irn"],
            "status": status,
            "reason": (
                "Buyer TIN not found on the taxpayer register (sandbox rule: buyer TINs ending 0000 are rejected)"
                if rejected
                else None
            ),
            "mode": self.mode,
        }
        return payload, sign(key, canonical_json(payload))


class ProductionNrsEInvoicing(Adapter):
    kind = "einvoicing"
    name = "nrs-einvoicing"
    mode = "production"
    description = "NRS e-invoicing API. Requires accreditation, credentials and certificates."

    def submit(self, doc: dict[str, Any]) -> dict[str, Any]:
        self.not_configured(PRODUCTION_NEEDS)

    def status_callback(self, submission: dict[str, Any], key: str) -> tuple[dict[str, Any], str]:
        self.not_configured(PRODUCTION_NEEDS)
