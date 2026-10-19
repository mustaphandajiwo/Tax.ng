"""HC-01, HC-02: the obligations engine over rules/obligations, and its data validation."""

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from taxng.config import CONTENT_DIR, RULES_DIR
from taxng.legal import Library
from taxng.modules.compliance.questions import QuestionBank
from taxng.modules.compliance.rules import ObligationError, ObligationRules, due_date
from taxng.rules import ParameterTree

CONTRACT_KEYS = {"id", "tax", "title", "frequency", "period", "due_date", "provision", "evidence", "applies_because", "review_status"}
SMALL = {"annual_turnover": "80000000.00", "fixed_assets": "50000000.00"}
LARGE = {"annual_turnover": "500000000.00", "fixed_assets": "300000000.00"}


def ids(items: list[dict]) -> set[str]:
    return {i["id"] for i in items}


class RealRules(unittest.TestCase):
    tree: ParameterTree
    rules: ObligationRules

    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = ParameterTree.from_directory(RULES_DIR / "parameters")
        cls.rules = ObligationRules.from_directory(RULES_DIR / "obligations", cls.tree)

    def test_contract_shape(self) -> None:
        items = self.rules.obligations_for({"entity_type": "company", "has_employees": True, **LARGE}, 2026)
        self.assertTrue(items)
        for item in items:
            self.assertTrue(CONTRACT_KEYS <= set(item), item)
            dt.date.fromisoformat(item["due_date"])
            self.assertIn(item["review_status"], ("unverified", "secondary_source"))
            self.assertTrue(item["applies_because"].endswith("."))

    def test_employee_without_other_income_has_no_return(self) -> None:
        facts = {"entity_type": "individual", "has_employment_income": True, "has_business_income": False, "has_employees": False,
                 "has_rental_income": False, "has_foreign_income": False, "has_capital_gains": False}  # fmt: skip
        result = self.rules.evaluate(facts, 2026)
        self.assertEqual(result["applicable"], [])
        self.assertEqual(result["undetermined"], [])

    def test_company_without_staff_gets_no_paye(self) -> None:
        facts = {"entity_type": "company", "has_employees": False, **SMALL}
        found = ids(self.rules.obligations_for(facts, 2026))
        self.assertNotIn("paye.monthly_remittance", found)
        self.assertIn("cit.annual_return", found)  # small companies still file

    def test_small_company_has_no_levy_large_company_does(self) -> None:
        self.assertNotIn("cit.development_levy", ids(self.rules.obligations_for({"entity_type": "company", "is_professional_services": False, **SMALL}, 2026)))
        large = {"entity_type": "company", "non_resident": False, **LARGE}
        self.assertIn("cit.development_levy", ids(self.rules.obligations_for(large, 2026)))
        # Residence unanswered: the levy cannot be decided, so it is undetermined rather than applied.
        result = self.rules.evaluate({"entity_type": "company", **LARGE}, 2026)
        self.assertIn("cit.development_levy", ids(result["undetermined"]))
        professional = {"entity_type": "company", "is_professional_services": True, "non_resident": False, **SMALL}
        self.assertIn("cit.development_levy", ids(self.rules.obligations_for(professional, 2026)))
        non_resident = {"entity_type": "company", "non_resident": True, **LARGE}
        self.assertNotIn("cit.development_levy", ids(self.rules.obligations_for(non_resident, 2026)))

    def test_category_alone_never_triggers_activity_taxes(self) -> None:
        for entity in ("company", "sole_proprietor", "partnership", "nonprofit", "individual"):
            found = ids(self.rules.obligations_for({"entity_type": entity}, 2026))
            self.assertFalse(found & {"paye.monthly_remittance", "vat.monthly_return", "wht.monthly_remittance"}, entity)

    def test_unknown_facts_are_undetermined_not_applicable(self) -> None:
        for facts in ({"has_employees": "unknown"}, {}):
            result = self.rules.evaluate(facts, 2026)
            self.assertNotIn("paye.monthly_remittance", ids(result["applicable"]))
            paye = next(u for u in result["undetermined"] if u["id"] == "paye.monthly_remittance")
            self.assertEqual(paye["unknown_facts"], ["has_employees"])

    def test_vat_threshold_comes_from_the_cit_parameter(self) -> None:
        ceiling = self.tree.value("cit.small_company.turnover_ceiling", dt.date(2026, 1, 1))
        base = {"entity_type": "company", "sells_taxable_supplies": True}
        self.assertNotIn("vat.monthly_return", ids(self.rules.obligations_for({**base, "annual_turnover": str(ceiling)}, 2026)))
        vat = [i for i in self.rules.obligations_for({**base, "annual_turnover": str(ceiling + 1)}, 2026) if i["id"] == "vat.monthly_return"]
        self.assertEqual(len(vat), 12)
        self.assertEqual(vat[0]["review_status"], "unverified")
        self.assertIn("vat.monthly_return", ids(self.rules.evaluate({**base}, 2026)["undetermined"]))

    def test_wht_due_on_21st_of_following_month(self) -> None:
        items = [i for i in self.rules.obligations_for({"entity_type": "company", "makes_wht_payments": True}, 2026) if i["id"] == "wht.monthly_remittance"]
        self.assertEqual([i["period"] for i in items][:2], ["2026-01", "2026-02"])
        self.assertEqual(items[0]["due_date"], "2026-02-21")
        self.assertEqual(items[-1]["due_date"], "2027-01-21")
        self.assertEqual(items[0]["due_date_review_status"], "secondary_source")

    def test_other_due_dates_are_unverified(self) -> None:
        facts = {"entity_type": "company", "has_employees": True, "has_capital_gains": True, "non_resident": False, **LARGE}
        for item in self.rules.obligations_for(facts, 2026):
            if item["id"] != "wht.monthly_remittance":
                self.assertEqual(item["due_date_review_status"], "unverified", item["id"])
        cit = next(i for i in self.rules.obligations_for(facts, 2026) if i["id"] == "cit.annual_return")
        self.assertEqual(cit["due_date"], "2027-06-30")

    def test_hni_with_rental_and_foreign_income(self) -> None:
        facts = {"entity_type": "individual", "has_rental_income": True, "has_foreign_income": True, "has_capital_gains": True}
        found = self.rules.obligations_for(facts, 2026)
        self.assertEqual(ids(found), {"pit.self_assessment", "pit.rental_income", "cgt.individual_gains"})
        pit = next(i for i in found if i["id"] == "pit.self_assessment")
        self.assertEqual(pit["due_date"], "2027-03-31")
        self.assertIn("rental income", pit["applies_because"])
        self.assertIn("foreign income", pit["applies_because"])

    def test_no_rules_before_the_reform(self) -> None:
        self.assertEqual(self.rules.obligations_for({"entity_type": "company", "has_employees": True}, 2025), [])

    def test_data_references_resolve(self) -> None:
        library = Library.load(CONTENT_DIR, self.tree)
        for ob in self.rules.obligations:
            self.assertIn(ob.provision, library.provisions, ob.id)
            if ob.guide:
                self.assertIn(ob.guide, library.guides, ob.id)
        bank = QuestionBank.from_file(CONTENT_DIR / "compliance" / "questions.yaml", self.rules.conditions, set(self.rules.ids()))
        covered = {q.obligation for q in bank.evidence}
        self.assertEqual(covered, set(self.rules.ids()), "every obligation needs evidence questions")


