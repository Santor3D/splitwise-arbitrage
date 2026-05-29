from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value: Decimal | int | str | float) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def is_zero(value: Decimal, min_amount: Decimal = CENT) -> bool:
    return abs(money(value)) < min_amount


def fmt(value: Decimal) -> str:
    return f"{money(value):.2f}"


def split_signed_amount(value: Decimal, aliases: Iterable[str]) -> dict[str, Decimal]:
    names = list(aliases)
    if not names:
        raise ValueError("Cannot split an amount without aliases.")

    rounded = money(value)
    sign = Decimal("1") if rounded >= 0 else Decimal("-1")
    cents = int(abs(rounded) * 100)
    base = cents // len(names)
    remainder = cents % len(names)

    result: dict[str, Decimal] = {}
    for index, alias in enumerate(names):
        alias_cents = base + (1 if index < remainder else 0)
        result[alias] = money(sign * Decimal(alias_cents) / Decimal(100))

    return result
