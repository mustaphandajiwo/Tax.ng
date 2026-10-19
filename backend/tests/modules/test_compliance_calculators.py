"""CALC-06: capital gains and stamp duty calculators beyond the worked examples in rules/tests/phase2_cases.yaml."""

from __future__ import annotations

import unittest
from decimal import Decimal

import taxng.api.handlers  # noqa: F401  (registers the public calculator routes)
from taxng.calculators import CALCULATORS, InputError
from taxng.config import RULES_DIR
from taxng.rules import ParameterTree

from ..helpers import ServicesTestCase

COMPANY = {"taxpayer_type": "company", "disposal_date": "2026-04-01", "asset_type": "other", "proceeds": 80000000, "cost": 50000000}


class CapitalGains(unittest.TestCase):
    tree: ParameterTree

    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = ParameterTree.from_directory(RULES_DIR / "parameters")

    def calc(self, **payload: object) -> dict:
        return CALCULATORS["cgt"](payload, self.tree).to_dict()

    def test_company_rate_is_read_from_cit_not_duplicated(self) -> None:
        result = self.calc(**COMPANY, annual_turnover=500000000, fixed_assets=300000000)
        self.assertIn("cit.rate.other", result["parameters_used"])
        self.assertEqual(Decimal(result["outputs"]["rate"]), self.tree.value("cit.rate.other", __import__("datetime").date(2026, 4, 1)))
        self.assertIn("nta2025.cgt.companies", result["citations"])

    def test_small_company_relief_is_unverified_and_warned(self) -> None:
        result = self.calc(**COMPANY, annual_turnover=80000000, fixed_assets=50000000)
        self.assertTrue(result["outputs"]["is_small_company"])
        self.assertEqual(result["review_status"], "unverified")
        self.assertTrue(any("not confirmed" in w for w in result["warnings"]))

    def test_professional_services_company_is_not_small(self) -> None:
        result = self.calc(**COMPANY, annual_turnover=80000000, fixed_assets=50000000, professional_services=True)
        self.assertFalse(result["outputs"]["is_small_company"])
        self.assertEqual(result["outputs"]["cgt"], "9000000.00")  # 30,000,000 x 30%

    def test_individual_treatment_is_flagged(self) -> None:
        result = self.calc(taxpayer_type="individual", disposal_date="2026-05-01", proceeds=20000000, cost=8000000)
        self.assertEqual(result["review_status"], "unverified")
        self.assertTrue(any("personal income tax rates" in w for w in result["warnings"]))

    def test_chattel_exemption_is_for_individuals_only(self) -> None:
        result = self.calc(**{**COMPANY, "asset_type": "chattel", "proceeds": 4000000, "cost": 1000000}, annual_turnover=500000000)
        self.assertFalse(result["outputs"]["exempt"])

    def test_share_exemption_uses_secondary_source(self) -> None:
        result = self.calc(**{**COMPANY, "asset_type": "shares", "proceeds": 100000000, "cost": 95000000}, annual_turnover=500000000)
        self.assertEqual(result["outputs"]["exemption"], "share_disposal")
        self.assertIn("cgt.share_exemption.proceeds_ceiling", result["parameters_used"])
        self.assertIn("nta2025.cgt.share_exemption", result["citations"])

    def test_share_gain_ceiling(self) -> None:
        result = self.calc(**{**COMPANY, "asset_type": "shares", "proceeds": 100000000, "cost": 85000000}, annual_turnover=500000000)
        # gain 15m > 10m ceiling, so taxable at the CIT rate
        self.assertEqual((result["outputs"]["exempt"], result["outputs"]["cgt"]), (False, "4500000.00"))

    def test_disposal_before_the_act_is_rejected(self) -> None:
        with self.assertRaises(InputError) as ctx:
            self.calc(**{**COMPANY, "disposal_date": "2025-06-01"}, annual_turnover=1)
        self.assertIn("disposal_date", ctx.exception.errors)

    def test_input_errors_are_collected(self) -> None:
        with self.assertRaises(InputError) as ctx:
            self.calc(taxpayer_type="trust", proceeds="abc")
        self.assertEqual(set(ctx.exception.errors), {"taxpayer_type", "proceeds"})
        with self.assertRaises(InputError) as ctx:
            self.calc(taxpayer_type="company", proceeds=1)
        self.assertIn("annual_turnover", ctx.exception.errors)


class StampDuty(unittest.TestCase):
    tree: ParameterTree

    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = ParameterTree.from_directory(RULES_DIR / "parameters")

    def calc(self, **payload: object) -> dict:
        return CALCULATORS["stamp-duty"](payload, self.tree).to_dict()

    def test_share_capital_warns_about_unverified_deadline(self) -> None:
        result = self.calc(instrument="share_capital", transaction_date="2026-03-01", amount=1000000)
        self.assertTrue(any("pending legal review" in w for w in result["warnings"]))
        self.assertEqual(result["review_status"], "unverified")
        self.assertIn("nta2025.stamp_duty.stamping_deadline", result["citations"])

    def test_own_account_flag_has_no_effect_on_share_capital(self) -> None:
        result = self.calc(instrument="share_capital", transaction_date="2026-03-01", amount=1000000, own_account=True)
        self.assertEqual(result["outputs"]["duty"], "7500.00")

    def test_electronic_transfer_is_secondary_source(self) -> None:
        result = self.calc(instrument="electronic_transfer", transaction_date="2026-03-01", amount=250000)
        self.assertEqual((result["outputs"]["duty"], result["review_status"]), ("50.00", "secondary_source"))

    def test_bad_instrument_and_date(self) -> None:
        with self.assertRaises(InputError) as ctx:
            self.calc(instrument="cheque", amount=1)
        self.assertIn("instrument", ctx.exception.errors)
        with self.assertRaises(InputError) as ctx:
            self.calc(instrument="share_capital", amount=1, transaction_date="2024-01-01")
        self.assertIn("transaction_date", ctx.exception.errors)


class CalculatorApi(ServicesTestCase):
    def test_public_endpoints(self) -> None:
        anon = self.client()
        status, body = anon.post("/api/calculate/cgt", {**COMPANY, "annual_turnover": 500000000})
        self.assertEqual((status, body["outputs"]["cgt"]), (200, "9000000.00"))
        status, body = anon.post("/api/calculate/stamp-duty", {"instrument": "electronic_transfer", "amount": 10000, "transaction_date": "2026-03-01"})
        self.assertEqual((status, body["outputs"]["duty"]), (200, "50.00"))
        status, body = anon.post("/api/calculate/cgt", {"taxpayer_type": "company"})
        self.assertEqual(status, 422)
        self.assertIn("proceeds", body["fields"])

    def test_new_provisions_and_guides_load(self) -> None:
        lib = self.services.library
        for pid in ("nta2025.cgt.companies", "nta2025.stamp_duty.electronic_transfer", "ntaa2025.cit.returns"):
            self.assertEqual(lib.provisions[pid].section, "[to be confirmed]")
        self.assertEqual(lib.guides["capital-gains-2026"].calculator, "cgt")


if __name__ == "__main__":
    unittest.main()
