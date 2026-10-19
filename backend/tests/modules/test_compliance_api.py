"""Compliance module over HTTP: profile, health check, report and account summary (HC-01 to HC-07)."""

from __future__ import annotations

import json
import unittest
from typing import Any

from ..helpers import Client, ServicesTestCase

EMPLOYEE = {
    "q.entity_type": "individual",
    "q.has_employment_income": True,
    "q.has_business_income": False,
    "q.has_employees": False,
    "q.has_rental_income": False,
    "q.has_foreign_income": False,
    "q.has_capital_gains": False,
}
CORPORATE_QUESTIONS = {"q.fixed_assets", "q.is_professional_services", "q.non_resident", "q.annual_turnover", "q.sells_taxable_supplies", "q.makes_wht_payments"}


def keys_anywhere(data: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(data, dict):
        for k, v in data.items():
            found.add(k)
            found |= keys_anywhere(v)
    elif isinstance(data, list):
        for v in data:
            found |= keys_anywhere(v)
    return found


class Base(ServicesTestCase):
    def start(self, client: Client, year: int = 2026) -> dict:
        status, body = client.post("/api/compliance/checks", {"year": year})
        self.assertIn(status, (200, 201), body)
        return body

    def answer(self, client: Client, check_id: str, answers: dict) -> dict:
        status, body = client.put(f"/api/compliance/checks/{check_id}/answers", {"answers": answers})
        self.assertEqual(status, 200, body)
        return body

    def evidence_ids(self, state: dict, obligation: str | None = None) -> list[str]:
        return [q["id"] for q in state["questions"] if q["kind"] == "evidence" and (obligation is None or q["obligation"] == obligation)]


class AccessControl(Base):
    def test_anonymous_gets_401_everywhere(self) -> None:
        anon = self.client()
        calls = [
            ("GET", "/api/compliance/profile"), ("PUT", "/api/compliance/profile"), ("DELETE", "/api/compliance/profile"),
            ("GET", "/api/compliance/obligations"), ("GET", "/api/compliance/checks"), ("POST", "/api/compliance/checks"),
            ("GET", "/api/compliance/checks/hc_x"), ("PUT", "/api/compliance/checks/hc_x/answers"),
            ("POST", "/api/compliance/checks/hc_x/complete"), ("GET", "/api/compliance/checks/hc_x/report"),
            ("DELETE", "/api/compliance/checks/hc_x"),
        ]  # fmt: skip
        for method, path in calls:
            with self.subTest(method=method, path=path):
                self.assertEqual(anon.request(method, path, {}).status, 401)

    def test_other_users_check_is_not_found(self) -> None:
        alice = self.client("hc-alice@example.com")
        mallory = self.client("hc-mallory@example.com")
        check_id = self.start(alice)["check"]["id"]
        self.answer(alice, check_id, EMPLOYEE)
        self.assertEqual(mallory.get(f"/api/compliance/checks/{check_id}").status, 404)
        self.assertEqual(mallory.put(f"/api/compliance/checks/{check_id}/answers", {"answers": {"q.has_employees": True}}).status, 404)
        self.assertEqual(mallory.post(f"/api/compliance/checks/{check_id}/complete").status, 404)
        self.assertEqual(mallory.get(f"/api/compliance/checks/{check_id}/report").status, 404)
        self.assertEqual(mallory.delete(f"/api/compliance/checks/{check_id}").status, 404)
        self.assertEqual(mallory.get("/api/compliance/checks").body["items"], [])
        # Mallory's profile is her own: Alice's facts never leak into it.
        self.assertEqual(mallory.get("/api/compliance/profile").body["facts"], {})
        self.assertEqual(alice.get("/api/compliance/profile").body["facts"]["entity_type"], "individual")


class Profile(Base):
    def test_validation_and_minimal_data(self) -> None:
        c = self.client("hc-profile@example.com")
        status, body = c.put("/api/compliance/profile", {"facts": {"entity_type": "trust"}})
        self.assertEqual(status, 422)
        self.assertIn("entity_type", body["fields"])
        self.assertEqual(c.put("/api/compliance/profile", {"facts": {"email": "x@example.com"}}).status, 422)
        self.assertEqual(c.put("/api/compliance/profile", {"facts": {"employee_count": -1}}).status, 422)
        self.assertEqual(c.put("/api/compliance/profile", {"facts": {"annual_turnover": "lots"}}).status, 422)
        status, body = c.put("/api/compliance/profile", {"facts": {"entity_type": "company", "annual_turnover": "₦120,000,000", "state": "Lagos"}})
        self.assertEqual(status, 200)
        self.assertEqual(body["facts"]["annual_turnover"], "120000000.00")
        status, body = c.put("/api/compliance/profile", {"facts": {"state": None}})
        self.assertNotIn("state", body["facts"])
        events = self.services.audit.events(entity_id=c.user_id)
        logged = [json.loads(e["data_json"]) for e in events if e["action"] == "compliance.profile_updated"]
        self.assertTrue(logged)
        self.assertNotIn("120000000", json.dumps(logged))  # values never reach the audit log
        self.assertEqual(c.delete("/api/compliance/profile").status, 200)
        self.assertEqual(c.get("/api/compliance/profile").body["facts"], {})

    def test_my_obligations_endpoint(self) -> None:
        c = self.client("hc-mine@example.com")
        c.put("/api/compliance/profile", {"facts": {"entity_type": "company", "has_employees": True}})
        status, body = c.get("/api/compliance/obligations", {"year": "2026"})
        self.assertEqual(status, 200)
        self.assertIn("paye.monthly_remittance", {i["id"] for i in body["applicable"]})
        self.assertEqual(c.get("/api/compliance/obligations", {"year": "2024"}).status, 422)


class Questionnaire(Base):
    def test_employee_sees_no_corporate_questions(self) -> None:
        c = self.client("hc-employee@example.com")
        check_id = self.start(c)["check"]["id"]
        state = self.answer(c, check_id, EMPLOYEE)
        shown = {q["id"] for q in state["questions"]}
        self.assertFalse(shown & CORPORATE_QUESTIONS)
        self.assertTrue(CORPORATE_QUESTIONS <= set(state["not_applicable"]))
        self.assertEqual(state["obligations"], [])
        self.assertEqual(self.evidence_ids(state), [])

    def test_hni_with_rental_and_foreign_income_sees_those_branches(self) -> None:
        c = self.client("hc-hni@example.com")
        check_id = self.start(c)["check"]["id"]
        state = self.answer(c, check_id, {**EMPLOYEE, "q.has_rental_income": True, "q.has_foreign_income": True})
        evidence = set(self.evidence_ids(state))
        self.assertTrue({"e.rent.agreements", "e.rent.reported", "e.foreign.tax_paid", "e.foreign.reported"} <= evidence)
        self.assertEqual({o["id"] for o in state["obligations"]}, {"pit.self_assessment", "pit.rental_income"})
        # Turning the foreign branch off hides its follow-ups again.
        state = self.answer(c, check_id, {"q.has_foreign_income": False})
        self.assertNotIn("e.foreign.tax_paid", self.evidence_ids(state))
        self.assertIn("e.foreign.tax_paid", state["not_applicable"])

    def test_company_without_staff_gets_no_paye_task(self) -> None:
        c = self.client("hc-company@example.com")
        check_id = self.start(c)["check"]["id"]
        state = self.answer(
            c, check_id,
            {"q.entity_type": "company", "q.has_employees": False, "q.annual_turnover": "50000000", "q.fixed_assets": "1000000",
             "q.is_professional_services": False, "q.non_resident": False, "q.sells_taxable_supplies": True, "q.makes_wht_payments": False,
             "q.has_capital_gains": False},
        )  # fmt: skip
        self.assertNotIn("paye.monthly_remittance", {o["id"] for o in state["obligations"]})
        self.assertFalse([q for q in self.evidence_ids(state) if q.startswith("e.paye")])
        self.assertIn("cit.annual_return", {o["id"] for o in state["obligations"]})
        self.assertNotIn("q.employee_count", {q["id"] for q in state["questions"]})

    def test_statuses_are_distinct(self) -> None:
        c = self.client("hc-status@example.com")
        check_id = self.start(c)["check"]["id"]
        state = self.answer(c, check_id, {**EMPLOYEE, "q.has_rental_income": True, "q.has_business_income": "unknown"})
        by_id = {q["id"]: q for q in state["questions"]}
        self.assertEqual(by_id["q.has_business_income"]["status"], "unknown")
        self.assertEqual(by_id["e.rent.agreements"]["status"], "unanswered")
        state = self.answer(c, check_id, {"e.rent.wht_notes": "not_applicable", "e.rent.agreements": "yes"})
        by_id = {q["id"]: q for q in state["questions"]}
        self.assertEqual(by_id["e.rent.wht_notes"]["status"], "not_applicable")
        self.assertEqual(by_id["e.rent.agreements"]["status"], "answered")
        # "Not sure" is refused where the bank does not allow it, as is N/A on a question without it.
        self.assertEqual(c.put(f"/api/compliance/checks/{check_id}/answers", {"answers": {"q.entity_type": "unknown"}}).status, 422)
        self.assertEqual(c.put(f"/api/compliance/checks/{check_id}/answers", {"answers": {"e.rent.reported": "not_applicable"}}).status, 422)
        self.assertEqual(c.put(f"/api/compliance/checks/{check_id}/answers", {"answers": {"q.nope": True}}).status, 422)
        self.assertEqual(c.put(f"/api/compliance/checks/{check_id}/answers", {"answers": {}}).status, 422)

    def test_contradiction_triggers_clarification(self) -> None:
        c = self.client("hc-contradiction@example.com")
        check_id = self.start(c)["check"]["id"]
        self.answer(c, check_id, {"q.entity_type": "company", "q.has_employees": True, "q.employee_count": 4})
        state = self.answer(c, check_id, {"q.has_employees": False})
        self.assertEqual([x["id"] for x in state["contradictions"]], ["c.no_employees_but_count"])
        self.assertEqual(state["contradictions"][0]["questions"], ["q.has_employees", "q.employee_count"])
        status, body = c.post(f"/api/compliance/checks/{check_id}/complete")
        self.assertEqual(status, 409)
        self.assertIn("contradict", body["message"])
        state = self.answer(c, check_id, {"q.employee_count": None})
        self.assertEqual(state["contradictions"], [])
        self.assertEqual(c.post(f"/api/compliance/checks/{check_id}/complete").status, 200)


class Lifecycle(Base):
    def test_saved_progress_and_transitions(self) -> None:
        c = self.client("hc-life@example.com")
        status, first = c.post("/api/compliance/checks", {"year": 2026})
        self.assertEqual(status, 201)
        check_id = first["check"]["id"]
        self.answer(c, check_id, EMPLOYEE)
        status, again = c.post("/api/compliance/checks", {"year": 2026})
        self.assertEqual((status, again["check"]["id"]), (200, check_id))  # resumes, does not duplicate
        self.assertEqual(c.get(f"/api/compliance/checks/{check_id}/report").status, 409)  # not completed
        status, report = c.post(f"/api/compliance/checks/{check_id}/complete")
        self.assertEqual(status, 200)
        self.assertEqual(c.get(f"/api/compliance/checks/{check_id}").body["check"]["status"], "completed")
        self.assertEqual(c.post(f"/api/compliance/checks/{check_id}/complete").status, 409)
        self.assertEqual(c.put(f"/api/compliance/checks/{check_id}/answers", {"answers": {"q.has_employees": True}}).status, 409)
        status, fresh = c.post("/api/compliance/checks", {"year": 2026})
        self.assertEqual(status, 201)
        self.assertNotEqual(fresh["check"]["id"], check_id)
        self.assertEqual(c.post("/api/compliance/checks", {"year": 2019}).status, 422)
        self.assertEqual(c.delete(f"/api/compliance/checks/{fresh['check']['id']}").status, 200)
        self.assertEqual(c.get(f"/api/compliance/checks/{fresh['check']['id']}").status, 404)
        actions = {e["action"] for e in self.services.audit.events(entity_id=check_id)}
        self.assertTrue({"compliance.check_started", "compliance.check_completed"} <= actions)


class Report(Base):
    def run_hni(self, email: str, extra: dict | None = None) -> dict:
        c = self.client(email)
        check_id = self.start(c)["check"]["id"]
        state = self.answer(c, check_id, {**EMPLOYEE, "q.has_rental_income": True, "q.has_foreign_income": True})
        answers = {q: "yes" for q in self.evidence_ids(state)}
        answers.update({"e.pit.filed": "no", "e.rent.agreements": "no", "e.pit.on_time": "unknown", "e.rent.wht_notes": "not_applicable"})
        answers.pop("e.foreign.reported")  # left unanswered
        answers.update(extra or {})
        self.answer(c, check_id, answers)
        status, report = c.post(f"/api/compliance/checks/{check_id}/complete")
        self.assertEqual(status, 200, report)
        self.client_ = c
        self.check_id = check_id
        return report

    def test_findings_by_dimension_only_without_any_score(self) -> None:
        report = self.run_hni("hc-report1@example.com")
        self.assertEqual(
            [d["id"] for d in report["dimensions"]],
            ["obligation_coverage", "timeliness", "documentation", "reporting_accuracy", "exposure_materiality", "evidence_confidence"],
        )
        forbidden = {"score", "overall", "total_score", "grade", "rating", "percent", "health_score"}
        self.assertFalse(keys_anywhere(report) & forbidden)
        self.assertNotIn("score", json.dumps(report).lower())

    def test_unknown_is_insufficient_evidence_never_a_fail(self) -> None:
        report = self.run_hni("hc-report2@example.com")
        on_time = next(f for f in report["findings"] if f["id"] == "timeliness:e.pit.on_time")
        self.assertEqual((on_time["status"], on_time["severity"], on_time["review_recommended"]), ("insufficient_evidence", None, False))
        unanswered = next(f for f in report["findings"] if f["id"] == "reporting_accuracy:e.foreign.reported")
        self.assertEqual(unanswered["status"], "insufficient_evidence")
        self.assertEqual(unanswered["answer"], "Not answered yet")
        timeliness = next(d for d in report["dimensions"] if d["id"] == "timeliness")
        self.assertEqual(timeliness["status"], "insufficient_evidence")
        self.assertFalse([f for f in report["findings"] if f["question"] and "wht_notes" in f["id"]])  # N/A excluded

    def test_severe_first_review_not_liability_and_report_contents(self) -> None:
        report = self.run_hni("hc-report3@example.com")
        findings = report["findings"]
        rank = lambda f: (0 if f["status"] == "gap" else 1, {"high": 0, "medium": 1, "low": 2}.get(f["severity"] or "", 3))  # noqa: E731
        self.assertEqual([rank(f) for f in findings], sorted(rank(f) for f in findings))
        self.assertEqual(findings[0]["severity"], "high")
        self.assertTrue(findings[0]["review_recommended"])
        self.assertIn("not an official assessment", report["statement"])
        self.assertIn("self-reported", report["statement"])
        self.assertIn("not a finding of liability", report["review_note"])
        for f in findings:
            self.assertNotIn("you owe", (f["why_it_matters"] + f["next_step"]).lower())
            self.assertTrue(f["links"])
        self.assertTrue(report["next_steps"][0]["text"].startswith("Ask a qualified tax adviser"))
        self.assertEqual(report["missing_evidence"][0]["obligation"], "pit.rental_income")
        self.assertIn("ntaa2025.pit.self_assessment", {c["id"] for c in report["citations"]})
        matrix = {r["id"]: r for r in report["obligations"]}
        self.assertEqual(matrix["pit.rental_income"]["cells"]["documentation"], {"status": "gap", "severity": "medium"})
        self.assertEqual(matrix["pit.self_assessment"]["cells"]["evidence_confidence"]["status"], "insufficient_evidence")
        self.assertEqual(report["rules_version"], self.services.tree.version)

    def test_download_and_frozen_report(self) -> None:
        report = self.run_hni("hc-report4@example.com")
        reply = self.client_.get(f"/api/compliance/checks/{self.check_id}/report", {"download": "1"})
        self.assertEqual(reply.status, 200)
        self.assertIn("attachment", reply.headers["Content-Disposition"])
        self.assertEqual(json.loads(reply.raw)["check_id"], self.check_id)
        # Later profile changes do not alter a completed report.
        self.client_.put("/api/compliance/profile", {"facts": {"has_employees": True}})
        self.assertEqual(self.client_.get(f"/api/compliance/checks/{self.check_id}/report").body, report)

    def test_exposure_is_raised_for_larger_businesses(self) -> None:
        c = self.client("hc-exposure@example.com")
        check_id = self.start(c)["check"]["id"]
        state = self.answer(
            c, check_id,
            {"q.entity_type": "company", "q.has_employees": True, "q.employee_count": 30, "q.annual_turnover": "900000000",
             "q.fixed_assets": "10", "q.is_professional_services": False, "q.non_resident": False, "q.sells_taxable_supplies": False,
             "q.makes_wht_payments": False, "q.has_capital_gains": False},
        )  # fmt: skip
        answers = {q: "yes" for q in self.evidence_ids(state)}
        answers["e.paye.records"] = "no"  # a medium gap
        self.answer(c, check_id, answers)
        report = c.post(f"/api/compliance/checks/{check_id}/complete").body
        exposure = next(f for f in report["findings"] if f["id"] == "exposure_materiality:paye.monthly_remittance")
        self.assertEqual(exposure["severity"], "high")
        self.assertIn("not an amount owed", exposure["why_it_matters"])


class AccountSummary(Base):
    def test_contract(self) -> None:
        c = self.client("hc-summary@example.com")
        compliance = self.services.modules["compliance"]
        empty = compliance.account_summary(c.user_id)
        self.assertEqual((empty["facts"], empty["latest_check"]), ({}, None))
        check_id = self.start(c)["check"]["id"]
        state = self.answer(c, check_id, {**EMPLOYEE, "q.has_rental_income": True})
        self.answer(c, check_id, {q: "no" for q in self.evidence_ids(state)})
        c.post(f"/api/compliance/checks/{check_id}/complete")
        summary = compliance.account_summary(c.user_id)
        self.assertEqual(summary["facts"]["has_rental_income"], True)
        self.assertEqual(summary["latest_check"]["id"], check_id)
        self.assertEqual(set(summary["latest_check"]["findings_by_dimension"]), {d["id"] for d in summary["latest_check"]["dimensions"]})
        gap = summary["latest_check"]["findings_by_dimension"]["reporting_accuracy"][0]
        self.assertEqual(set(gap), {"obligation", "obligation_title", "tax", "status", "severity", "review_recommended", "title", "specialism"})
        self.assertNotIn("question", json.dumps(summary))  # no raw answers
        self.assertIn("has_rental_income", summary["labels"])


if __name__ == "__main__":
    unittest.main()
