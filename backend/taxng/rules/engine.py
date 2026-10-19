"""Effective-dated parameter engine.

The parameter files under ``rules/parameters`` use the OpenFisca YAML layout
(``values`` keyed by start date, ``brackets`` for marginal scales, nested nodes
in one file). This module is a deliberately small reader for that layout so the
demo runs without ``openfisca-core``. Migrating means moving the same YAML into
an OpenFisca country package; see docs/DECISIONS.md (D1).

Conventions:
  * A value applies from its start date until the next start date.
  * ``value: null`` ends a parameter (the rule is repealed from that date).
  * Numbers are returned as ``Decimal`` so money arithmetic is exact.
  * Metadata (``review_status``, ``provision``, ``reference``) is inherited from
    parent nodes and may be overridden by children.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

ENGINE_VERSION = "0.1.0"

# Weakest first. A calculation is only as reviewed as its weakest input.
REVIEW_LEVELS = ("unverified", "secondary_source", "legal_approved")

_RESERVED_KEYS = {"description", "metadata", "documentation"}


class ParameterError(LookupError):
    """A parameter is unknown, malformed or not in force on the requested date."""


@dataclass(frozen=True)
class Bracket:
    threshold: Decimal
    rate: Decimal


@dataclass(frozen=True)
class ParameterInfo:
    name: str
    description: str
    review_status: str
    provision: str | None
    reference: str | None
    unit: str | None


def _to_date(key: Any) -> dt.date:
    if isinstance(key, dt.datetime):
        return key.date()
    if isinstance(key, dt.date):
        return key
    return dt.date.fromisoformat(str(key))


def _coerce(value: Any) -> Any:
    """Numbers become Decimal; everything else is returned unchanged."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    return value


def _value_on(series: dict, on: dt.date, name: str) -> Any:
    """Return the entry whose start date is the latest on or before ``on``."""
    current: Any = None
    found = False
    for start, entry in sorted(series.items(), key=lambda item: _to_date(item[0])):
        if _to_date(start) > on:
            break
        current = entry.get("value") if isinstance(entry, dict) else entry
        found = True
    if not found or current is None:
        raise ParameterError(f"{name} is not in force on {on.isoformat()}")
    return current


class ParameterTree:
    """Flat index of leaf parameters, keyed by dotted name (e.g. ``vat.standard_rate``)."""

    def __init__(self, nodes: dict[str, dict], version: str) -> None:
        self._nodes = nodes
        self.version = version

    # ------------------------------------------------------------------ loading
    @classmethod
    def from_directory(cls, root: Path) -> "ParameterTree":
        nodes: dict[str, dict] = {}
        digest = hashlib.sha256()
        files = sorted(root.rglob("*.yaml"))
        if not files:
            raise ParameterError(f"No parameter files found under {root}")
        for path in files:
            rel = path.relative_to(root).with_suffix("")
            raw = path.read_bytes()
            digest.update(rel.as_posix().encode())
            digest.update(raw)
            data = yaml.safe_load(raw) or {}
            cls._collect(".".join(rel.parts), data, nodes, {})
        # The version is a content hash, so any change to any rule file changes
        # it. Calculations store it for reproducibility (NFR-06).
        return cls(nodes, "rules-" + digest.hexdigest()[:12])

    @staticmethod
    def _collect(name: str, data: dict, out: dict[str, dict], inherited: dict) -> None:
        if not isinstance(data, dict):
            raise ParameterError(f"{name}: expected a mapping")
        meta = {**inherited, **(data.get("metadata") or {})}
        if "description" in data:
            # Lets a leaf such as wht.rates.rent.corporate show its group's label.
            meta["label"] = data["description"]
        if "values" in data or "brackets" in data:
            out[name] = {**data, "metadata": meta}
            return
        for key, child in data.items():
            if key in _RESERVED_KEYS:
                continue
            ParameterTree._collect(f"{name}.{key}", child, out, meta)

    # ------------------------------------------------------------------ lookup
    def _leaf(self, name: str) -> dict:
        try:
            return self._nodes[name]
        except KeyError:
            raise ParameterError(f"Unknown parameter {name}") from None

    def has(self, name: str) -> bool:
        return name in self._nodes

    def names(self, prefix: str = "") -> list[str]:
        return sorted(n for n in self._nodes if n.startswith(prefix))

    def value(self, name: str, on: dt.date) -> Any:
        node = self._leaf(name)
        if "values" not in node:
            raise ParameterError(f"{name} is a scale; use scale()")
        return _coerce(_value_on(node["values"], on, name))

    def scale(self, name: str, on: dt.date) -> list[Bracket]:
        node = self._leaf(name)
        if "brackets" not in node:
            raise ParameterError(f"{name} is not a scale")
        brackets = [
            Bracket(
                threshold=_coerce(_value_on(b["threshold"], on, name)),
                rate=_coerce(_value_on(b["rate"], on, name)),
            )
            for b in node["brackets"]
        ]
        return sorted(brackets, key=lambda b: b.threshold)

    def info(self, name: str) -> ParameterInfo:
        node = self._leaf(name)
        meta = node.get("metadata", {})
        return ParameterInfo(
            name=name,
            description=node.get("description") or meta.get("label") or name,
            review_status=meta.get("review_status", "unverified"),
            provision=meta.get("provision"),
            reference=meta.get("reference"),
            unit=meta.get("unit") or meta.get("threshold_unit"),
        )

    def is_scale(self, name: str) -> bool:
        return "brackets" in self._leaf(name)


def weakest(statuses: Iterable[str]) -> str:
    levels = [REVIEW_LEVELS.index(s) if s in REVIEW_LEVELS else 0 for s in statuses]
    return REVIEW_LEVELS[min(levels)] if levels else REVIEW_LEVELS[0]


class ParameterView:
    """Parameters as at one date, recording every lookup.

    Calculators read rules only through a view. The recorded lookups become the
    result's audit trail: which parameters, which values, which provisions, and
    the weakest review status among them.
    """

    def __init__(self, tree: ParameterTree, on: dt.date) -> None:
        self.tree = tree
        self.on = on
        self.used: dict[str, Any] = {}

    def value(self, name: str) -> Any:
        result = self.tree.value(name, self.on)
        self.used[name] = result
        return result

    def scale(self, name: str) -> list[Bracket]:
        result = self.tree.scale(name, self.on)
        self.used[name] = [{"threshold": b.threshold, "rate": b.rate} for b in result]
        return result

    def review_status(self) -> str:
        return weakest(self.tree.info(n).review_status for n in self.used)

    def provisions(self) -> list[str]:
        found = {self.tree.info(n).provision for n in self.used}
        return sorted(p for p in found if p)


@dataclass(frozen=True)
class Band:
    lower: Decimal
    upper: Decimal | None
    rate: Decimal
    taxable: Decimal
    tax: Decimal


def apply_scale(amount: Decimal, brackets: list[Bracket]) -> tuple[Decimal, list[Band]]:
    """Marginal tax on ``amount``. Returns total tax and a per-band breakdown."""
    total = Decimal(0)
    bands: list[Band] = []
    for i, bracket in enumerate(brackets):
        upper = brackets[i + 1].threshold if i + 1 < len(brackets) else None
        if amount <= bracket.threshold:
            taxable = Decimal(0)
        else:
            top = amount if upper is None else min(amount, upper)
            taxable = top - bracket.threshold
        tax = taxable * bracket.rate
        total += tax
        bands.append(Band(bracket.threshold, upper, bracket.rate, taxable, tax))
    return total, bands
