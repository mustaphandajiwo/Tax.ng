"""Professional register checks (ADV-01): the "register" adapter kind.

The sandbox is deterministic: a membership number ending in ``0000`` is
``not_found`` and any other well-formed number is ``verified``. A sandbox
result is never shown as a real verification; callers carry ``mode`` through
to every response. The production adapter needs register access from the
Chartered Institute of Taxation of Nigeria (CITN) and the Institute of
Chartered Accountants of Nigeria (ICAN).
"""

from __future__ import annotations

from ...platform.adapters import Adapter

REGISTERS = {"citn": "CITN", "ican": "ICAN"}


class SandboxRegister(Adapter):
    kind = "register"
    name = "sandbox-professional-register"
    mode = "sandbox"
    description = "Deterministic CITN and ICAN membership checks. Numbers ending 0000 are not found."

    def check(self, register: str, number: str) -> str:
        return "not_found" if number.endswith("0000") else "verified"


class ProductionRegister(Adapter):
    kind = "register"
    name = "citn-ican-registers"
    mode = "production"
    description = "Membership look-ups against the CITN and ICAN member registers."

    def check(self, register: str, number: str) -> str:
        self.not_configured("data-access agreements and API (or bulk register) access from CITN and ICAN")
