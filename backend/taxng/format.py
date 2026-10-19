"""Human formatting for figures. Shared by the Tax AI composer and its guard."""

from __future__ import annotations

from decimal import Decimal


def naira(value: Decimal) -> str:
    value = Decimal(value)
    if value == value.to_integral_value():
        return f"₦{int(value):,}"
    return f"₦{value:,.2f}"


def percent(rate: Decimal) -> str:
    """0.075 -> '7.5%'."""
    pct = (Decimal(rate) * 100).normalize()
    text = format(pct, "f")
    return f"{text}%"
