"""Obligations engine (HC-01, HC-02): which taxes apply, as effective-dated data.

Obligation rules live in ``rules/obligations/*.yaml`` (format in
``rules/obligations/_format.yaml``). This module only interprets them:

* **Conditions** are evaluated with three-valued logic. A fact that is missing
  or answered "unknown" makes a comparison *unknown*, and unknown never becomes
  "applies". Such obligations are reported as *undetermined* so the health check
  can say "insufficient evidence" instead of guessing (HC-04). No tax applies
  merely because of the taxpayer's category: categories only narrow the
  activity tests written in the data.
* **Thresholds** in conditions reference rule parameters by name
  (``{param: cit.small_company.turnover_ceiling}``) and are read from the
  parameter tree as at the start of each period, so a rule change applies only
  to the periods it covers.
* **Versions**: several entries may share an id with non-overlapping
  ``valid_from``/``valid_to``. Each period uses the version in force on the
  period's first day, so changing an effective date alters only the affected
  periods.
* **Due dates** are computed from the version's due-date rule and carry their
  own review status, kept separate from the applicability rule's status.
"""

from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from ...rules import ParameterError, ParameterTree
from ...rules.engine import REVIEW_LEVELS, weakest
from .facts import FACTS, known

COMPARISONS = ("eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte")
FREQUENCIES = ("monthly", "annual")
DUE_RULES = ("day_of_following_month", "months_after_period_end")


class ObligationError(ValueError):
    """An obligation rule file is malformed."""


# ------------------------------------------------------------------ conditions
@dataclass
class Outcome:
    """Result of a condition: ``value`` is True, False or None (unknown)."""

    value: bool | None
    reasons: list[str] = field(default_factory=list)
    unknown: set[str] = field(default_factory=set)


class Conditions:
    """Evaluates and validates the condition language shared by obligations and questions."""

    def __init__(self, tree: ParameterTree) -> None:
        self.tree = tree

    # -------------------------------------------------------------- validation
    def validate(self, cond: Any, where: str) -> set[str]:
        """Raise ``ObligationError`` on a malformed condition; return the parameters it references."""
        if not isinstance(cond, dict):
            raise ObligationError(f"{where}: condition must be a mapping")
        params: set[str] = set()
        keys = set(cond) - {"label"}
        if keys in ({"all"}, {"any"}):
            children = cond["all" if "all" in keys else "any"]
            if not isinstance(children, list) or not children:
                raise ObligationError(f"{where}: all/any needs a non-empty list")
            for i, child in enumerate(children):
                params |= self.validate(child, f"{where}[{i}]")
            return params
        if keys == {"not"}:
            return self.validate(cond["not"], f"{where}.not")
        fact = cond.get("fact")
        ops = keys - {"fact"}
        if fact not in FACTS:
            raise ObligationError(f"{where}: unknown fact {fact!r}")
        if len(ops) != 1 or next(iter(ops)) not in COMPARISONS:
            raise ObligationError(f"{where}: needs exactly one of {', '.join(COMPARISONS)}")
        op = next(iter(ops))
        target = cond[op]
        if isinstance(target, dict):
            name = target.get("param")
            if set(target) != {"param"} or not self.tree.has(str(name)):
                raise ObligationError(f"{where}: unknown parameter reference {target!r}")
            params.add(str(name))
        if op in ("in", "not_in") and not isinstance(target, list):
            raise ObligationError(f"{where}: {op} needs a list")
        return params

    # -------------------------------------------------------------- evaluation
    def evaluate(self, cond: dict[str, Any], facts: dict[str, Any], on: dt.date) -> Outcome:
        label = cond.get("label")
        if "all" in cond or "any" in cond:
            parts = [self.evaluate(c, facts, on) for c in cond.get("all") or cond.get("any")]
            values = [p.value for p in parts]
            unknown = set().union(*(p.unknown for p in parts if p.value is None))
            if "all" in cond:
                if False in values:
                    return Outcome(False)
                if None in values:
                    return Outcome(None, unknown=unknown)
                reasons = [r for p in parts for r in p.reasons]
            else:
                if True in values:
                    reasons = [r for p in parts if p.value for r in p.reasons]
                elif None in values:
                    return Outcome(None, unknown=unknown)
                else:
                    return Outcome(False)
            return Outcome(True, [label] if label else reasons)
        if "not" in cond:
            inner = self.evaluate(cond["not"], facts, on)
            if inner.value is None:
                return Outcome(None, unknown=inner.unknown)
            return Outcome(not inner.value, [label] if label and not inner.value else [])
        value = known(facts, cond["fact"])
        if value is None:
            return Outcome(None, unknown={cond["fact"]})
        op = next(k for k in cond if k in COMPARISONS)
        result = self._compare(value, op, self._target(cond[op], on))
        return Outcome(result, [label] if result and label else [])

    def _target(self, target: Any, on: dt.date) -> Any:
        if isinstance(target, dict):
            return self.tree.value(target["param"], on)
        return target

    @staticmethod
    def _compare(value: Any, op: str, target: Any) -> bool:
        if op == "eq":
            return bool(value == target)
        if op == "ne":
            return bool(value != target)
        if op == "in":
            return value in target
        if op == "not_in":
            return value not in target
        try:
            left, right = Decimal(str(value)), Decimal(str(target))
        except InvalidOperation:
            return False
        return {"gt": left > right, "gte": left >= right, "lt": left < right, "lte": left <= right}[op]

    def param_statuses(self, params: set[str]) -> list[str]:
        return [self.tree.info(p).review_status for p in params]


