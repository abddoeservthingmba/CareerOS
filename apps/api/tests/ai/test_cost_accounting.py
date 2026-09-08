"""T-AI-03.3 - the recorded cost is the provider's own token counts.

`AC-AI-03.3`: "Actual spend recorded after a call uses the provider's reported
token counts, and `est_cost_usd` matches `MODEL_PRICING` to within a rounding
cent."

Two separate claims, and the first is the one that goes wrong quietly.

**The provider's counts, not ours.** Tokenization is the provider's business:
their tokenizer, their version of it, their accounting for system instructions
and structured-output schemas. A locally computed estimate is a guess that
drifts - always in the same direction, because the parts we forget to count are
parts they charge for - and the drift is only discovered when the invoice
disagrees with the dashboard.

**And the arithmetic must be exact.** `Decimal`, not `float`: a day of
fractional-cent additions in binary floating point drifts far enough to move a
cap, which means a feature degrades a call early or a call late, for no reason
anyone can find.

The estimate is still used - before the call, pessimistically (§3.1). It is
*replaced* by the actual once the provider answers. The two numbers have
different jobs: one prevents an overshoot, the other is the truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.ai import pricing
from app.ai.base import Feature
from app.ai.budget import Budget, Caps, Counters, estimate, feature_key, global_key, utc_day
from app.ai.usage import Outcome, UsageRecorder, build_row

MODEL = "gemini-3.5-flash-lite"
INPUT_PRICE = Decimal("0.30")
OUTPUT_PRICE = Decimal("2.50")
USER = "01J000000000000000000USER"


@dataclass(frozen=True)
class ProviderResponse:
    """What an adapter returns: the provider's own counts, not ours."""

    text: str
    input_tokens: int
    output_tokens: int


async def complete(
    budget: Budget, recorder: UsageRecorder, response: ProviderResponse
) -> Decimal | None:
    """The post-call half of §3.1: actuals in, estimate out."""
    cost = pricing.estimate_cost(MODEL, response.input_tokens, response.output_tokens)
    await budget.record_actual(Feature.RESUME_EXTRACT, cost_usd=cost, user_id=USER)
    recorder.record(
        build_row(
            provider="gemini",
            model=MODEL,
            feature=Feature.RESUME_EXTRACT,
            outcome=Outcome.OK,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            est_cost_usd=cost,
            latency_ms=1200,
        )
    )
    return cost


# -- the provider's counts ---------------------------------------------------


async def test_the_recorded_tokens_are_the_providers():
    """AC-AI-03.3, first half."""
    budget = Budget(Caps(global_usd=Decimal("2"), user_daily_calls=500), Counters())
    recorder = UsageRecorder()

    await complete(budget, recorder, ProviderResponse("{}", input_tokens=4120, output_tokens=812))

    row = recorder.drain()[0]
    assert row["input_tokens"] == 4120
    assert row["output_tokens"] == 812


async def test_the_recorded_cost_matches_the_pricing_table():
    """AC-AI-03.3, second half - "to within a rounding cent"."""
    budget = Budget(Caps(global_usd=Decimal("2"), user_daily_calls=500), Counters())
    recorder = UsageRecorder()

    cost = await complete(
        budget, recorder, ProviderResponse("{}", input_tokens=4120, output_tokens=812)
    )

    expected = (Decimal(4120) * INPUT_PRICE + Decimal(812) * OUTPUT_PRICE) / Decimal(1_000_000)
    assert cost == expected
    assert abs(cost - expected) < Decimal("0.01")


async def test_the_actual_replaces_the_estimate_in_the_counter():
    """§3.1: "Actual spend replaces the estimate in the counter after the call
    returns."

    Recording the pessimistic estimate instead would exhaust the cap on a small
    fraction of the real spend, and the product would degrade all day for no
    reason.
    """
    counters = Counters()
    budget = Budget(Caps(global_usd=Decimal("2"), user_daily_calls=500), counters)

    pessimistic = estimate(4120, 8000, INPUT_PRICE, OUTPUT_PRICE)
    await budget.check(Feature.RESUME_EXTRACT, estimate_usd=pessimistic, user_id=USER)
    await complete(
        budget, UsageRecorder(), ProviderResponse("{}", input_tokens=4120, output_tokens=812)
    )

    actual = await counters.spend(global_key(utc_day()))
    assert actual < pessimistic
    assert actual == pricing.estimate_cost(MODEL, 4120, 812)


async def test_the_estimate_never_reaches_the_counter():
    """The check reads the counter; it does not write to it. A check that
    reserved its estimate would leave a phantom charge behind whenever the call
    failed or was cached."""
    counters = Counters()
    budget = Budget(Caps(global_usd=Decimal("2"), user_daily_calls=500), counters)

    await budget.check(Feature.RESUME_EXTRACT, estimate_usd=Decimal("0.5"), user_id=USER)

    assert await counters.spend(global_key(utc_day())) == Decimal(0)