class EffectiveDating(unittest.TestCase):
    """Changing effective dates alters only the affected periods (PRD acceptance test)."""

    tree: ParameterTree

    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = ParameterTree.from_directory(RULES_DIR / "parameters")

    def load(self, text: str) -> ObligationRules:
        root = Path(tempfile.mkdtemp())
        (root / "test.yaml").write_text(text, encoding="utf-8")
        return ObligationRules.from_directory(root, self.tree)

    BASE = """
- id: paye.test
  tax: pit
  title: Test PAYE
  frequency: monthly
  valid_from: 2026-01-01
  valid_to: {to}
  review_status: unverified
  applies_if: {{fact: has_employees, eq: true}}
  due: {{rule: day_of_following_month, day: 10, review_status: unverified}}
  provision: ntaa2025.paye.remittance
  evidence: [payroll]
"""
    LATER = """
- id: paye.test
  tax: pit
  title: Test PAYE
  frequency: monthly
  valid_from: {start}
  valid_to: null
  review_status: unverified
  applies_if: {{fact: has_employees, eq: true}}
  due: {{rule: day_of_following_month, day: 15, review_status: unverified}}
  provision: ntaa2025.paye.remittance
  evidence: [payroll]
"""

    def test_new_version_changes_only_later_periods(self) -> None:
        before = self.load(self.BASE.format(to="null")).obligations_for({"has_employees": True}, 2026)
        after = self.load(self.BASE.format(to="2026-07-01") + self.LATER.format(start="2026-07-01")).obligations_for({"has_employees": True}, 2026)
        self.assertEqual(len(before), 12)
        self.assertEqual(len(after), 12)
        changed = [b["period"] for b, a in zip(before, after) if b["due_date"] != a["due_date"]]
        self.assertEqual(changed, [f"2026-{m:02d}" for m in range(7, 13)])
        self.assertEqual(after[5]["due_date"], "2026-07-10")
        self.assertEqual(after[6]["due_date"], "2026-08-15")
        self.assertEqual({a["version"] for a in after[6:]}, {"2026-07-01"})

    def test_ending_a_rule_removes_only_later_periods(self) -> None:
        items = self.load(self.BASE.format(to="2026-04-01")).obligations_for({"has_employees": True}, 2026)
        self.assertEqual([i["period"] for i in items], ["2026-01", "2026-02", "2026-03"])

    def test_overlapping_versions_are_rejected(self) -> None:
        with self.assertRaises(ObligationError):
            self.load(self.BASE.format(to="null") + self.LATER.format(start="2026-07-01"))

    def test_malformed_rules_are_rejected(self) -> None:
        bad = {
            "unknown fact": self.BASE.format(to="null").replace("has_employees", "has_yacht"),
            "unknown parameter": self.BASE.format(to="null").replace("{fact: has_employees, eq: true}", "{fact: annual_turnover, gt: {param: cit.nope}}"),
            "bad frequency": self.BASE.format(to="null").replace("monthly", "weekly"),
            "bad due rule": self.BASE.format(to="null").replace("day_of_following_month", "whenever"),
            "bad status": self.BASE.format(to="null").replace("review_status: unverified\n  applies_if", "review_status: approved\n  applies_if"),
            "two operators": self.BASE.format(to="null").replace("eq: true}", "eq: true, ne: false}"),
        }
        for label, text in bad.items():
            with self.subTest(label), self.assertRaises(ObligationError):
                self.load(text)


class DueDates(unittest.TestCase):
    def test_short_months_are_clamped(self) -> None:
        self.assertEqual(due_date({"rule": "day_of_following_month", "day": 31}, dt.date(2026, 1, 31)), dt.date(2026, 2, 28))
        self.assertEqual(due_date({"rule": "months_after_period_end", "months": 6}, dt.date(2026, 12, 31)), dt.date(2027, 6, 30))


if __name__ == "__main__":
    unittest.main()
