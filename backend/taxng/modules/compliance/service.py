"""Compliance domain service: profile, health-check runs and the cross-module contract.

``services.modules["compliance"]`` is an instance of :class:`ComplianceService`.
Contract methods (docs/MODULES.md):

* :meth:`obligations_for` (HC-01, HC-02)
* :meth:`account_summary` (AI-04, ADV-02 intake)

Module extension used by advisory (ADV-03): :meth:`report_for_delegate`, the
client's latest completed report, read only under an engagement consent that
the advisory module checks and audits.

Every query on personal data filters by ``user_id``; a check that belongs to
someone else is reported as not found.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ...api.router import NotFound
from ...platform.errors import Conflict, Invalid
from ...platform.util import iso, new_id
from .facts import merge
from .findings import build_report
from .questions import QuestionBank
from .rules import ObligationRules

if TYPE_CHECKING:
    from ...services import Services

MAX_YEAR = 2035  # input sanity bound shared with calculators.common.Fields.year


class ComplianceService:
    def __init__(self, services: Services, *, today: Callable[[], dt.date] = dt.date.today) -> None:
        self.services = services
        self.db = services.db
        self.today = today
        self.rules = ObligationRules.from_directory(services.rules_dir / "obligations", services.tree)
        self.bank = QuestionBank.from_file(
            services.content_dir / "compliance" / "questions.yaml", self.rules.conditions, set(self.rules.ids())
        )

    # ------------------------------------------------------------------ contract
    def obligations_for(self, facts: dict[str, Any], year: int) -> list[dict[str, Any]]:
        """Obligations that apply for each period of ``year`` (contract; HC-01).

        Only obligations whose conditions are definitely met are returned. Use
        :meth:`evaluate` to see the ones that cannot be decided from ``facts``.
        """
        return self.rules.obligations_for(facts or {}, int(year))

    def evaluate(self, facts: dict[str, Any], year: int) -> dict[str, Any]:
        return self.rules.evaluate(facts or {}, int(year))

    def account_summary(self, user_id: str) -> dict[str, Any]:
        """Saved profile facts and the latest health-check findings by dimension (contract).

        No document data and no free text from the user is included.
        """
        profile = self.get_profile(user_id)
        latest = self._latest_completed(user_id)
        summary: dict[str, Any] = {
            "facts": profile["facts"],
            "profile_updated_at": profile["updated_at"],
            "labels": {f: self.bank.fact_label(f) for f in profile["facts"]},
            "latest_check": None,
        }
        if latest:
            report = json.loads(latest["report_json"])
            by_dim: dict[str, list[dict[str, Any]]] = {d["id"]: [] for d in report["dimensions"]}
            for f in report["findings"]:
                specialism = next((link.get("specialism") for link in f["links"] if link["kind"] == "adviser"), "") or ""
                by_dim[f["dimension"]].append(
                    {k: f[k] for k in ("obligation", "obligation_title", "tax", "status", "severity", "review_recommended", "title")}
                    | {"specialism": specialism}
                )
            summary["latest_check"] = {
                "id": latest["id"],
                "year": latest["year"],
                "completed_at": latest["completed_at"],
                "dimensions": report["dimensions"],
                "findings_by_dimension": by_dim,
            }
        return summary

    def report_for_delegate(self, user_id: str) -> dict[str, Any] | None:
        """The user's latest completed report, for an adviser holding engagement consent."""
        latest = self._latest_completed(user_id)
        return json.loads(latest["report_json"]) if latest else None

    # ------------------------------------------------------------------ profile
    def get_profile(self, user_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT facts_json, updated_at FROM compliance_profiles WHERE user_id = ?", (user_id,))
        if not row:
            return {"facts": {}, "updated_at": None}
        return {"facts": json.loads(row["facts_json"]), "updated_at": row["updated_at"]}

    def _write_facts(self, user_id: str, facts: dict[str, Any]) -> str:
        at = iso()
        self.db.execute(
            "INSERT INTO compliance_profiles (user_id, facts_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET facts_json = excluded.facts_json, updated_at = excluded.updated_at",
            (user_id, json.dumps(facts, sort_keys=True), at),
        )
        return at

    def save_profile(self, user_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        current = self.get_profile(user_id)["facts"]
        facts = merge(current, updates)
        at = self._write_facts(user_id, facts)
        # Audit which facts changed, never their values (personal data stays out of the log).
        changed = sorted(k for k in set(current) | set(facts) if current.get(k) != facts.get(k))
        if changed:
            self.services.audit.record("compliance.profile_updated", "compliance_profile", user_id, actor_id=user_id, data={"facts": changed})
        return {"facts": facts, "updated_at": at, "contradictions": self.bank.active_contradictions(facts, self.today())}

    def delete_profile(self, user_id: str) -> None:
        self.db.execute("DELETE FROM compliance_profiles WHERE user_id = ?", (user_id,))
        self.services.audit.record("compliance.profile_deleted", "compliance_profile", user_id, actor_id=user_id)

    # ------------------------------------------------------------------ checks
    def parse_year(self, raw: Any) -> int:
        try:
            year = int(raw)
        except (TypeError, ValueError):
            raise Invalid("year: must be a year") from None
        first = self.rules.first_year()
        if not first <= year <= MAX_YEAR:
            raise Invalid(f"year: the health check covers {first} to {MAX_YEAR}")
        return year

    def _row(self, user_id: str, check_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM compliance_checks WHERE id = ? AND user_id = ?", (check_id, user_id))
        if not row:
            raise NotFound("Health check not found")
        return row

    def _latest_completed(self, user_id: str) -> dict[str, Any] | None:
        return self.db.one(
            "SELECT * FROM compliance_checks WHERE user_id = ? AND status = 'completed' ORDER BY completed_at DESC, created_at DESC LIMIT 1",
            (user_id,),
        )

    def list_checks(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT id, year, status, created_at, updated_at, completed_at FROM compliance_checks WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        return rows

    def start_check(self, user_id: str, year: int) -> tuple[bool, dict[str, Any]]:
        """Resume the open check for ``year`` or start one. Returns ``(created, state)``."""
        existing = self.db.one(
            "SELECT id FROM compliance_checks WHERE user_id = ? AND year = ? AND status = 'in_progress'", (user_id, year)
        )
        if existing:
            return False, self.state(user_id, existing["id"])
        check_id = new_id("hc")
        at = iso()
        self.db.insert(
            "compliance_checks",
            {"id": check_id, "user_id": user_id, "year": year, "status": "in_progress", "created_at": at, "updated_at": at},
        )
        self.services.audit.record("compliance.check_started", "compliance_check", check_id, actor_id=user_id, data={"year": year})
        return True, self.state(user_id, check_id)

    def state(self, user_id: str, check_id: str) -> dict[str, Any]:
        row = self._row(user_id, check_id)
        facts = json.loads(row["facts_json"]) if row["status"] == "completed" else self.get_profile(user_id)["facts"]
        answers = json.loads(row["answers_json"])
        evaluation = self.evaluate(facts, row["year"])
        titles = {i["id"]: i["title"] for i in evaluation["applicable"]}
        on = dt.date(row["year"], 1, 1)
        return {
            "check": {k: row[k] for k in ("id", "year", "status", "created_at", "updated_at", "completed_at")},
            "facts": facts,
            **self.bank.questionnaire(facts, answers, titles, on),
            "obligations": _distinct(evaluation["applicable"]),
            "undetermined": evaluation["undetermined"],
        }

    def save_answers(self, user_id: str, check_id: str, answers: Any) -> dict[str, Any]:
        row = self._row(user_id, check_id)
        if row["status"] != "in_progress":
            raise Conflict("This health check is completed. Start a new one to change answers.")
        if not isinstance(answers, dict) or not answers:
            raise Invalid("answers: send at least one answer")
        fact_updates: dict[str, Any] = {}
        evidence = json.loads(row["answers_json"])
        for qid, value in answers.items():
            kind, parsed = self.bank.check_answer(str(qid), value)
            if kind == "fact":
                fact, fact_value = parsed
                fact_updates[fact] = fact_value
            elif parsed is None:
                evidence.pop(qid, None)
            else:
                evidence[qid] = parsed
        if fact_updates:
            self.save_profile(user_id, fact_updates)
        self.db.update(
            "compliance_checks", {"answers_json": json.dumps(evidence, sort_keys=True), "updated_at": iso()}, "id = ? AND user_id = ?", (check_id, user_id)
        )
        return self.state(user_id, check_id)

    def complete(self, user_id: str, check_id: str) -> dict[str, Any]:
        row = self._row(user_id, check_id)
        if row["status"] != "in_progress":
            raise Conflict("This health check is already completed")
        facts = self.get_profile(user_id)["facts"]
        on = dt.date(row["year"], 1, 1)
        contradictions = self.bank.active_contradictions(facts, on)
        if contradictions:
            raise Conflict("Some answers contradict each other. Please clarify them first: " + " ".join(c["message"] for c in contradictions))
        at = iso()
        report = build_report(
            bank=self.bank,
            evaluation=self.evaluate(facts, row["year"]),
            facts=facts,
            answers=json.loads(row["answers_json"]),
            year=row["year"],
            on=self.today(),
            library=self.services.library,
            rules_version=self.services.tree.version,
            generated_at=at,
            check_id=check_id,
        )
        self.db.update(
            "compliance_checks",
            {
                "status": "completed",
                "facts_json": json.dumps(facts, sort_keys=True),
                "report_json": json.dumps(report, sort_keys=True),
                "rules_version": self.services.tree.version,
                "completed_at": at,
                "updated_at": at,
            },
            "id = ? AND user_id = ?",
            (check_id, user_id),
        )
        self.services.audit.record(
            "compliance.check_completed", "compliance_check", check_id, actor_id=user_id,
            data={"year": row["year"], "rules_version": self.services.tree.version, "obligations": len(report["obligations"])},
        )  # fmt: skip
        return report

    def report(self, user_id: str, check_id: str) -> dict[str, Any]:
        row = self._row(user_id, check_id)
        if row["status"] != "completed":
            raise Conflict("Complete the health check to see the report")
        return json.loads(row["report_json"])

    def delete_check(self, user_id: str, check_id: str) -> None:
        self._row(user_id, check_id)
        self.db.execute("DELETE FROM compliance_checks WHERE id = ? AND user_id = ?", (check_id, user_id))
        self.services.audit.record("compliance.check_deleted", "compliance_check", check_id, actor_id=user_id)


def _distinct(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per obligation with its periods and next due dates, for the questionnaire view."""
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        entry = out.setdefault(
            item["id"],
            {k: item[k] for k in ("id", "tax", "title", "frequency", "provision", "applies_because", "review_status", "due_rule", "due_date_review_status", "note")}
            | {"periods": [], "due_dates": []},
        )
        entry["periods"].append(item["period"])
        entry["due_dates"].append(item["due_date"])
    return list(out.values())
