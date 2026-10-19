"""Companies income tax and development levy (CALC-02)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from ..format import percent
from ..rules import ParameterTree, ParameterView
from .common import CalculationResult, Fields, InputError, Step, money, money_str, rate_str


def calculate_cit(payload: dict[str, Any], tree: ParameterTree) -> CalculationResult:
    f = Fields(payload)
    inputs: dict[str, Any] = {
        "tax_year": f.year("tax_year", default=2026),
        "annual_turnover": f.money("annual_turnover", required=True),
        "fixed_assets": f.money("fixed_assets"),
        "total_profits": f.money("total_profits", required=True),
        "assessable_profits": f.money("assessable_profits"),
        "professional_services": f.flag("professional_services"),
        "non_resident": f.flag("non_resident"),
    }
    f.finish()
    if inputs["tax_year"] < 2026:
        raise InputError({"tax_year": "this demo covers CIT under the Nigeria Tax Act 2025 (2026 onwards) only"})

    view = ParameterView(tree, dt.date(inputs["tax_year"], 1, 1))
    assumptions = ["Total profits are after capital allowances and loss relief."]
    warnings: list[str] = []

    turnover_cap = view.value("cit.small_company.turnover_ceiling")
    assets_cap = view.value("cit.small_company.fixed_assets_ceiling")
    excludes_prof = view.value("cit.small_company.excludes_professional_services")
    is_small = (
        inputs["annual_turnover"] <= turnover_cap
        and inputs["fixed_assets"] <= assets_cap
        and not (excludes_prof and inputs["professional_services"])
    )
    if excludes_prof and inputs["professional_services"] and inputs["annual_turnover"] <= turnover_cap:
        warnings.append("Professional services firms are treated as not small. This rule is pending legal review.")

    levy_base = inputs["assessable_profits"]
    if not levy_base:
        levy_base = inputs["total_profits"]
        assumptions.append("Assessable profits (levy base) not given; total profits used instead.")

    steps = [
        Step("Annual turnover", inputs["annual_turnover"]),
        Step("Total fixed assets", inputs["fixed_assets"]),
        Step(
            "Small company test",
            None,
            "Meets both ceilings: small company" if is_small else "Exceeds a ceiling or excluded: not a small company",
        ),
    ]

    rate = view.value("cit.rate.small" if is_small else "cit.rate.other")
    cit = inputs["total_profits"] * rate
    steps.append(Step(f"Companies income tax at {percent(rate)} of total profits", cit))

    levy = Decimal(0)
    if is_small or inputs["non_resident"]:
        steps.append(Step("Development levy", Decimal(0), "Not payable by small or non-resident companies"))
    else:
        levy_rate = view.value("cit.development_levy.rate")
        levy = levy_base * levy_rate
        steps.append(Step(f"Development levy at {percent(levy_rate)} of assessable profits", levy))

    if inputs["annual_turnover"] >= view.value("cit.minimum_etr.turnover_threshold"):
        warnings.append("Minimum effective tax rate rules may apply. They are not computed in this demo.")

    total = money(cit) + money(levy)
    steps.append(Step("Total", total))
    return CalculationResult(
        calculator="cit",
        regime="nta2025",
        period=f"Tax year {inputs['tax_year']}",
        inputs=inputs,
        outputs={
            "is_small_company": is_small,
            "cit_rate": rate_str(rate),
            "cit": money_str(cit),
            "development_levy": money_str(levy),
            "total_tax": money_str(total),
        },
        steps=steps,
        view=view,
        assumptions=assumptions,
        warnings=warnings,
    )
