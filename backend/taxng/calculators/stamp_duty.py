"""Stamp duties (CALC-06) under the Nigeria Tax Act 2025.

Two instruments are modelled:

* ``electronic_transfer``: the flat electronic money transfer levy on an
  electronic receipt or transfer at or above ``stamp_duty.electronic_transfer.threshold``.
  Transfers between the same owner's accounts in the same bank are exempt when
  ``stamp_duty.electronic_transfer.own_account_exempt`` is true.
* ``share_capital``: ad valorem duty on authorised share capital at
  incorporation or on an increase.

Every figure comes from ``rules/parameters/stamp_duty.yaml`` (CALC-07).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from ..format import naira, percent
from ..rules import ParameterError, ParameterTree, ParameterView
from .common import CalculationResult, Fields, InputError, Step, money_str, rate_str

INSTRUMENTS = ["electronic_transfer", "share_capital"]


def calculate_stamp_duty(payload: dict[str, Any], tree: ParameterTree, *, today: dt.date | None = None) -> CalculationResult:
    f = Fields(payload)
    inputs: dict[str, Any] = {
        "instrument": f.choice("instrument", INSTRUMENTS),
        "transaction_date": f.date("transaction_date", default=today or dt.date.today()),
        "amount": f.money("amount", required=True),
        "own_account": f.flag("own_account"),
    }
    f.finish()
    view = ParameterView(tree, inputs["transaction_date"])
    try:
        if inputs["instrument"] == "electronic_transfer":
            return _electronic_transfer(inputs, view)
        return _share_capital(inputs, view)
    except ParameterError:
        raise InputError(
            {"transaction_date": "no stamp duty rules are in force on this date; the calculator covers the Nigeria Tax Act 2025"}
        ) from None


def _result(inputs: dict[str, Any], view: ParameterView, steps: list[Step], outputs: dict[str, Any], assumptions: list[str], warnings: list[str]) -> CalculationResult:
    return CalculationResult(
        calculator="stamp-duty",
        regime="nta2025",
        period=f"Transaction on {inputs['transaction_date'].isoformat()}",
        inputs=inputs,
        outputs=outputs,
        steps=steps,
        view=view,
        assumptions=assumptions,
        warnings=warnings,
    )


def _electronic_transfer(inputs: dict[str, Any], view: ParameterView) -> CalculationResult:
    threshold = view.value("stamp_duty.electronic_transfer.threshold")
    levy = view.value("stamp_duty.electronic_transfer.levy")
    own_exempt = view.value("stamp_duty.electronic_transfer.own_account_exempt")
    amount = inputs["amount"]
    steps = [Step("Amount received or transferred", amount)]
    if inputs["own_account"] and own_exempt:
        duty, exemption = Decimal(0), "own_account"
        steps.append(Step("Transfer between your own accounts in the same bank", None, "Exempt"))
    elif amount < threshold:
        duty, exemption = Decimal(0), "below_threshold"
        steps.append(Step("Below the levy threshold", None, f"The levy applies from {naira(threshold)}"))
    else:
        duty, exemption = levy, "none"
        steps.append(Step("Flat electronic money transfer levy", levy, f"Applies to each receipt or transfer of {naira(threshold)} or more"))
    return _result(
        inputs,
        view,
        steps,
        {"duty": money_str(duty), "exempt": exemption != "none", "exemption": exemption},
        [
            "The levy is charged once per qualifying electronic receipt or transfer and is collected by the bank.",
            "Own-account means accounts held by the same owner in the same bank.",
        ],
        [],
    )


def _share_capital(inputs: dict[str, Any], view: ParameterView) -> CalculationResult:
    rate = view.value("stamp_duty.share_capital.rate")
    days = view.value("stamp_duty.stamping_deadline_days")
    duty = inputs["amount"] * rate
    steps = [
        Step("Authorised share capital (or the increase)", inputs["amount"]),
        Step(f"Duty at {percent(rate)}", duty),
    ]
    return _result(
        inputs,
        view,
        steps,
        {"duty": money_str(duty), "rate": rate_str(rate), "exempt": False, "exemption": "none"},
        ["The amount is the authorised share capital at incorporation, or the amount of the increase for new shares."],
        [f"Dutiable instruments should be stamped within {days} days of execution. This deadline is pending legal review."],
    )
