"""T-FOUND-03.4 - Money (`01-foundations.md` §3).

Also shared with `T-TRACK-03.8`, which asserts money round-trips through the API
with no floating-point drift.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.shared.enums import MoneyPeriod
from app.shared.money import CurrencyMismatch, FloatAmountError, Money


def test_rejects_float_construction():
    """AC-FOUND-03.4 - "`Money` rejects float construction"."""
    with pytest.raises(FloatAmountError):
        Money(1000.0, "INR", MoneyPeriod.YEAR)  # type: ignore[arg-type]
    with pytest.raises(FloatAmountError):
        Money(0.1, "USD")  # type: ignore[arg-type]
    # A bool is an int in Python, and is not an amount.
    with pytest.raises(FloatAmountError):
        Money(True, "USD")


def test_rejects_a_float_through_from_major():
    with pytest.raises(FloatAmountError):
        Money.from_major(0.1, "USD")  # type: ignore[arg-type]


def test_cross_currency_addition_raises_rather_than_converting():
    """AC-FOUND-03.4 - "raises `CurrencyMismatch` rather than converting implicitly"."""
    inr = Money(1000, "INR", MoneyPeriod.YEAR)
    usd = Money(1000, "USD", MoneyPeriod.YEAR)
    with pytest.raises(CurrencyMismatch):
        _ = inr + usd
    with pytest.raises(CurrencyMismatch):
        _ = inr < usd


def test_mismatched_periods_do_not_combine():
    with pytest.raises(CurrencyMismatch):
        _ = Money(100, "INR", MoneyPeriod.YEAR) + Money(100, "INR", MoneyPeriod.MONTH)


def test_currency_must_be_iso4217_alphabetic():
    with pytest.raises(ValueError, match="ISO 4217"):
        Money(100, "RUPEES")
    with pytest.raises(ValueError, match="ISO 4217"):
        Money(100, "12")
    assert Money(100, "inr").currency == "INR"


def test_minor_units_are_exact():
    # ₹25,00,000 per year, the salary in `17-data-model.md` §2.6's example job.
    salary = Money.from_major("2500000", "INR", MoneyPeriod.YEAR)
    assert salary.amount == 250_000_000
    assert salary.major == "2500000.00"
    assert str(salary) == "INR 2500000.00/year"


def test_zero_decimal_currencies():
    """JPY has no minor unit; 100 means 100 yen, not one yen."""
    yen = Money.from_major("100", "JPY")
    assert yen.amount == 100
    assert yen.major == "100"


def test_three_decimal_currencies():
    dinar = Money.from_major("1.500", "KWD")
    assert dinar.amount == 1500
    assert dinar.major == "1.500"


def test_more_precision_than_the_currency_has_is_refused():
    with pytest.raises(ValueError, match="precision"):
        Money.from_major("1.999", "USD")


@given(
    amounts=st.lists(st.integers(min_value=-(10**12), max_value=10**12), min_size=3, max_size=3),
)
def test_addition_is_associative_within_a_currency(amounts):
    """AC-FOUND-03.4 - hypothesis: no float path, associativity within a currency."""
    a, b, c = (Money(v, "INR", MoneyPeriod.YEAR) for v in amounts)
    assert (a + b) + c == a + (b + c)


@given(amount=st.integers(min_value=-(10**12), max_value=10**12))
def test_major_round_trips(amount):
    """No drift: minor -> major string -> minor is the identity."""
    money = Money(amount, "USD")
    assert Money.from_major(money.major, "USD").amount == amount


@given(amount=st.integers(min_value=0, max_value=10**12))
def test_no_float_appears_anywhere_in_arithmetic(amount):
    money = Money(amount, "INR", MoneyPeriod.YEAR)
    doubled = money + money
    assert isinstance(doubled.amount, int)
    assert doubled.amount == amount * 2


def test_equality_and_hashing_account_for_currency_and_period():
    assert Money(100, "INR") != Money(100, "USD")
    assert Money(100, "INR", MoneyPeriod.YEAR) != Money(100, "INR", MoneyPeriod.MONTH)
    assert Money(100, "INR") == Money(100, "INR")
    assert len({Money(100, "INR"), Money(100, "INR")}) == 1
