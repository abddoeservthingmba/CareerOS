"""Currency conversion - `FOUND-03`.

`01-foundations.md` §3: "Cross-currency comparison goes through `shared/fx.py`,
which reads a daily-cached rate table and returns a `ConvertedMoney` carrying
the rate and its date, so a displayed comparison can be explained."

`AC-FOUND-03.5`: "`fx.convert()` returns the rate and its date alongside the
amount, and raises `RateUnavailable` rather than falling back to 1.0." A silent
1.0 would tell a user in Bengaluru that a $90,000 role pays below their
₹90,000 floor, which is the kind of wrong that looks right.

The rate *source* is not specified here. `RateTable` is a plain mapping the
caller supplies, so the daily fetch and its cache belong to whatever phase needs
live rates; the conversion itself is pure and testable with fixed numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.shared.enums import MoneyPeriod
from app.shared.money import MINOR_UNITS, Money


class RateUnavailable(LookupError):
    """No rate for this pair on this date. Never substituted with 1.0."""


@dataclass(frozen=True, slots=True)
class Rate:
    base: str
    quote: str
    value: Decimal
    as_of: date

    def __post_init__(self) -> None:
        if isinstance(self.value, float):
            raise TypeError("a rate is a Decimal, not a float")
        if self.value <= 0:
            raise ValueError(f"rate must be positive, got {self.value}")


@dataclass(frozen=True, slots=True)
class ConvertedMoney:
    """The result of a conversion, carrying its own provenance.

    `original` is kept so the UI can show "₹25,00,000 (about $30,120 at 83.0 on
    2026-09-05)" rather than an unexplained number.
    """

    amount: Money
    original: Money
    rate: Decimal
    as_of: date

    @property
    def explanation(self) -> str:
        return f"{self.original} ≈ {self.amount} at {self.rate} on {self.as_of.isoformat()}"


class RateTable:
    """A day's rates. Deliberately dumb: fetching and caching live elsewhere."""

    def __init__(self, rates: dict[tuple[str, str], Rate] | None = None) -> None:
        self._rates: dict[tuple[str, str], Rate] = dict(rates or {})

    def add(self, rate: Rate) -> None:
        self._rates[(rate.base, rate.quote)] = rate

    def get(self, base: str, quote: str) -> Rate:
        base, quote = base.upper(), quote.upper()
        if base == quote:
            raise RateUnavailable(f"{base} to {quote} needs no conversion")
        direct = self._rates.get((base, quote))
        if direct is not None:
            return direct
        inverse = self._rates.get((quote, base))
        if inverse is not None:
            return Rate(base, quote, Decimal(1) / inverse.value, inverse.as_of)
        raise RateUnavailable(f"no rate for {base} to {quote}")


def convert(money: Money, to: str, rates: RateTable) -> ConvertedMoney:
    """Convert `money` into `to`, carrying the rate and its date."""
    target = to.upper()
    if money.currency == target:
        raise RateUnavailable(
            f"{money.currency} is already the target currency; nothing to explain"
        )
    rate = rates.get(money.currency, target)

    source_exponent = MINOR_UNITS.get(money.currency, 2)
    target_exponent = MINOR_UNITS.get(target, 2)
    major = Decimal(money.amount) / (Decimal(10) ** source_exponent)
    converted_major = major * rate.value
    minor = (converted_major * (Decimal(10) ** target_exponent)).quantize(
        Decimal(1), rounding=ROUND_HALF_UP
    )
    return ConvertedMoney(
        amount=Money(int(minor), target, money.period),
        original=money,
        rate=rate.value,
        as_of=rate.as_of,
    )


def compare(left: Money, right: Money, rates: RateTable) -> tuple[int, ConvertedMoney | None]:
    """Compare two amounts, converting only when the currencies differ.

    Returns `(-1 | 0 | 1, conversion_used_or_None)`, so a caller that must show
    its working - the salary component of the match explain payload
    (`08-matching.md` §2) - has the rate to hand.
    """
    if left.period != right.period:
        raise ValueError(f"cannot compare {left.period} against {right.period}")
    if left.currency == right.currency:
        return ((left.amount > right.amount) - (left.amount < right.amount), None)
    converted = convert(right, left.currency, rates)
    other = converted.amount.amount
    return ((left.amount > other) - (left.amount < other), converted)


__all__ = [
    "ConvertedMoney",
    "MoneyPeriod",
    "Rate",
    "RateTable",
    "RateUnavailable",
    "compare",
    "convert",
]
