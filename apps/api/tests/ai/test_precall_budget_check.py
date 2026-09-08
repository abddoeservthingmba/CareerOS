"""T-AI-03.2 - the provider is never contacted for a call that will be denied.

`AC-AI-03.2`: "A call whose **estimate** would cross a cap is refused before the
provider is contacted, asserted by the fake provider recording zero
invocations."

The criterion names its own evidence: *zero invocations*. That is deliberate,
because "the call was denied" and "the call was made and then denied" are
indistinguishable from the caller's side and completely different on the
invoice. A check that ran after the request would deny the *result* while still
paying for it - which is the exact opposite of what a cost cap is for.

`05-ai-layer.md` §3.1: "**The pre-call check uses an estimate; the post-call
record uses actuals.** Estimate = `measured_input_tokens × input_price +
max_output_tokens × output_price`, deliberately pessimistic on output so a
single large call cannot overshoot a cap it was under."

The pessimism is the design. An estimate based on *expected* output would let
one unusually long generation cross a cap the check had just approved, and the
overshoot would be discovered by the bill rather than by the counter.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app.ai.base import Feature
from app.ai.budget import (
    AIBudgetExceeded,
    Budget,
    Caps,
    Counters,
    estimate,
    global_key,
    utc_day,
)

FEATURE = Feature.PACK_GENERATE
USER = "01J000000000000000000USER"

#: `gemini-3.8-flash`'s current rates, per million tokens.
INPUT_PRICE = Decimal("0.75")
OUTPUT_PRICE = Decimal("3.75")


class CountingProvider:
    """A provider that only counts. `AC-AI-03.2`'s evidence."""

    def __init__(self) -> None:
        self.invocations = 0

    async def complete_json(self, *_: object, **__: object) -> dict[str, str]:
        self.invocations += 1
        return {"ok": "true"}


async def spent(amount: str) -> Counters:
    counters = Counters()
    await counters.add_spend(global_key(utc_day()), Decimal(amount), timedelta(hours=1))
    return counters


async def call_through(budget: Budget, provider: CountingProvider, estimate_usd: Decimal) -> bool:
    """The shape every feature uses: check, then call only if allowed."""
    decision = await budget.check(FEATURE, estimate_usd=estimate_usd, user_id=USER)
    if not decision.allowed:
        decision.raise_if_denied(FEATURE)
    await provider.complete_json()
    return True


# -- the criterion -----------------------------------------------------------


async def test_a_denied_call_never_reaches_the_provider():
    """AC-AI-03.2, with the criterion's own evidence."""
    budget = Budget(Caps(global_usd=Decimal("2.00"), user_daily_calls=500), await spent("2.00"))
    provider = CountingProvider()

    with pytest.raises(AIBudgetExceeded):
        await call_through(budget, provider, Decimal("0.01"))

    assert provider.invocations == 0


async def test_an_allowed_call_does_reach_the_provider():
    """The control. A budget that denied everything would satisfy the assertion
    above and ship a product with no AI in it."""
    budget = Budget(Caps(global_usd=Decimal("2.00"), user_daily_calls=500), Counters())
    provider = CountingProvider()

    await call_through(budget, provider, Decimal("0.01"))

    assert provider.invocations == 1


async def test_the_estimate_is_what_is_checked_not_the_actual():
    """A call that *would* cross the cap is refused even though nothing has been
    spent on it yet. Checking the actual would mean checking after paying."""
    budget = Budget(Caps(global_usd=Decimal("1.00"), user_daily_calls=500), await spent("0.90"))
    provider = CountingProvider()

    with pytest.raises(AIBudgetExceeded):
        await call_through(budget, provider, Decimal("0.20"))

    assert provider.invocations == 0


async def test_a_call_that_exactly_reaches_the_cap_is_allowed():
    """The boundary. `spent + estimate > cap` denies; equal to the cap is the
    last call that fits, and refusing it would make the cap effectively smaller
    than its stated value."""
    budget = Budget(Caps(global_usd=Decimal("1.00"), user_daily_calls=500), await spent("0.90"))
    provider = CountingProvider()

    await call_through(budget, provider, Decimal("0.10"))

    assert provider.invocations == 1


