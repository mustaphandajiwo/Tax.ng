"""Tax AI: intent parsing, retrieval and, above all, the two guards."""

from __future__ import annotations

import unittest
from decimal import Decimal

from taxng.ai import Assistant, Draft, TemplateProvider, ToolCall, classify, guard
from taxng.services import build_services


class Classify(unittest.TestCase):
    def test_amount_and_tax(self) -> None:
        i = classify("How much PAYE on ₦6m salary?", 2026)
        self.assertIn("pit", i.taxes)
        self.assertEqual(i.amount, Decimal(6_000_000))

    def test_year_is_not_an_amount(self) -> None:
        i = classify("What changed for salary earners in 2026?", 2025)
        self.assertEqual(i.year, 2026)
        self.assertIsNone(i.amount)

    def test_monthly(self) -> None:
        i = classify("I earn 450,000 per month", 2026)
        self.assertTrue(i.monthly)
        self.assertEqual(i.amount, Decimal(450_000))


class Guards(unittest.TestCase):
    def test_rejects_citation_not_retrieved(self) -> None:
        report = guard(Draft("Some text.", ["made.up.provision"]), {"nta2025.vat.rate"}, [])
        self.assertFalse(report.citations_ok)

    def test_rejects_figure_not_from_engine(self) -> None:
        call = ToolCall("get_parameter", {"name": "vat.standard_rate"}, "0.075")
        report = guard(Draft("VAT is 10%.", []), set(), [call])
        self.assertFalse(report.figures_ok)

    def test_accepts_engine_figures_in_percent_and_naira(self) -> None:
        calls = [
            ToolCall("get_parameter", {}, "0.075"),
            ToolCall("calculate_pit", {}, {"annual_tax": "330000.00"}),
        ]
        report = guard(Draft("VAT is 7.5%. Tax is ₦330,000.", []), set(), calls)
        self.assertTrue(report.passed, report.problems)


class BadProvider(TemplateProvider):
    """Simulates an LLM that invents a rate and a citation."""

    def compose(self, question, intent, passages, tools, calculation):  # type: ignore[override]
        return Draft("The VAT rate is 10% under section 999.", ["nta2025.fake"])


class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.services = build_services(database=":memory:")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.services.store.close()

    def test_salary_question_uses_calculator_tool(self) -> None:
        r = self.services.assistant.answer("How much PAYE on a salary of ₦6m?")
        self.assertFalse(r["blocked"])
        self.assertIn("calculate_pit", [c["name"] for c in r["tool_calls"]])
        self.assertEqual(r["calculation"]["outputs"]["annual_tax"], "870000.00")
        self.assertIn("₦870,000", r["answer"])

    def test_old_year_retrieves_old_law_only(self) -> None:
        r = self.services.assistant.answer("What was the consolidated relief allowance in 2025?")
        ids = [c["id"] for c in r["citations"]]
        self.assertIn("pita.cra", ids)
        self.assertFalse(any(i.startswith("nta2025.pit") for i in ids))

    def test_out_of_scope_escalates(self) -> None:
        r = self.services.assistant.answer("Who won the football match?")
        self.assertTrue(r["escalate"])
        self.assertEqual(r["citations"], [])

    def test_invented_answer_is_blocked(self) -> None:
        s = self.services
        bad = Assistant(s.tree, s.library, s.index, provider=BadProvider())
        r = bad.answer("What is the VAT rate?")
        self.assertTrue(r["blocked"])
        self.assertFalse(r["guard"]["citations_ok"])
        self.assertFalse(r["guard"]["figures_ok"])
        self.assertNotIn("10%", r["answer"])


if __name__ == "__main__":
    unittest.main()
