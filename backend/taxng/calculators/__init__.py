"""Calculators. Each reads rules only through a ParameterView (CALC-07)."""

from .cgt import calculate_cgt
from .cit import calculate_cit
from .common import CalculationResult, InputError
from .pit import calculate_pit, compare_pit
from .stamp_duty import calculate_stamp_duty
from .vat import calculate_vat
from .wht import calculate_wht, payment_types

CALCULATORS = {
    "pit": calculate_pit,
    "cit": calculate_cit,
    "vat": calculate_vat,
    "wht": calculate_wht,
    "cgt": calculate_cgt,  # CALC-06
    "stamp-duty": calculate_stamp_duty,  # CALC-06
}

__all__ = [
    "CALCULATORS",
    "CalculationResult",
    "InputError",
    "calculate_cgt",
    "calculate_cit",
    "calculate_pit",
    "calculate_stamp_duty",
    "calculate_vat",
    "calculate_wht",
    "compare_pit",
    "payment_types",
]
