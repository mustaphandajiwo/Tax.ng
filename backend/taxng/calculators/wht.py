"""Withholding tax on payments to residents (CALC-04)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from ..format import naira, percent
from ..rules import ParameterTree, ParameterView
from .common import CalculationResult, Fields, InputError, Step, money, money_str, rate_str

RECIPIENTS = ["corporate", "non_corporate"]


def payment_types(tree: ParameterTree) -> list[str]:
    """Payment types are discovered from the parameter tree, not hard-coded."""
    types = {name.split(".")[2] for name in tree.names("wht.rates.")}
    return sorted(types)


def calculate_wht(payload: dict[str, Any], tree: ParameterTree, *, today: dt.date | None = None) -> CalculationResult:
    f = Fields(payload)
    inputs: dict[str, Any] = {
        "payment_date": f.date("payment_date", default=today or dt.date.today()),
        "payment_type": f.choice("payment_type", payment_types(tree)),
        "recipient_type": f.choice("recipient_type", RECIPIENTS, default="corporate"),
        "amount": f.money("amount", required=True),
        "recipient_has_tin": f.flag("recipient_has_tin", default=True),
        "payer_is_small_company": f.flag("payer_is_small_company"),
    }
    f.finish()

    rate_name = f"wht.rates.{inputs['payment_type']}.{inputs['recipient_type']}"
    if not tree.has(rate_name):
        raise InputError({"recipient_type": "this payment type does not apply to that recipient type"})

    view = ParameterView(tree, inputs["payment_date"])
    amount = inputs["amount"]
    warnings: list[str] = []
    base_rate = view.value(rate_name)
    steps = [
        Step("Payment amount", amount),
        Step(f"Prescribed rate: {percent(base_rate)}", None, tree.info(rate_name).description),
    ]

    ceiling = view.value("wht.small_company_exemption.transaction_ceiling")
    exempt = inputs["payer_is_small_company"] and inputs["recipient_has_tin"] and amount < ceiling
    rate = base_rate
    if exempt:
        rate = Decimal(0)
        steps.append(Step("Small company exemption applies", None, f"Payer is small, recipient has a TIN, amount below {naira(ceiling)}"))
    elif not inputs["recipient_has_tin"]:
        passive = view.value("wht.passive_types")
        if inputs["payment_type"] in passive:
            steps.append(Step("Recipient has no TIN", None, "Surcharge does not apply to passive income"))
        else:
            multiplier = view.value("wht.no_tin.multiplier")
            cap = view.value("wht.no_tin.cap")
            rate = min(base_rate * multiplier, cap)
            steps.append(Step(f"Recipient has no TIN: rate becomes {percent(rate)}", None, f"Rate × {rate_str(multiplier)}, capped at {percent(cap)}"))
            warnings.append("Ask the recipient for a TIN before payment to avoid the higher rate.")

    wht = amount * rate
    steps.append(Step("Withholding tax to deduct and remit", wht))
    steps.append(Step("Net payment to recipient", amount - money(wht)))
    warnings.append("Remittance is due by the 21st day of the month after payment (pending legal review).")
    return CalculationResult(
        calculator="wht",
        regime="wht_regulations",
        period=f"Payment on {inputs['payment_date'].isoformat()}",
        inputs=inputs,
        outputs={
            "rate": rate_str(rate),
            "exempt": exempt,
            "wht": money_str(wht),
            "net_payment": money_str(amount - money(wht)),
        },
        steps=steps,
        view=view,
        assumptions=["The recipient is resident in Nigeria.", "The payment is not covered by a specific exemption."],
        warnings=warnings,
    )