# -- the arithmetic ----------------------------------------------------------


def test_the_cost_is_decimal_all_the_way():
    """A day of fractional-cent additions in binary floating point drifts far
    enough to move a cap - which degrades a feature a call early or a call late
    for no reason anyone can find."""
    cost = pricing.estimate_cost(MODEL, 4120, 812)

    assert isinstance(cost, Decimal)


async def test_many_small_calls_sum_exactly():
    """The failure this guards is invisible per call and obvious per day.

    A thousand calls at a fraction of a cent each is a real day's traffic, and
    in `float` the accumulated error is enough to move the cap by a call or two.
    """
    counters = Counters()
    budget = Budget(Caps(global_usd=Decimal("100"), user_daily_calls=100_000), counters)
    per_call = pricing.estimate_cost(MODEL, 1000, 100)
    assert per_call is not None

    for _ in range(1000):
        await budget.record_actual(Feature.RESUME_EXTRACT, cost_usd=per_call, user_id=USER)

    assert await counters.spend(global_key(utc_day())) == per_call * 1000


async def test_the_spend_lands_in_both_counters():
    """One call, two counters - the global and the feature's own. A feature cap
    that only saw its own spend and a global that only saw the total would each
    be right, and together they would let a feature's runaway hide inside the
    global headroom."""
    counters = Counters()
    budget = Budget(Caps(global_usd=Decimal("2"), user_daily_calls=500), counters)

    cost = await complete(
        budget, UsageRecorder(), ProviderResponse("{}", input_tokens=1000, output_tokens=100)
    )

    assert await counters.spend(global_key(utc_day())) == cost
    assert await counters.spend(feature_key(Feature.RESUME_EXTRACT, utc_day())) == cost


# -- the unpriced case -------------------------------------------------------


async def test_an_unpriced_model_records_null_and_spends_nothing():
    """`AC-AI-04.3` meets `AC-AI-03.3`. There is no honest number to add to the
    counter, so nothing is added - and the row says `null` rather than zero, so
    the gap is visible."""
    counters = Counters()
    budget = Budget(Caps(global_usd=Decimal("2"), user_daily_calls=500), counters)
    recorder = UsageRecorder()
    pricing.UNPRICED_CALLS.clear()

    cost = pricing.estimate_cost("a-model-with-no-price", 1000, 100)
    await budget.record_actual(Feature.RESUME_EXTRACT, cost_usd=cost, user_id=USER)
    recorder.record(
        build_row(
            provider="gemini",
            model="a-model-with-no-price",
            feature=Feature.RESUME_EXTRACT,
            outcome=Outcome.OK,
            input_tokens=1000,
            output_tokens=100,
            est_cost_usd=cost,
        )
    )

    assert recorder.drain()[0]["est_cost_usd"] is None
    assert await counters.spend(global_key(utc_day())) == Decimal(0)
    assert pricing.unpriced_count("a-model-with-no-price") == 1
    pricing.UNPRICED_CALLS.clear()


async def test_an_unpriced_call_still_counts_against_the_user():
    """The per-user cap is a count, not a cost. It is the one protection that
    still works when the price is unknown - which is precisely when a runaway is
    most likely, because the model is new."""
    counters = Counters()
    budget = Budget(Caps(global_usd=Decimal("2"), user_daily_calls=500), counters)

    await budget.record_actual(Feature.RESUME_EXTRACT, cost_usd=None, user_id=USER)

    from app.ai.budget import user_key

    assert await counters.calls(user_key(USER, utc_day())) == 1


# -- the latency the row carries ---------------------------------------------


async def test_the_row_records_how_long_the_call_took():
    """`17-data-model.md` §2.12 has `latency_ms`. Cost and latency are the two
    questions asked of an AI feature, and a row with only one of them answers
    half of them."""
    recorder = UsageRecorder()
    budget = Budget(Caps(global_usd=Decimal("2"), user_daily_calls=500), Counters())

    await complete(budget, recorder, ProviderResponse("{}", input_tokens=100, output_tokens=10))

    assert recorder.drain()[0]["latency_ms"] == 1200


@pytest.mark.parametrize(
    ("input_tokens", "output_tokens"),
    [(0, 0), (1, 0), (0, 1), (1_000_000, 1_000_000)],
)
def test_the_arithmetic_holds_at_the_edges(input_tokens: int, output_tokens: int):
    """Zero tokens is a real outcome - a request rejected before generation -
    and a million is a long resume. Neither should produce a surprise."""
    cost = pricing.estimate_cost(MODEL, input_tokens, output_tokens)

    assert cost is not None
    assert cost >= 0
