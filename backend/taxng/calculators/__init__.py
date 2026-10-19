"""Calculators. Each reads rules only through a ParameterView (CALC-07)."""

from .cit import calculate_cit
from .common import CalculationResult, InputError
from .pit import calculate_pit, compare_pit
from .vat import calculate_vat
from .wht import calculate_wht, payment_types

CALCULATORS = {
    "pit": calculate_pit,
    "cit": calculate_cit,
    "vat": calculate_vat,
    "wht": calculate_wht,
}

__all__ = [
    "CALCULATORS",
    "CalculationResult",
    "InputError",
    "calculate_cit",
    "calculate_pit",
    "calculate_vat",
    "calculate_wht",
    "compare_pit",
    "payment_types",
]
