"""Personal income tax and PAYE (CALC-01) with the old-versus-new comparison (CALC-05).

The regime is selected by the ``pit.regime`` parameter on 1 January of the tax
year, so a year before 2026 applies PITA and 2026 onwards applies the Nigeria
Tax Act 2025. No rate, band or threshold appears in this module (CALC-07).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from ..format import naira, percent
from ..rules import ParameterTree, ParameterView, apply_scale
from .common import CalculationResult, Fields, Step, money, money_str

DEDUCTIONS: dict[str, str] = {
    "pension": "Pension contribution",
    "nhf": "National Housing Fund contribution",
    "nhis": "Health insurance (NHIS) contribution",
    "life_insurance": "Life insurance premium",
    "mortgage_interest": "Mortgage interest on owner-occupied home",
}


def _parse(payload: dict[str, Any]) -> dict[str, Any]:
    f = Fields(payload)
    parsed = {
        "tax_year": f.year("tax_year", default=2026),
        "annual_gross_income": f.money("annual_gross_income", required=True),
        "annual_rent_paid": f.money("annual_rent_paid"),
        **{key: f.money(key) for key in DEDUCTIONS},
    }
    f.finish()
    return parsed


def calculate_pit(payload: dict[str, Any], tree: ParameterTree) -> CalculationResult:
    inputs = _parse(payload)
    view = ParameterView(tree, dt.date(inputs["tax_year"], 1, 1))
    regime = view.value("pit.regime")
    if regime == "nta2025":
        return _nta2025(inputs, view)
    if regime == "pita":
        return _pita(inputs, view)
    raise NotImplementedError(f"No PIT calculation for regime {regime!r}")


def _deductions(inputs: dict[str, Any], allowed: list[str], steps: list[Step], warnings: list[str]) -> Decimal:
    total = Decimal(0)
    for key, label in DEDUCTIONS.items():
        amount = inputs[key]
        if not amount:
            continue
        if key in allowed:
            steps.append(Step(f"Less: {label}", -amount))
            total += amount
        else:
            warnings.append(f"{label} is not deductible under this regime and was ignored.")
    return total


def _finish(
    *,
    regime: str,
    inputs: dict[str, Any],
    view: ParameterView,
    steps: list[Step],
    chargeable: Decimal,
    scale_name: str,
    extra_outputs: dict[str, Any],
    assumptions: list[str],
    warnings: list[str],
    minimum_tax: Decimal | None = None,
) -> CalculationResult:
    gross = inputs["annual_gross_income"]
    steps.append(Step("Chargeable income", chargeable))
    tax, bands = apply_scale(chargeable, view.scale(scale_name))
    steps.append(Step("Tax on chargeable income (see bands)", tax))

    minimum_applied = False
    if minimum_tax is not None and gross > 0 and tax < minimum_tax:
        steps.append(Step("Minimum tax applies (higher than computed tax)", minimum_tax))
        tax = minimum_tax
        minimum_applied = True
        warnings.append(
            "Minimum tax applied. Low-income exemptions under the old law are not modelled in this demo."
        )

    annual = money(tax)
    effective = (annual / gross * 100) if gross else Decimal(0)
    outputs = {
        **extra_outputs,
        "chargeable_income": money_str(chargeable),
        "annual_tax": money_str(annual),
        "monthly_tax": money_str(annual / 12),
        "effective_rate_percent": str(effective.quantize(Decimal("0.01"))),
        "income_after_tax": money_str(gross - annual),
        "minimum_tax_applied": minimum_applied,
    }
    steps.append(Step("Annual tax", annual))
    steps.append(Step("Monthly PAYE (annual ÷ 12)", money(annual / 12)))
    return CalculationResult(
        calculator="pit",
        regime=regime,
        period=f"Tax year {inputs['tax_year']}",
        inputs=inputs,
        outputs=outputs,
        steps=steps,
        view=view,
        bands=bands,
        assumptions=assumptions,
        warnings=warnings,
    )


def _nta2025(inputs: dict[str, Any], view: ParameterView) -> CalculationResult:
    gross = inputs["annual_gross_income"]
    steps = [Step("Gross annual income", gross)]
    warnings: list[str] = []
    deductions = _deductions(inputs, view.value("pit.nta2025.allowed_deductions"), steps, warnings)

    rent = inputs["annual_rent_paid"]
    relief = Decimal(0)
    if rent:
        rate = view.value("pit.nta2025.rent_relief.rate")
        cap = view.value("pit.nta2025.rent_relief.cap")
        relief = min(rent * rate, cap)
        note = f"{percent(rate)} of rent paid, capped at {naira(cap)}"
        steps.append(Step("Less: Rent relief", -relief, note))

    chargeable = max(Decimal(0), gross - deductions - relief)
    if gross - deductions - relief < 0:
        warnings.append("Deductions exceed income; chargeable income set to zero.")
    return _finish(
        regime="nta2025",
        inputs=inputs,
        view=view,
        steps=steps,
        chargeable=chargeable,
        scale_name="pit.nta2025.rates",
        extra_outputs={"rent_relief": money_str(relief), "total_deductions": money_str(deductions)},
        assumptions=[
            "Gross income is total annual employment and other personal income before deductions.",
            "Deductions are supported by documentary evidence.",
            "Income is from a single employment; benefits in kind are included in gross income.",
        ],
        warnings=warnings,
    )


def _pita(inputs: dict[str, Any], view: ParameterView) -> CalculationResult:
    gross = inputs["annual_gross_income"]
    steps = [Step("Gross annual income", gross)]
    warnings: list[str] = []
    deductions = _deductions(inputs, view.value("pit.pita.allowed_deductions"), steps, warnings)
    if inputs["annual_rent_paid"]:
        warnings.append("Rent relief did not exist before 2026; rent paid was ignored.")

    fixed = view.value("pit.pita.cra.fixed_minimum")
    floor_rate = view.value("pit.pita.cra.floor_rate")
    cra_rate = view.value("pit.pita.cra.rate")
    cra = max(fixed, gross * floor_rate) + gross * cra_rate
    steps.append(Step("Less: Consolidated relief allowance", -cra, "Higher of the fixed element or a share of gross, plus a further share of gross"))

    chargeable = max(Decimal(0), gross - deductions - cra)
    minimum = gross * view.value("pit.pita.minimum_tax.rate")
    return _finish(
        regime="pita",
        inputs=inputs,
        view=view,
        steps=steps,
        chargeable=chargeable,
        scale_name="pit.pita.rates",
        extra_outputs={"consolidated_relief_allowance": money_str(cra), "total_deductions": money_str(deductions)},
        assumptions=[
            "Consolidated relief allowance computed on gross income.",
            "Deductions are supported by documentary evidence.",
        ],
        warnings=warnings,
        minimum_tax=minimum,
    )


def compare_pit(payload: dict[str, Any], tree: ParameterTree) -> dict[str, Any]:
    """Same inputs under the last PITA year and the first NTA year (CALC-05)."""
    old = calculate_pit({**payload, "tax_year": 2025}, tree)
    new = calculate_pit({**payload, "tax_year": 2026}, tree)
    old_tax = Decimal(old.outputs["annual_tax"])
    new_tax = Decimal(new.outputs["annual_tax"])
    change = new_tax - old_tax
    return {
        "calculator": "pit-compare",
        "old": old.to_dict(),
        "new": new.to_dict(),
        "difference": {
            "annual_change": money_str(change),
            "monthly_change": money_str(change / 12),
            "direction": "lower" if change < 0 else "higher" if change > 0 else "same",
        },
    }
