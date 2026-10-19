"""Capital gains (CALC-06) under the Nigeria Tax Act 2025.

Companies pay tax on chargeable gains at the prevailing companies income tax
rate. The rate is not repeated here or in ``cgt.yaml``: the parameter
``cgt.company.rate_parameter`` names the CIT parameter to read, so CIT and CGT
always agree. Individuals' gains are added to chargeable income and taxed on the
PIT scale (``cgt.individual.scale_parameter``); that treatment is unverified.

Exemptions modelled:

* direct share disposals where proceeds and gains in any twelve-month window are
  within ``cgt.share_exemption.*`` (secondary source, PwC);
* personal chattels disposed of by an individual for no more than the higher of
  a fixed amount and a multiple of the annual national minimum wage;
* small companies, where ``cgt.company.small_company_rate_applies`` is true
  (unverified, so the result always carries a warning).

No rate, ceiling or threshold appears in this module (CALC-07).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from collections.abc import Callable
from typing import Any

from ..format import naira, percent
from ..rules import ParameterError, ParameterTree, ParameterView, apply_scale
from .common import CalculationResult, Fields, InputError, Step, money, money_str, rate_str

TAXPAYER_TYPES = ["company", "individual"]
ASSET_TYPES = ["shares", "chattel", "land_buildings", "other"]
MONTHS_PER_YEAR = 12  # calendar fact used to annualise a monthly wage, not a tax figure

Finish = Callable[[Decimal, str, dict[str, Any]], CalculationResult]


def _parse(payload: dict[str, Any], today: dt.date) -> dict[str, Any]:
    f = Fields(payload)
    taxpayer = f.choice("taxpayer_type", TAXPAYER_TYPES)
    inputs: dict[str, Any] = {
        "taxpayer_type": taxpayer,
        "disposal_date": f.date("disposal_date", default=today),
        "asset_type": f.choice("asset_type", ASSET_TYPES, default="other"),
        "proceeds": f.money("proceeds", required=True),
        "cost": f.money("cost"),
        "allowable_expenses": f.money("allowable_expenses"),
        # Earlier share disposals in the same twelve-month window (share exemption test).
        "prior_share_proceeds_12m": f.money("prior_share_proceeds_12m"),
        "prior_share_gains_12m": f.money("prior_share_gains_12m"),
    }
    if "taxpayer_type" in f.errors:
        pass
    elif taxpayer == "company":
        inputs["annual_turnover"] = f.money("annual_turnover", required=True)
        inputs["fixed_assets"] = f.money("fixed_assets")
        inputs["professional_services"] = f.flag("professional_services")
    else:
        inputs["other_chargeable_income"] = f.money("other_chargeable_income")
    f.finish()
    return inputs


def is_small_company(view: ParameterView, turnover: Decimal, fixed_assets: Decimal, professional: bool) -> bool:
    """The CIT small company test (same parameters as ``calculators.cit``)."""
    excludes_prof = view.value("cit.small_company.excludes_professional_services")
    return (
        turnover <= view.value("cit.small_company.turnover_ceiling")
        and fixed_assets <= view.value("cit.small_company.fixed_assets_ceiling")
        and not (excludes_prof and professional)
    )


def calculate_cgt(payload: dict[str, Any], tree: ParameterTree, *, today: dt.date | None = None) -> CalculationResult:
    inputs = _parse(payload, today or dt.date.today())
    view = ParameterView(tree, inputs["disposal_date"])
    try:
        view.value("cgt.company.rate_parameter")
    except ParameterError:
        raise InputError(
            {"disposal_date": "no capital gains rules are in force on this date; the calculator covers the Nigeria Tax Act 2025"}
        ) from None

    steps = [
        Step("Disposal proceeds", inputs["proceeds"]),
        Step("Less: cost of acquisition", -inputs["cost"]),
        Step("Less: allowable expenses of acquisition and disposal", -inputs["allowable_expenses"]),
    ]
    gain = inputs["proceeds"] - inputs["cost"] - inputs["allowable_expenses"]
    steps.append(Step("Chargeable gain" if gain >= 0 else "Capital loss", gain))
    assumptions = [
        "Cost and expenses are supported by documentary evidence and were not deducted elsewhere.",
        "The asset is a chargeable asset located in Nigeria or disposed of by a Nigerian resident.",
    ]
    warnings: list[str] = []
    outputs: dict[str, Any] = {"taxpayer_type": inputs["taxpayer_type"], "chargeable_gain": money_str(max(gain, Decimal(0)))}

    def finish(cgt: Decimal, exemption: str, extra: dict[str, Any]) -> CalculationResult:
        steps.append(Step("Tax on chargeable gain", money(cgt)))
        return CalculationResult(
            calculator="cgt",
            regime="nta2025",
            period=f"Disposal on {inputs['disposal_date'].isoformat()}",
            inputs=inputs,
            outputs={**outputs, **extra, "exempt": exemption != "none", "exemption": exemption, "cgt": money_str(cgt)},
            steps=steps,
            view=view,
            assumptions=assumptions,
            warnings=warnings,
        )

    if gain <= 0:
        warnings.append("No gain arises. Relief for capital losses is not modelled in this demo.")
        return finish(Decimal(0), "none", {})

    exemption = _exemption(inputs, gain, view, steps, assumptions)
    if exemption != "none":
        return finish(Decimal(0), exemption, {})

    if inputs["taxpayer_type"] == "company":
        return _company(inputs, gain, view, steps, warnings, finish)
    return _individual(inputs, gain, view, steps, warnings, finish)


def _exemption(inputs: dict[str, Any], gain: Decimal, view: ParameterView, steps: list[Step], assumptions: list[str]) -> str:
    if inputs["asset_type"] == "shares":
        proceeds_cap = view.value("cgt.share_exemption.proceeds_ceiling")
        gain_cap = view.value("cgt.share_exemption.gain_ceiling")
        window = view.value("cgt.share_exemption.window_months")
        total_proceeds = inputs["proceeds"] + inputs["prior_share_proceeds_12m"]
        total_gains = gain + inputs["prior_share_gains_12m"]
        assumptions.append(
            f"Earlier share disposals in the same {window}-month window are included in the figures entered for them."
        )
        within = total_proceeds <= proceeds_cap and total_gains <= gain_cap
        steps.append(
            Step(
                "Share disposal exemption test",
                None,
                f"Proceeds in the window {naira(money(total_proceeds))} (limit {naira(proceeds_cap)}); "
                f"gains {naira(money(total_gains))} (limit {naira(gain_cap)}): {'exempt' if within else 'not exempt'}",
            )
        )
        if within:
            return "share_disposal"
    if inputs["asset_type"] == "chattel" and inputs["taxpayer_type"] == "individual":
        fixed = view.value("cgt.individual.chattel_exemption.fixed_ceiling")
        multiple = view.value("cgt.individual.chattel_exemption.minimum_wage_multiple")
        wage = view.value("cgt.individual.chattel_exemption.national_minimum_wage_monthly")
        ceiling = max(fixed, multiple * wage * MONTHS_PER_YEAR)
        within = inputs["proceeds"] <= ceiling
        steps.append(
            Step(
                "Personal chattels exemption test",
                None,
                f"Disposal value against the higher of {naira(fixed)} or {multiple} times the annual national minimum wage "
                f"({naira(ceiling)}): {'exempt' if within else 'not exempt'}",
            )
        )
        if within:
            return "personal_chattel"
    return "none"


def _company(
    inputs: dict[str, Any], gain: Decimal, view: ParameterView, steps: list[Step], warnings: list[str], finish: Finish
) -> CalculationResult:
    small = is_small_company(view, inputs["annual_turnover"], inputs["fixed_assets"], inputs["professional_services"])
    steps.append(
        Step("Small company test", None, "Meets both ceilings: small company" if small else "Exceeds a ceiling or excluded: not a small company")
    )
    if small and view.value("cgt.company.small_company_rate_applies"):
        rate = view.value(view.value("cgt.company.small_rate_parameter"))
        warnings.append(
            "Whether the small company exemption extends to chargeable gains is not confirmed. "
            "The small company rate has been applied pending legal review."
        )
    else:
        rate = view.value(view.value("cgt.company.rate_parameter"))
        if small:
            warnings.append("Small company relief has not been applied to gains under the current rule setting.")
    cgt = gain * rate
    steps.append(Step(f"Chargeable gain taxed at the CIT rate of {percent(rate)}", cgt))
    return finish(cgt, "none", {"is_small_company": small, "rate": rate_str(rate)})


def _individual(
    inputs: dict[str, Any], gain: Decimal, view: ParameterView, steps: list[Step], warnings: list[str], finish: Finish
) -> CalculationResult:
    scale = view.scale(view.value("cgt.individual.scale_parameter"))
    other = inputs["other_chargeable_income"]
    without_gain, _ = apply_scale(other, scale)
    with_gain, _ = apply_scale(other + gain, scale)
    steps.append(Step("Tax on other chargeable income alone", without_gain))
    steps.append(Step("Tax on other chargeable income plus the gain", with_gain))
    cgt = with_gain - without_gain
    warnings.append(
        "Taxing an individual's gain by adding it to chargeable income at personal income tax rates is not yet confirmed. "
        "Treat this result as indicative."
    )
    if inputs["asset_type"] == "land_buildings":
        warnings.append("Reliefs for a principal private residence are not modelled in this demo.")
    return finish(
        cgt,
        "none",
        {"tax_without_gain": money_str(without_gain), "tax_with_gain": money_str(with_gain)},
    )
