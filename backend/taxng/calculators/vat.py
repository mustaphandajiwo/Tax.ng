"""Value added tax (CALC-03)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from ..format import percent
from ..rules import ParameterTree, ParameterView
from .common import CalculationResult, Fields, Step, money, money_str, rate_str

CATEGORIES = ["standard", "zero_rated", "exempt"]


def calculate_vat(payload: dict[str, Any], tree: ParameterTree, *, today: dt.date | None = None) -> CalculationResult:
    f = Fields(payload)
    inputs: dict[str, Any] = {
        "supply_date": f.date("supply_date", default=today or dt.date.today()),
        "amount": f.money("amount", required=True),
        "category": f.choice("category", CATEGORIES, default="standard"),
        "amount_includes_vat": f.flag("amount_includes_vat"),
    }
    f.finish()

    view = ParameterView(tree, inputs["supply_date"])
    amount, category = inputs["amount"], inputs["category"]
    warnings: list[str] = []
    notes = {
        "standard": "Standard-rated supply",
        "zero_rated": "Zero-rated: VAT at zero; input VAT is generally recoverable",
        "exempt": "Exempt: outside VAT; input VAT is generally not recoverable",
    }

    if category == "standard":
        rate = view.value("vat.standard_rate")
    else:
        rate = Decimal(0)
        examples = view.value("vat.zero_rated_examples" if category == "zero_rated" else "vat.exempt_examples")
        warnings.append("Check the supply is on the prescribed list: " + "; ".join(examples) + ".")

    if inputs["amount_includes_vat"]:
        net = amount / (1 + rate)
        vat = amount - net
    else:
        net = amount
        vat = amount * rate

    steps = [
        Step("Category", None, notes[category]),
        Step("Net amount (excluding VAT)", net),
        Step(f"VAT at {percent(rate)}", vat),
        Step("Gross amount (including VAT)", net + vat),
    ]
    return CalculationResult(
        calculator="vat",
        regime="nta2025" if inputs["supply_date"] >= dt.date(2026, 1, 1) else "vat_act",
        period=f"Supply on {inputs['supply_date'].isoformat()}",
        inputs=inputs,
        outputs={
            "rate": rate_str(rate),
            "net_amount": money_str(net),
            "vat": money_str(vat),
            "gross_amount": money_str(money(net) + money(vat)),
        },
        steps=steps,
        view=view,
        assumptions=["The supplier is registered for VAT and the supply takes place in Nigeria."],
        warnings=warnings,
    )
