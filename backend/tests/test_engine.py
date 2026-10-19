from __future__ import annotations

import datetime as dt
import tempfile
import textwrap
import unittest
from decimal import Decimal
from pathlib import Path

from taxng.config import RULES_DIR
from taxng.rules import Bracket, ParameterError, ParameterTree, ParameterView, apply_scale

D = Decimal


def tree_from(yaml_text: str) -> ParameterTree:
    tmp = Path(tempfile.mkdtemp())
    (tmp / "t.yaml").write_text(textwrap.dedent(yaml_text))
    return ParameterTree.from_directory(tmp)


class EffectiveDates(unittest.TestCase):
    def setUp(self) -> None:
        self.tree = tree_from(
            """
            rate:
              metadata: {review_status: legal_approved, provision: p.one}
              values:
                2020-01-01: {value: 0.05}
                2026-01-01: {value: 0.075}
                2030-01-01: {value: null}
            """
        )

    def test_value_applies_from_start_date(self) -> None:
        self.assertEqual(self.tree.value("t.rate", dt.date(2025, 12, 31)), D("0.05"))
        self.assertEqual(self.tree.value("t.rate", dt.date(2026, 1, 1)), D("0.075"))

    def test_before_first_value_is_not_in_force(self) -> None:
        with self.assertRaises(ParameterError):
            self.tree.value("t.rate", dt.date(2019, 6, 1))

    def test_null_repeals(self) -> None:
        with self.assertRaises(ParameterError):
            self.tree.value("t.rate", dt.date(2031, 1, 1))

    def test_unknown_parameter(self) -> None:
        with self.assertRaises(ParameterError):
            self.tree.value("t.missing", dt.date(2026, 1, 1))

    def test_view_records_lookups_and_review_status(self) -> None:
        view = ParameterView(self.tree, dt.date(2026, 6, 1))
        view.value("t.rate")
        self.assertEqual(view.used, {"t.rate": D("0.075")})
        self.assertEqual(view.review_status(), "legal_approved")
        self.assertEqual(view.provisions(), ["p.one"])


class Metadata(unittest.TestCase):
    def test_children_inherit_and_override(self) -> None:
        tree = tree_from(
            """
            metadata: {review_status: secondary_source, provision: parent}
            a: {values: {2026-01-01: {value: 1}}}
            b:
              metadata: {review_status: unverified}
              values: {2026-01-01: {value: 2}}
            """
        )
        self.assertEqual(tree.info("t.a").review_status, "secondary_source")
        self.assertEqual(tree.info("t.b").review_status, "unverified")
        self.assertEqual(tree.info("t.b").provision, "parent")

    def test_weakest_status_wins(self) -> None:
        tree = tree_from(
            """
            a: {metadata: {review_status: legal_approved}, values: {2026-01-01: {value: 1}}}
            b: {metadata: {review_status: unverified}, values: {2026-01-01: {value: 2}}}
            """
        )
        view = ParameterView(tree, dt.date(2026, 1, 1))
        view.value("t.a")
        view.value("t.b")
        self.assertEqual(view.review_status(), "unverified")

    def test_version_changes_with_content(self) -> None:
        one = tree_from("a: {values: {2026-01-01: {value: 1}}}")
        two = tree_from("a: {values: {2026-01-01: {value: 2}}}")
        self.assertNotEqual(one.version, two.version)


class Scales(unittest.TestCase):
    def test_marginal_bands(self) -> None:
        brackets = [Bracket(D(0), D(0)), Bracket(D(100), D("0.1")), Bracket(D(200), D("0.2"))]
        total, bands = apply_scale(D(250), brackets)
        self.assertEqual(total, D(20))  # 100 x 10% + 50 x 20%
        self.assertEqual([b.taxable for b in bands], [D(100), D(100), D(50)])

    def test_zero_income(self) -> None:
        total, _ = apply_scale(D(0), [Bracket(D(0), D("0.1"))])
        self.assertEqual(total, D(0))


class ShippedRules(unittest.TestCase):
    """Structural checks on the real rule files."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = ParameterTree.from_directory(RULES_DIR / "parameters")

    def test_every_parameter_has_review_status_and_provision(self) -> None:
        for name in self.tree.names():
            info = self.tree.info(name)
            with self.subTest(name=name):
                self.assertIn(info.review_status, {"unverified", "secondary_source", "legal_approved"})
                self.assertTrue(info.provision, "parameter must link a provision")

    def test_no_rule_is_legally_approved_yet(self) -> None:
        # Guard rail for the demo: flipping a status to legal_approved must be a
        # deliberate, reviewed change, never a side effect.
        self.assertFalse(any(self.tree.info(n).review_status == "legal_approved" for n in self.tree.names()))

    def test_pit_regime_switches_in_2026(self) -> None:
        self.assertEqual(self.tree.value("pit.regime", dt.date(2025, 12, 31)), "pita")
        self.assertEqual(self.tree.value("pit.regime", dt.date(2026, 1, 1)), "nta2025")


if __name__ == "__main__":
    unittest.main()
