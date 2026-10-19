"""Shared types for calculators: input parsing, money rounding and results.

Rounding policy (CALC-08): calculations run on exact decimals; reported amounts
are rounded to the kobo (2 dp) with ROUND_HALF_UP at the point of output only.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from ..rules import ENGINE_VERSION, Band, ParameterView

MAX_AMOUNT = Decimal("1e13")  # ₦10 trillion; guards against absurd inputs
KOBO = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(KOBO, rounding=ROUND_HALF_UP)


def money_str(value: Decimal) -> str:
    return str(money(value))


def rate_str(value: Decimal) -> str:
    """Plain decimal text without exponent notation: 0.20 -> '0.2', 20.00 -> '20'."""
    return format(value.normalize(), "f") if value != 0 else "0"


class InputError(ValueError):
    """Invalid calculator input. ``errors`` maps field name to a message."""

    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


class Fields:
    """Reads and validates a JSON payload, collecting every error before raising."""

    def __init__(self, payload: dict[str, Any] | None) -> None:
        self.payload = payload or {}
        self.errors: dict[str, str] = {}

    def money(self, key: str, *, required: bool = False) -> Decimal:
        raw = self.payload.get(key)
        if raw in (None, ""):
            if required:
                self.errors[key] = "is required"
            return Decimal(0)
        try:
            text = re.sub(r"[,\s₦]", "", str(raw))
            value = Decimal(text)
        except InvalidOperation:
            self.errors[key] = "must be a number"
            return Decimal(0)
        if not value.is_finite() or value < 0:
            self.errors[key] = "must be zero or more"
            return Decimal(0)
        if value > MAX_AMOUNT:
            self.errors[key] = "is too large"
            return Decimal(0)
        return value

    def year(self, key: str, *, default: int) -> int:
        raw = self.payload.get(key, default)
        try:
            year = int(raw)
        except (TypeError, ValueError):
            self.errors[key] = "must be a year"
            return default
        if not 2011 <= year <= 2035:
            self.errors[key] = "must be between 2011 and 2035"
            return default
        return year

    def date(self, key: str, *, default: dt.date) -> dt.date:
        raw = self.payload.get(key)
        if raw in (None, ""):
            return default
        try:
            return dt.date.fromisoformat(str(raw))
        except ValueError:
            self.errors[key] = "must be a date (YYYY-MM-DD)"
            return default

    def choice(self, key: str, options: list[str], *, default: str | None = None) -> str:
        raw = self.payload.get(key, default)
        if raw not in options:
            self.errors[key] = f"must be one of: {', '.join(options)}"
            return options[0]
        return str(raw)

    def flag(self, key: str, *, default: bool = False) -> bool:
        raw = self.payload.get(key, default)
        if isinstance(raw, bool):
            return raw
        if raw in ("true", "1", 1):
            return True
        if raw in ("false", "0", 0, None, ""):
            return False
        self.errors[key] = "must be true or false"
        return default

    def finish(self) -> None:
        if self.errors:
            raise InputError(self.errors)


@dataclass
class Step:
    label: str
    amount: Decimal | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "amount": None if self.amount is None else money_str(self.amount),
            "note": self.note,
        }


def bands_to_dict(bands: list[Band]) -> list[dict[str, Any]]:
    return [
        {
            "lower": money_str(b.lower),
            "upper": None if b.upper is None else money_str(b.upper),
            "rate": rate_str(b.rate),
            "taxable": money_str(b.taxable),
            "tax": money_str(b.tax),
        }
        for b in bands
    ]


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


@dataclass
class CalculationResult:
    """Everything needed to show, explain and later reproduce a calculation."""

    calculator: str
    regime: str
    period: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    steps: list[Step]
    view: ParameterView
    bands: list[Band] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "calculator": self.calculator,
            "regime": self.regime,
            "period": self.period,
            "inputs": _jsonable(self.inputs),
            "outputs": _jsonable(self.outputs),
            "steps": [s.to_dict() for s in self.steps],
            "bands": bands_to_dict(self.bands),
            "assumptions": self.assumptions,
            "warnings": self.warnings,
            "citations": self.view.provisions(),
            "parameters_used": _jsonable(self.view.used),
            "review_status": self.view.review_status(),
            "rules_version": self.view.tree.version,
            "engine_version": ENGINE_VERSION,
        }