async def test_the_denial_carries_the_reset_time():
    """`AC-AI-03.11` needs it for `Retry-After`, and the user-facing copy needs
    it for "try after HH:MM". A denial that only said "no" would leave both
    guessing."""
    budget = Budget(Caps(global_usd=Decimal("1.00"), user_daily_calls=500), await spent("1.00"))

    with pytest.raises(AIBudgetExceeded) as caught:
        await call_through(budget, CountingProvider(), Decimal("0.01"))

    assert caught.value.retry_after_seconds > 0
    assert caught.value.resets_at.hour == 0
    assert caught.value.resets_at.minute == 0


# -- the estimate itself -----------------------------------------------------


def test_the_estimate_is_the_formula_the_spec_gives():
    """§3.1: `measured_input_tokens × input_price + max_output_tokens ×
    output_price`."""
    value = estimate(1_000_000, 1_000_000, INPUT_PRICE, OUTPUT_PRICE)

    assert value == INPUT_PRICE + OUTPUT_PRICE


def test_the_estimate_is_pessimistic_on_output():
    """ "deliberately pessimistic on output so a single large call cannot
    overshoot a cap it was under".

    The estimate assumes the model emits its maximum. An estimate based on the
    expected output would approve a call that then ran long, and the overshoot
    would be found on the invoice rather than in the counter.
    """
    expected_output = 500
    max_output = 8_000

    pessimistic = estimate(4_000, max_output, INPUT_PRICE, OUTPUT_PRICE)
    optimistic = estimate(4_000, expected_output, INPUT_PRICE, OUTPUT_PRICE)

    assert pessimistic > optimistic


def test_the_estimate_is_decimal():
    """A day of fractional-cent additions in binary floating point drifts far
    enough to move a cap."""
    assert isinstance(estimate(100, 100, INPUT_PRICE, OUTPUT_PRICE), Decimal)


def test_a_zero_token_estimate_is_zero():
    assert estimate(0, 0, INPUT_PRICE, OUTPUT_PRICE) == Decimal(0)


# -- the actual replaces the estimate ----------------------------------------


async def test_the_actual_is_what_lands_in_the_counter():
    """§3.1: "Actual spend replaces the estimate in the counter after the call
    returns."

    Recording the pessimistic estimate would exhaust the cap on maybe a tenth of
    the real spend, and the product would degrade all day for no reason.
    """
    counters = Counters()
    budget = Budget(Caps(global_usd=Decimal("2.00"), user_daily_calls=500), counters)

    await budget.check(FEATURE, estimate_usd=Decimal("0.90"), user_id=USER)
    await budget.record_actual(FEATURE, cost_usd=Decimal("0.02"), user_id=USER)

    assert await counters.spend(global_key(utc_day())) == Decimal("0.02")


async def test_an_unpriced_call_still_counts_against_the_user():
    """A call whose cost is unknown adds nothing to the spend counters - there
    is nothing to add - but the per-user *call count* is a count, not a cost,
    and it is the protection that still works when the price does not."""
    counters = Counters()
    budget = Budget(Caps(global_usd=Decimal("2.00"), user_daily_calls=5), counters)

    await budget.record_actual(FEATURE, cost_usd=None, user_id=USER)

    from app.ai.budget import user_key

    assert await counters.calls(user_key(USER, utc_day())) == 1
    assert await counters.spend(global_key(utc_day())) == Decimal(0)


async def test_the_spend_lands_in_both_the_global_and_feature_counters():
    """One call, two counters. A feature cap that only saw its own spend and a
    global cap that only saw the total would each be right, and together they
    would let a feature's runaway hide inside the global headroom."""
    counters = Counters()
    budget = Budget(Caps(global_usd=Decimal("2.00"), user_daily_calls=500), counters)

    await budget.record_actual(FEATURE, cost_usd=Decimal("0.05"), user_id=USER)

    from app.ai.budget import feature_key

    assert await counters.spend(global_key(utc_day())) == Decimal("0.05")
    assert await counters.spend(feature_key(FEATURE, utc_day())) == Decimal("0.05")
