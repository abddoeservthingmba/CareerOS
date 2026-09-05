"""T-FOUND-03.5 - currency conversion (`01-foundations.md` §3)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.shared.enums import MoneyPeriod
from app.shared.fx import Rate, RateTable, RateUnavailable, compare, convert
from app.shared.money import Money

AS_OF = date(2026, 9, 5)


@pytest.fixture
def rates() -> RateTable:
    return RateTable({("USD", "INR"): Rate("USD", "INR", Decimal("83.00"), AS_OF)})


def test_convert_returns_the_rate_and_its_date(rates):
    """AC-FOUND-03.5 - "returns the rate and its date alongside the amount"."""
    salary = Money.from_major("90000", "USD", MoneyPeriod.YEAR)
    result = convert(salary, "INR", rates)

    assert result.rate == Decimal("83.00")
    assert result.as_of == AS_OF
    assert result.original == salary
    assert result.amount.currency == "INR"
    assert result.amount.period is MoneyPeriod.YEAR
    assert result.amount.major == "7470000.00"
    assert "83.00" in result.explanation and "2026-09-05" in result.explanation


def test_missing_rate_raises_rather_than_falling_back_to_one(rates):
    """AC-FOUND-03.5 - "raises `RateUnavailable` rather than falling back to 1.0"."""
    salary = Money.from_major("50000", "EUR", MoneyPeriod.YEAR)
    with pytest.raises(RateUnavailable):
        convert(salary, "INR", rates)


def test_the_inverse_rate_is_derived_not_invented(rates):
    result = convert(Money.from_major("8300", "INR"), "USD", rates)
    assert result.amount.major == "100.00"
    assert result.as_of == AS_OF


def test_converting_to_the_same_currency_is_refused(rates):
    with pytest.raises(RateUnavailable):
        convert(Money(100, "INR"), "INR", rates)


def test_a_rate_may_not_be_a_float():
    with pytest.raises(TypeError):
        Rate("USD", "INR", 83.0, AS_OF)  # type: ignore[arg-type]


def test_a_rate_must_be_positive():
    with pytest.raises(ValueError, match="positive"):
        Rate("USD", "INR", Decimal("0"), AS_OF)


def test_compare_within_one_currency_needs_no_rate(rates):
    verdict, conversion = compare(
        Money.from_major("100", "INR"), Money.from_major("90", "INR"), rates
    )
    assert verdict == 1
    assert conversion is None


def test_compare_across_currencies_shows_its_working(rates):
    """`08-matching.md` §2 - the salary component records the rate and its date."""
    floor = Money.from_major("9000000", "INR", MoneyPeriod.YEAR)
    offered = Money.from_major("90000", "USD", MoneyPeriod.YEAR)
    verdict, conversion = compare(floor, offered, rates)

    assert verdict == 1, "₹90,00,000 is above $90,000 at 83.00"
    assert conversion is not None
    assert conversion.rate == Decimal("83.00")
    assert conversion.as_of == AS_OF


def test_compare_refuses_mismatched_periods(rates):
    with pytest.raises(ValueError, match="compare"):
        compare(
            Money(100, "INR", MoneyPeriod.YEAR),
            Money(100, "INR", MoneyPeriod.MONTH),
            rates,
        )


def test_rounding_is_half_up(rates):
    table = RateTable({("USD", "INR"): Rate("USD", "INR", Decimal("1.005"), AS_OF)})
    # 1.00 USD -> 1.005 INR -> 100.5 minor units -> 101, not 100.
    assert convert(Money.from_major("1", "USD"), "INR", table).amount.amount == 101
