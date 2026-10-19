"""Taxpayer profile facts (HC-01): the only personal data the health check keeps.

The keys are the cross-module contract in docs/MODULES.md, plus two extensions
this module needs to separate employment income from other income
(``has_employment_income``, ``has_business_income``). Every fact is optional.
A fact may also hold the explicit answer ``"unknown"``; the obligations engine
treats it like a missing fact, so it can never make a tax apply (HC-04).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from ...calculators.common import MAX_AMOUNT, money_str
from ...platform.errors import Invalid

UNKNOWN = "unknown"
ENTITY_TYPES = ("individual", "company", "sole_proprietor", "partnership", "nonprofit")
STATES = (
    "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue", "Borno", "Cross River", "Delta",
    "Ebonyi", "Edo", "Ekiti", "Enugu", "FCT", "Gombe", "Imo", "Jigawa", "Kaduna", "Kano", "Katsina", "Kebbi",
    "Kogi", "Kwara", "Lagos", "Nasarawa", "Niger", "Ogun", "Ondo", "Osun", "Oyo", "Plateau", "Rivers", "Sokoto",
    "Taraba", "Yobe", "Zamfara",
)  # fmt: skip
MAX_COUNT = 10_000_000  # input sanity bound, not a tax figure


@dataclass(frozen=True)
class FactSpec:
    kind: str  # "choice" | "bool" | "count" | "money" | "state"
    options: tuple[str, ...] = ()


FACTS: dict[str, FactSpec] = {
    "entity_type": FactSpec("choice", ENTITY_TYPES),
    "state": FactSpec("state", STATES),
    "has_employment_income": FactSpec("bool"),
    "has_business_income": FactSpec("bool"),
    "has_employees": FactSpec("bool"),
    "employee_count": FactSpec("count"),
    "annual_turnover": FactSpec("money"),
    "fixed_assets": FactSpec("money"),
    "sells_taxable_supplies": FactSpec("bool"),
    "makes_wht_payments": FactSpec("bool"),
    "has_rental_income": FactSpec("bool"),
    "has_foreign_income": FactSpec("bool"),
    "has_capital_gains": FactSpec("bool"),
    "is_professional_services": FactSpec("bool"),
    "non_resident": FactSpec("bool"),
}


def normalise(key: str, value: Any) -> Any:
    """Validate one fact. Returns the stored form, or ``None`` to clear the fact."""
    spec = FACTS.get(key)
    if spec is None:
        raise Invalid(f"{key}: not a profile fact")
    if value is None or value == "":
        return None
    if value == UNKNOWN:
        return UNKNOWN
    if spec.kind == "bool":
        if isinstance(value, bool):
            return value
        raise Invalid(f"{key}: must be true, false or unknown")
    if spec.kind in ("choice", "state"):
        if value in spec.options:
            return value
        raise Invalid(f"{key}: must be one of {', '.join(spec.options)}")
    if spec.kind == "count":
        if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).isdigit():
            raise Invalid(f"{key}: must be a whole number of zero or more")
        number = int(value)
        if number > MAX_COUNT:
            raise Invalid(f"{key}: is too large")
        return number
    # money
    try:
        amount = Decimal(re.sub(r"[,\s₦]", "", str(value)))
    except InvalidOperation:
        raise Invalid(f"{key}: must be an amount in naira") from None
    if not amount.is_finite() or amount < 0 or amount > MAX_AMOUNT:
        raise Invalid(f"{key}: must be an amount of zero or more")
    return money_str(amount)


def merge(current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Apply validated updates; ``None`` removes a fact (data minimisation)."""
    if not isinstance(updates, dict):
        raise Invalid("facts: must be an object")
    merged = dict(current)
    for key, raw in updates.items():
        value = normalise(key, raw)
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def known(facts: dict[str, Any], key: str) -> Any:
    """The fact's value, or ``None`` when missing or answered "unknown"."""
    value = facts.get(key)
    return None if value is None or value == UNKNOWN else value
