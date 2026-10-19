"""Identity verification (NIN, TIN, CAC) through a KYC adapter (Annex A9).

Only a masked form and a salted hash of the identifier are stored.
Sandbox rule (deterministic, for tests and demos): identifiers ending in
``0000`` are "not_found"; anything else of the right length is "verified".
"""

from __future__ import annotations

import re
from typing import Any

from ..db import Database
from .adapters import Adapter
from .errors import Invalid
from .util import iso, mask, new_id, sign

FORMATS = {
    "nin": re.compile(r"^\d{11}$"),
    "tin": re.compile(r"^\d{8,14}(-\d{4})?$"),
    "cac": re.compile(r"^(RC|BN|IT|LP)?\d{5,9}$", re.IGNORECASE),
}


class SandboxKyc(Adapter):
    kind = "kyc"
    name = "sandbox-kyc"
    mode = "sandbox"
    description = "Deterministic NIN, TIN and CAC checks. Identifiers ending 0000 are not found."

    def check(self, id_type: str, number: str) -> str:
        return "not_found" if number.endswith("0000") else "verified"


class ProductionKyc(Adapter):
    kind = "kyc"
    name = "licensed-kyc-provider"
    mode = "production"
    description = "Licensed verification provider for NIN (NIMC), TIN (JRB/NRS) and CAC records."

    def check(self, id_type: str, number: str) -> str:
        self.not_configured("a contract and API credentials with a licensed verification provider")


class IdentityService:
    def __init__(self, db: Database, provider: Adapter, secret: str) -> None:
        self.db = db
        self.provider = provider
        self.secret = secret

    def verify(self, subject_type: str, subject_id: str, id_type: str, number: str) -> dict[str, Any]:
        number = number.strip().replace(" ", "")
        if id_type not in FORMATS:
            raise Invalid("id_type: must be one of nin, tin, cac")
        if not FORMATS[id_type].match(number):
            raise Invalid(f"number: not a valid {id_type.upper()} format")
        result = self.provider.check(id_type, number)  # type: ignore[attr-defined]
        record = {
            "id": new_id("idv"),
            "subject_type": subject_type,
            "subject_id": subject_id,
            "id_type": id_type,
            "id_masked": mask(number),
            "id_hash": sign(self.secret, f"{id_type}:{number}"),
            "provider": self.provider.name,
            "mode": self.provider.mode,
            "result": result,
            "checked_at": iso(),
        }
        self.db.insert("identity_verifications", record)
        return {k: record[k] for k in ("id", "id_type", "id_masked", "provider", "mode", "result", "checked_at")}

    def latest(self, subject_type: str, subject_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT id, id_type, id_masked, provider, mode, result, checked_at FROM identity_verifications "
            "WHERE subject_type = ? AND subject_id = ? ORDER BY checked_at DESC",
            (subject_type, subject_id),
        )
