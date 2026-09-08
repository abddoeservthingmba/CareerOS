"""Money - `FOUND-03`.

`01-foundations.md` §3: "`Money{amount: int, currency: ISO4217, period:
"hour"|"month"|"year"}`. `amount` is a **minor-unit integer** (paise, cents) -
never a float, anywhere, ever. Cross-currency comparison goes through
`shared/fx.py` ... so a displayed comparison can be explained."

The float ban is enforced at construction rather than documented, because the
failure it prevents is silent: a salary that drifts by a paise per arithmetic
operation is still a plausible-looking salary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.shared.enums import MoneyPeriod

# ISO 4217 minor-unit exponents for the currencies the product handles. Most are
# 2; the exceptions matter because "100" means different amounts in each.
MINOR_UNITS: dict[str, int] = {
    "INR": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "AUD": 2,
    "CAD": 2,
    "SGD": 2,
    "AED": 2,
    "CHF": 2,
    "NZD": 2,
    "ZAR": 2,
    "SEK": 2,
    "JPY": 0,
    "KRW": 0,
    "BHD": 3,
    "KWD": 3,
}


class CurrencyMismatch(ValueError):
    """Two amounts in different currencies met without going through `fx`."""


class FloatAmountError(TypeError):
    """A float reached a money amount.

    Separate from `TypeError` so the ban is greppable and so the message can say
    why: minor units are exact, floats are not, and a cover letter quoting a
    salary of 2499999.9999 is a bug the user sends to an employer.
    """


@dataclass(frozen=True, slots=True)
class Money:
    """An exact amount in a currency's minor unit."""

    amount: int
    currency: str
    period: MoneyPeriod | None = None

    def __post_init__(self) -> None:
        if isinstance(self.amount, bool) or not isinstance(self.amount, int):
            raise FloatAmountError(
                f"Money.amount must be a minor-unit integer, got "
                f"{type(self.amount).__name__} {self.amount!r}"
            )
        currency = self.currency.upper() if isinstance(self.currency, str) else self.currency
        if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
            raise ValueError(f"currency must be an ISO 4217 alphabetic code, got {self.currency!r}")
        object.__setattr__(self, "currency", currency)
        if self.period is not None:
            object.__setattr__(self, "period", MoneyPeriod(self.period))

    # -- arithmetic, within one currency only --------------------------------

    def _compatible(self, other: Money) -> None:
        if not isinstance(other, Money):
            raise TypeError(f"cannot combine Money with {type(other).__name__}")
        if other.currency != self.currency:
            raise CurrencyMismatch(
                f"{self.currency} and {other.currency} differ; convert through "
                "shared.fx so the rate and its date can be shown"
            )
        if other.period != self.period:
            raise CurrencyMismatch(f"periods differ: {self.period} and {other.period}")

    def __add__(self, other: Money) -> Money:
        self._compatible(other)
        return Money(self.amount + other.amount, self.currency, self.period)

    def __sub__(self, other: Money) -> Money:
        self._compatible(other)
        return Money(self.amount - other.amount, self.currency, self.period)

    def __lt__(self, other: Money) -> bool:
        self._compatible(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._compatible(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._compatible(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._compatible(other)
        return self.amount >= other.amount

    # -- presentation --------------------------------------------------------

    @property
    def minor_units(self) -> int:
        return MINOR_UNITS.get(self.currency, 2)

    @property
    def major(self) -> str:
        """The amount as a decimal string, for display only - never for maths."""
        exponent = self.minor_units
        if exponent == 0:
            return str(self.amount)
        sign = "-" if self.amount < 0 else ""
        digits = str(abs(self.amount)).rjust(exponent + 1, "0")
        return f"{sign}{digits[:-exponent]}.{digits[-exponent:]}"

    @classmethod
    def from_major(
        cls, value: str | int, currency: str, period: MoneyPeriod | None = None
    ) -> Money:
        """Build from a major-unit decimal *string*, exactly.

        Takes a string rather than a float on purpose: `from_major(0.1, "USD")`
        would be the very rounding error this type exists to prevent.
        """
        if isinstance(value, float):
            raise FloatAmountError("from_major takes a decimal string, not a float")
        exponent = MINOR_UNITS.get(currency.upper(), 2)
        text = str(value).strip()
        negative = text.startswith("-")
        text = text.lstrip("+-")
        whole, _, fraction = text.partition(".")
        if not whole.isdigit() or (fraction and not fraction.isdigit()):
            raise ValueError(f"{value!r} is not a decimal amount")
        if len(fraction) > exponent:
            raise ValueError(
                f"{value!r} has more precision than {currency.upper()}'s {exponent} minor digits"
            )
        amount = int(whole) * (10**exponent) + int(fraction.ljust(exponent, "0") or 0)
        return cls(-amount if negative else amount, currency, period)

    def __str__(self) -> str:
        suffix = f"/{self.period}" if self.period else ""
        return f"{self.currency} {self.major}{suffix}"

    def __hash__(self) -> int:
        return hash((self.amount, self.currency, self.period))

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return (
            self.amount == other.amount
            and self.currency == other.currency
            and self.period == other.period
        )
