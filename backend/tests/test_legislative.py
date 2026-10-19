"""Runs every worked example in rules/tests/*.yaml against the calculators."""

from __future__ import annotations

import unittest
from decimal import Decimal

import yaml

from taxng.calculators import CALCULATORS
from taxng.config import RULES_DIR
from taxng.rules import ParameterTree

CASES_DIR = RULES_DIR / "tests"


def _load_cases() -> list[dict]:
    cases: list[dict] = []
    for path in sorted(CASES_DIR.glob("*.yaml")):
        for case in yaml.safe_load(path.read_text()) or []:
            case["_file"] = path.name
            cases.append(case)
    return cases


def _same(actual: object, expected: object) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return actual is expected
    return Decimal(str(actual)) == Decimal(str(expected))


class LegislativeCases(unittest.TestCase):
    tree: ParameterTree

    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = ParameterTree.from_directory(RULES_DIR / "parameters")

    def test_cases_exist(self) -> None:
        self.assertGreaterEqual(len(_load_cases()), 10)

    def test_all_cases(self) -> None:
        for case in _load_cases():
            with self.subTest(case=case["name"], file=case["_file"]):
                result = CALCULATORS[case["calculator"]](case["input"], self.tree).to_dict()
                for key, expected in case["output"].items():
                    self.assertIn(key, result["outputs"], f"missing output {key}")
                    self.assertTrue(
                        _same(result["outputs"][key], expected),
                        f"{key}: expected {expected}, got {result['outputs'][key]}",
                    )


if __name__ == "__main__":
    unittest.main()
