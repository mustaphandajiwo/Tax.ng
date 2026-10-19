"""Behaviour beyond the worked examples: validation, warnings, consistency."""

from __future__ import annotations

import unittest
from decimal import Decimal

from taxng.calculators import InputError, calculate_cit, calculate_pit, calculate_wht, compare_pit
from taxng.config import RULES_DIR
from taxng.rules import ParameterTree


class Base(unittest.TestCase):
    tree: ParameterTree

    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = ParameterTree.from_directory(RULES_DIR / "parameters")


class Validation(Base):
    def test_collects_every_error(self) -> None:
        with self.assertRaises(InputError) as ctx:
            calculate_pit({"annual_gross_income": "abc", "pension": -1, "tax_year": 1999}, self.tree)
        self.assertEqual(set(ctx.exception.errors), {"annual_gross_income", "pension", "tax_year"})

    def test_accepts_formatted_amounts(self) -> None:
        r = calculate_pit({"annual_gross_income": "₦3,000,000", "tax_year": 2026}, self.tree)
        self.assertEqual(r.outputs["annual_tax"], "330000.00")

    def test_cit_rejects_pre_reform_years(self) -> None:
        with self.assertRaises(InputError):
            calculate_cit({"tax_year": 2025, "annual_turnover": 1, "total_profits": 1}, self.tree)

    def test_wht_rejects_recipient_type_without_rate(self) -> None:
        with self.assertRaises(InputError):
            calculate_wht({"payment_type": "directors_fees", "recipient_type": "corporate", "amount": 1}, self.tree)


class Pit(Base):
    def test_rent_ignored_under_pita_with_warning(self) -> None:
        r = calculate_pit({"annual_gross_income": 5_000_000, "annual_rent_paid": 1_000_000, "tax_year": 2025}, self.tree)
        self.assertTrue(any("Rent relief" in w for w in r.warnings))

    def test_mortgage_interest_not_deductible_under_pita(self) -> None:
        r = calculate_pit({"annual_gross_income": 5_000_000, "mortgage_interest": 100_000, "tax_year": 2025}, self.tree)
        self.assertTrue(any("Mortgage" in w for w in r.warnings))

    def test_deductions_cannot_make_income_negative(self) -> None:
        r = calculate_pit({"annual_gross_income": 100_000, "pension": 500_000, "tax_year": 2026}, self.tree)
        self.assertEqual(r.outputs["chargeable_income"], "0.00")
        self.assertEqual(r.outputs["annual_tax"], "0.00")

    def test_result_is_reproducible(self) -> None:
        r = calculate_pit({"annual_gross_income": 9_000_000, "tax_year": 2026}, self.tree).to_dict()
        self.assertEqual(r["rules_version"], self.tree.version)
        self.assertIn("pit.nta2025.rates", r["parameters_used"])
        self.assertIn("nta2025.pit.rates", r["citations"])
        self.assertEqual(r["review_status"], "unverified")  # weakest input: allowed_deductions

    def test_bands_sum_to_tax(self) -> None:
        r = calculate_pit({"annual_gross_income": 40_000_000, "tax_year": 2026}, self.tree).to_dict()
        total = sum(Decimal(b["tax"]) for b in r["bands"])
        self.assertEqual(total, Decimal(r["outputs"]["annual_tax"]))

    def test_compare_reports_direction(self) -> None:
        low = compare_pit({"annual_gross_income": 1_000_000}, self.tree)
        self.assertEqual(low["old"]["regime"], "pita")
        self.assertEqual(low["new"]["regime"], "nta2025")
        self.assertEqual(low["difference"]["direction"], "lower")


class Cit(Base):
    def test_minimum_etr_warning_for_very_large_companies(self) -> None:
        r = calculate_cit({"annual_turnover": 60_000_000_000, "fixed_assets": 1, "total_profits": 1_000_000}, self.tree)
        self.assertTrue(any("Minimum effective tax rate" in w for w in r.warnings))

    def test_non_resident_pays_no_levy(self) -> None:
        r = calculate_cit(
            {"annual_turnover": 500_000_000, "fixed_assets": 300_000_000, "total_profits": 10_000_000, "non_resident": True},
            self.tree,
        )
        self.assertEqual(r.outputs["development_levy"], "0.00")


if __name__ == "__main__":
    unittest.main()
