"""Health-check question bank (HC-01, HC-02, HC-04), loaded from ``content/compliance/questions.yaml``.

Branching is data: a question is shown only when its ``ask_if`` condition is
true for the saved facts, and evidence questions are shown only for obligations
that apply. Every question therefore has one of four states, which the API keeps
distinct:

* ``answered``: a definite answer was saved;
* ``unknown``: the taxpayer said "Not sure" (reported as insufficient evidence);
* ``not_applicable``: hidden because its branch was not triggered, or answered
  "Does not apply" where that is allowed;
* ``unanswered``: shown but not yet answered.

Contradiction checks run over every saved fact, including facts whose
questions are now hidden, so a stale answer cannot slip through.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ...platform.errors import Invalid
from ...rules import ParameterError
from .facts import FACTS, UNKNOWN, normalise
from .rules import Conditions, ObligationError

DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("obligation_coverage", "Obligation coverage"),
    ("timeliness", "Timeliness"),
    ("documentation", "Documentation"),
    ("reporting_accuracy", "Reporting accuracy indicators"),
    ("exposure_materiality", "Exposure materiality"),
    ("evidence_confidence", "Evidence confidence"),
)
ASKED_DIMENSIONS = ("obligation_coverage", "timeliness", "documentation", "reporting_accuracy")
SEVERITIES = ("high", "medium", "low")
EVIDENCE_ANSWERS = ("yes", "no", UNKNOWN)
NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class FactQuestion:
    id: str
    fact: str
    text: str
    type: str
    options: tuple[tuple[str, str], ...]
    allow_unknown: bool
    ask_if: dict[str, Any] | None


@dataclass(frozen=True)
class EvidenceQuestion:
    id: str
    obligation: str
    dimension: str
    text: str
    severity: str
    allow_na: bool
    ask_if: dict[str, Any] | None
    evidence: tuple[str, ...]
    why: str
    next_step: str


@dataclass(frozen=True)
class Contradiction:
    id: str
    when: dict[str, Any]
    message: str
    questions: tuple[str, ...]


class QuestionBank:
    def __init__(
        self,
        facts: list[FactQuestion],
        evidence: list[EvidenceQuestion],
        contradictions: list[Contradiction],
        materiality: dict[str, Any],
        conditions: Conditions,
    ) -> None:
        self.facts = facts
        self.evidence = evidence
        self.contradictions = contradictions
        self.materiality = materiality
        self.conditions = conditions
        self.by_id: dict[str, FactQuestion | EvidenceQuestion] = {q.id: q for q in [*facts, *evidence]}
        self.by_fact = {q.fact: q for q in facts}

    # ------------------------------------------------------------------ loading
    @classmethod
    def from_file(cls, path: Path, conditions: Conditions, obligation_ids: set[str]) -> QuestionBank:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        seen: set[str] = set()

        def unique(qid: str) -> str:
            if qid in seen:
                raise ObligationError(f"questions: duplicate id {qid}")
            seen.add(qid)
            return qid

        facts = []
        for q in raw.get("facts", []):
            spec = FACTS.get(q.get("fact"))
            if spec is None:
                raise ObligationError(f"questions {q.get('id')}: unknown fact {q.get('fact')!r}")
            if q["type"] != spec.kind:
                raise ObligationError(f"questions {q['id']}: type {q['type']} does not match fact kind {spec.kind}")
            if q.get("ask_if"):
                conditions.validate(q["ask_if"], f"questions {q['id']}.ask_if")
            options = tuple((o["value"], o["label"]) for o in q.get("options", []))
            if spec.kind == "choice" and {v for v, _ in options} != set(spec.options):
                raise ObligationError(f"questions {q['id']}: options must cover {', '.join(spec.options)}")
            if spec.kind == "state":
                options = tuple((s, s) for s in spec.options)
            facts.append(
                FactQuestion(unique(q["id"]), q["fact"], q["text"], q["type"], options, bool(q.get("allow_unknown")), q.get("ask_if"))
            )

        evidence = []
        for q in raw.get("evidence", []):
            if q.get("obligation") not in obligation_ids:
                raise ObligationError(f"questions {q.get('id')}: unknown obligation {q.get('obligation')!r}")
            if q.get("dimension") not in ASKED_DIMENSIONS:
                raise ObligationError(f"questions {q['id']}: dimension must be one of {', '.join(ASKED_DIMENSIONS)}")
            if q.get("severity") not in SEVERITIES:
                raise ObligationError(f"questions {q['id']}: severity must be one of {', '.join(SEVERITIES)}")
            if q.get("ask_if"):
                conditions.validate(q["ask_if"], f"questions {q['id']}.ask_if")
            evidence.append(
                EvidenceQuestion(
                    id=unique(q["id"]),
                    obligation=q["obligation"],
                    dimension=q["dimension"],
                    text=q["text"],
                    severity=q["severity"],
                    allow_na=bool(q.get("allow_na")),
                    ask_if=q.get("ask_if"),
                    evidence=tuple(q.get("evidence", [])),
                    why=q["why"],
                    next_step=q["next_step"],
                )
            )

        contradictions = []
        for c in raw.get("contradictions", []):
            conditions.validate(c["when"], f"contradiction {c['id']}")
            for qid in c["questions"]:
                if qid not in seen:
                    raise ObligationError(f"contradiction {c['id']}: unknown question {qid}")
            contradictions.append(Contradiction(c["id"], c["when"], c["message"], tuple(c["questions"])))

        materiality = raw.get("materiality") or {}
        if materiality.get("elevate_when"):
            conditions.validate(materiality["elevate_when"], "materiality.elevate_when")
        return cls(facts, evidence, contradictions, materiality, conditions)

    # ------------------------------------------------------------------ evaluation
    def _true(self, cond: dict[str, Any] | None, facts: dict[str, Any], on: dt.date) -> bool:
        if not cond:
            return True
        try:
            return self.conditions.evaluate(cond, facts, on).value is True
        except ParameterError:
            return False

    def visible_facts(self, facts: dict[str, Any], on: dt.date) -> list[FactQuestion]:
        return [q for q in self.facts if self._true(q.ask_if, facts, on)]

    def visible_evidence(self, applicable: set[str], facts: dict[str, Any], on: dt.date) -> list[EvidenceQuestion]:
        return [q for q in self.evidence if q.obligation in applicable and self._true(q.ask_if, facts, on)]

    def active_contradictions(self, facts: dict[str, Any], on: dt.date) -> list[dict[str, Any]]:
        return [
            {"id": c.id, "message": c.message, "questions": list(c.questions)}
            for c in self.contradictions
            if self._true(c.when, facts, on)
        ]

    def elevated(self, facts: dict[str, Any], on: dt.date) -> bool | None:
        cond = self.materiality.get("elevate_when")
        if not cond:
            return False
        try:
            return self.conditions.evaluate(cond, facts, on).value
        except ParameterError:
            return None

    def fact_label(self, fact: str) -> str:
        q = self.by_fact.get(fact)
        return q.text if q else fact.replace("_", " ")

    # ------------------------------------------------------------------ answers
    def check_answer(self, qid: str, value: Any) -> tuple[str, Any]:
        """Validate one answer. Returns ``("fact", (fact, value))`` or ``("evidence", value)``."""
        q = self.by_id.get(qid)
        if q is None:
            raise Invalid(f"{qid}: unknown question")
        if isinstance(q, FactQuestion):
            if value == UNKNOWN and not q.allow_unknown:
                raise Invalid(f"{qid}: an answer is needed for this question")
            try:
                return "fact", (q.fact, normalise(q.fact, value))
            except Invalid as exc:
                raise Invalid(f"{qid}: {str(exc).partition(': ')[2]}") from None
        if value is None or value == "":
            return "evidence", None
        allowed = EVIDENCE_ANSWERS + ((NOT_APPLICABLE,) if q.allow_na else ())
        if value not in allowed:
            raise Invalid(f"{qid}: must be one of {', '.join(allowed)}")
        return "evidence", value

    # ------------------------------------------------------------------ state
    def questionnaire(
        self, facts: dict[str, Any], answers: dict[str, Any], applicable: dict[str, str], on: dt.date
    ) -> dict[str, Any]:
        """Visible questions with their status, hidden question ids, and active contradictions.

        ``applicable`` maps applicable obligation ids to titles.
        """
        shown: list[dict[str, Any]] = []
        for q in self.visible_facts(facts, on):
            value = facts.get(q.fact)
            status = "unanswered" if value is None else UNKNOWN if value == UNKNOWN else "answered"
            shown.append(
                {
                    "id": q.id,
                    "kind": "fact",
                    "fact": q.fact,
                    "text": q.text,
                    "type": q.type,
                    "options": [{"value": v, "label": label} for v, label in q.options],
                    "allow_unknown": q.allow_unknown,
                    "answer": value,
                    "status": status,
                }
            )
        for e in self.visible_evidence(set(applicable), facts, on):
            value = answers.get(e.id)
            status = {None: "unanswered", UNKNOWN: UNKNOWN, NOT_APPLICABLE: NOT_APPLICABLE}.get(value, "answered")
            shown.append(
                {
                    "id": e.id,
                    "kind": "evidence",
                    "obligation": e.obligation,
                    "obligation_title": applicable[e.obligation],
                    "dimension": e.dimension,
                    "text": e.text,
                    "type": "evidence",
                    "allow_na": e.allow_na,
                    "answer": value,
                    "status": status,
                }
            )
        visible = {q["id"] for q in shown}
        counts = {s: sum(1 for q in shown if q["status"] == s) for s in ("answered", UNKNOWN, NOT_APPLICABLE, "unanswered")}
        return {
            "questions": shown,
            "not_applicable": [qid for qid in self.by_id if qid not in visible],
            "contradictions": self.active_contradictions(facts, on),
            "progress": {"shown": len(shown), **counts},
        }