# ------------------------------------------------------------------ obligations
@dataclass(frozen=True)
class Obligation:
    id: str
    tax: str
    title: str
    frequency: str
    valid_from: dt.date
    valid_to: dt.date | None
    review_status: str
    applies_if: dict[str, Any]
    due: dict[str, Any]
    provision: str
    evidence: tuple[str, ...]
    params: frozenset[str]
    note: str | None = None
    guide: str | None = None
    calculator: str | None = None
    specialism: str | None = None
    source: str = ""

    def in_force(self, on: dt.date) -> bool:
        return self.valid_from <= on and (self.valid_to is None or on < self.valid_to)


def _date(value: Any) -> dt.date:
    return value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value))


def periods(frequency: str, year: int) -> list[tuple[str, dt.date, dt.date]]:
    """Calendar periods of ``year``: twelve months, or the whole year."""
    if frequency == "annual":
        return [(str(year), dt.date(year, 1, 1), dt.date(year, 12, 31))]
    out = []
    for month in range(1, 13):
        last = calendar.monthrange(year, month)[1]
        out.append((f"{year}-{month:02d}", dt.date(year, month, 1), dt.date(year, month, last)))
    return out


def _add_months(year: int, month: int, months: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + months
    return index // 12, index % 12 + 1


def due_date(rule: dict[str, Any], period_end: dt.date) -> dt.date:
    """Apply a due-date rule to a period end (weekends and holidays not adjusted)."""
    if rule["rule"] == "day_of_following_month":
        year, month = _add_months(period_end.year, period_end.month, 1)
        return dt.date(year, month, min(int(rule["day"]), calendar.monthrange(year, month)[1]))
    year, month = _add_months(period_end.year, period_end.month, int(rule["months"]))
    return dt.date(year, month, calendar.monthrange(year, month)[1])


def describe_due(rule: dict[str, Any]) -> str:
    if rule["rule"] == "day_of_following_month":
        return f"Day {rule['day']} of the following month"
    return f"End of the month falling {rule['months']} months after the period ends"


class ObligationRules:
    """All obligation versions, loaded and validated once at startup."""

    def __init__(self, obligations: list[Obligation], conditions: Conditions) -> None:
        self.obligations = obligations
        self.conditions = conditions

    @classmethod
    def from_directory(cls, root: Path, tree: ParameterTree) -> ObligationRules:
        conditions = Conditions(tree)
        items: list[Obligation] = []
        for path in sorted(root.glob("*.yaml")):
            for i, raw in enumerate(yaml.safe_load(path.read_text()) or []):
                items.append(cls._parse(raw, f"{path.name}[{i}]", conditions))
        by_id: dict[str, list[Obligation]] = {}
        for ob in items:
            by_id.setdefault(ob.id, []).append(ob)
        for oid, versions in by_id.items():
            versions.sort(key=lambda o: o.valid_from)
            for a, b in zip(versions, versions[1:]):
                if a.valid_to is None or a.valid_to > b.valid_from:
                    raise ObligationError(f"{oid}: versions {a.source} and {b.source} overlap")
        return cls(items, conditions)

    @staticmethod
    def _parse(raw: dict[str, Any], where: str, conditions: Conditions) -> Obligation:
        required = ("id", "tax", "title", "frequency", "valid_from", "review_status", "applies_if", "due", "provision", "evidence")
        missing = [k for k in required if k not in raw]
        if missing:
            raise ObligationError(f"{where}: missing {', '.join(missing)}")
        if raw["frequency"] not in FREQUENCIES:
            raise ObligationError(f"{where}: frequency must be one of {', '.join(FREQUENCIES)}")
        for status in (raw["review_status"], raw["due"].get("review_status")):
            if status not in REVIEW_LEVELS:
                raise ObligationError(f"{where}: review_status must be one of {', '.join(REVIEW_LEVELS)}")
        due = raw["due"]
        if due.get("rule") not in DUE_RULES:
            raise ObligationError(f"{where}: due.rule must be one of {', '.join(DUE_RULES)}")
        if due["rule"] == "day_of_following_month" and not 1 <= int(due.get("day", 0)) <= 31:
            raise ObligationError(f"{where}: due.day must be 1 to 31")
        if due["rule"] == "months_after_period_end" and not 0 < int(due.get("months", 0)) <= 24:
            raise ObligationError(f"{where}: due.months must be 1 to 24")
        params = conditions.validate(raw["applies_if"], f"{where}.applies_if")
        valid_to = raw.get("valid_to")
        return Obligation(
            id=str(raw["id"]),
            tax=str(raw["tax"]),
            title=str(raw["title"]),
            frequency=raw["frequency"],
            valid_from=_date(raw["valid_from"]),
            valid_to=_date(valid_to) if valid_to else None,
            review_status=raw["review_status"],
            applies_if=raw["applies_if"],
            due=dict(due),
            provision=str(raw["provision"]),
            evidence=tuple(str(e) for e in raw["evidence"]),
            params=frozenset(params),
            note=raw.get("note"),
            guide=raw.get("guide"),
            calculator=raw.get("calculator"),
            specialism=raw.get("specialism"),
            source=where,
        )

    # -------------------------------------------------------------- queries
    def first_year(self) -> int:
        return min(o.valid_from.year for o in self.obligations)

    def ids(self) -> list[str]:
        return sorted({o.id for o in self.obligations})

    def latest(self, oid: str) -> Obligation | None:
        versions = [o for o in self.obligations if o.id == oid]
        return max(versions, key=lambda o: o.valid_from) if versions else None

    def evaluate(self, facts: dict[str, Any], year: int) -> dict[str, Any]:
        """Applicable period items, plus obligations that cannot be decided yet.

        Returns ``{"applicable": [item, ...], "undetermined": [...], "not_applicable": [ids]}``.
        """
        applicable: list[dict[str, Any]] = []
        undetermined: dict[str, dict[str, Any]] = {}
        seen_true: set[str] = set()
        considered: set[str] = set()
        for ob in self.obligations:
            for period, start, end in periods(ob.frequency, year):
                if not ob.in_force(start):
                    continue
                considered.add(ob.id)
                try:
                    outcome = self.conditions.evaluate(ob.applies_if, facts, start)
                except ParameterError:
                    # A referenced threshold is not in force for this period.
                    outcome = Outcome(None, unknown=set())
                if outcome.value is True:
                    seen_true.add(ob.id)
                    applicable.append(self._item(ob, period, start, end, outcome))
                elif outcome.value is None:
                    entry = undetermined.setdefault(ob.id, self._summary(ob))
                    entry["unknown_facts"] = sorted(set(entry["unknown_facts"]) | outcome.unknown)
                    entry["periods"].append(period)
        # An obligation can apply in some periods and be undetermined in others
        # (for example when a threshold is not in force); both are reported.
        applicable.sort(key=lambda i: (i["due_date"], i["id"]))
        return {
            "applicable": applicable,
            "undetermined": sorted(undetermined.values(), key=lambda u: u["id"]),
            "not_applicable": sorted(considered - seen_true - set(undetermined)),
        }

    def obligations_for(self, facts: dict[str, Any], year: int) -> list[dict[str, Any]]:
        return self.evaluate(facts, year)["applicable"]

    def _summary(self, ob: Obligation) -> dict[str, Any]:
        return {
            "id": ob.id,
            "tax": ob.tax,
            "title": ob.title,
            "frequency": ob.frequency,
            "provision": ob.provision,
            "review_status": ob.review_status,
            "unknown_facts": [],
            "periods": [],
            "guide": ob.guide,
            "calculator": ob.calculator,
            "specialism": ob.specialism,
        }

    def _item(self, ob: Obligation, period: str, start: dt.date, end: dt.date, outcome: Outcome) -> dict[str, Any]:
        reasons = [r for r in outcome.reasons if r]
        because = "; ".join(reasons) if reasons else "Your answers meet the conditions for this obligation"
        due_status = ob.due["review_status"]
        return {
            "id": ob.id,
            "tax": ob.tax,
            "title": ob.title,
            "frequency": ob.frequency,
            "period": period,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "due_date": due_date(ob.due, end).isoformat(),
            "due_rule": describe_due(ob.due),
            "due_date_review_status": due_status,
            "provision": ob.provision,
            "evidence": list(ob.evidence),
            "applies_because": because[0].upper() + because[1:] + ".",
            "review_status": weakest([ob.review_status, due_status, *self.conditions.param_statuses(set(ob.params))]),
            "version": ob.valid_from.isoformat(),
            "note": ob.note,
            "guide": ob.guide,
            "calculator": ob.calculator,
            "specialism": ob.specialism,
        }
