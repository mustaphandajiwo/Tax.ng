"""Filing adapters (Phase 4, PRD section 5 "Direct submission", Annex A9).

``SandboxNrsFiling`` is deterministic: the acknowledgement reference is derived
from the document hash and signed with HMAC so the workspace can verify it.
It rejects a return whose organisation TIN ends with ``0000``. A sandbox
acknowledgement is never a real filing; the workspace records it as
``filed_sandbox``.

``ProductionNrsFiling`` raises ``NotConfigured`` until tax.ng holds NRS
accreditation, API credentials, client certificates and the taxpayer's written
authorisation. Until then "File & Pay" stays out of public navigation
(``features.py``).
"""

from __future__ import annotations

from typing import Any

from ...platform.adapters import Adapter
from ...platform.util import canonical_json, sha256, sign, verify_signature

PRODUCTION_NEEDS = (
    "NRS accreditation as an approved filing channel, API credentials, client certificates "
    "and the taxpayer's written authorisation to file on their behalf"
)


def ack_message(mode: str, reference: str, document_hash: str) -> str:
    return f"taxng-filing-ack:{mode}:{reference}:{document_hash}"


def document_hash(document: dict[str, Any]) -> str:
    return sha256(canonical_json(document))


def verify_ack(secret: str, ack: dict[str, Any], expected_hash: str) -> bool:
    """True only if the acknowledgement was signed for this exact document and mode."""
    reference = str(ack.get("reference") or "")
    mode = str(ack.get("mode") or "")
    if not reference or mode not in ("sandbox", "production") or ack.get("document_hash") != expected_hash:
        return False
    return verify_signature(secret, ack_message(mode, reference, expected_hash), str(ack.get("signature") or ""))


class SandboxNrsFiling(Adapter):
    kind = "filing"
    name = "sandbox-nrs-filing"
    mode = "sandbox"
    description = "Deterministic sandbox filing. Returns a signed sandbox acknowledgement. Nothing reaches NRS. TINs ending 0000 are rejected."

    def submit(self, document: dict[str, Any], *, secret: str) -> dict[str, Any]:
        digest = document_hash(document)
        tin = str((document.get("taxpayer") or {}).get("tin") or "")
        if tin.endswith("0000"):
            return {"outcome": "rejected", "mode": self.mode, "document_hash": digest, "message": "Sandbox rejection: TIN not recognised."}
        reference = "SBX-" + digest[:16].upper()
        return {
            "outcome": "acknowledged",
            "mode": self.mode,
            "reference": reference,
            "document_hash": digest,
            "signature": sign(secret, ack_message(self.mode, reference, digest)),
            "message": "Sandbox acknowledgement. This return has not been filed with NRS.",
        }


class ProductionNrsFiling(Adapter):
    kind = "filing"
    name = "nrs-filing"
    mode = "production"
    description = "Direct submission to the Nigeria Revenue Service. Requires accreditation, credentials, certificates and written authorisation."

    def submit(self, document: dict[str, Any], *, secret: str) -> dict[str, Any]:
        self.not_configured(PRODUCTION_NEEDS)
