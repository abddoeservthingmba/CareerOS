"""T-AI-04.3 - a model with no price records `null`, never zero.

`AC-AI-04.3`: "A model absent from `MODEL_PRICING` records `est_cost_usd: null`
and increments the alert counter."

The whole point is the difference between two ways of not knowing a cost.

Recording **zero** says "this was free". The dashboard shows spend flat, the
budget never trips, `ai_budget_state` stays `ok`, and the first sign that
anything happened is the invoice. Every mechanism in `AI-03` is downstream of
this number, so a wrong zero disables all of them at once - silently, and
precisely on the model somebody just switched to, which is the model most likely
to be expensive.

Recording **null** and alerting says "cost tracking has a blind spot". That is
the only honest thing an estimate can say about a price it does not have, and
`15-infra-and-ops.md` §4.3 makes it an alert for exactly that reason: "Unpriced
AI model | any `est_cost_usd: null` | Cost tracking has a blind spot".
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.ai import pricing
from app.ai.usage import Outcome, build_row
from app.core import clock


@pytest.fixture(autouse=True)
def clean_counter():
    """The counter is process-global, as an alert counter is."""
    pricing.UNPRICED_CALLS.clear()
    yield
    pricing.UNPRICED_CALLS.clear()


# -- the criterion -----------------------------------------------------------


def test_an_unpriced_model_estimates_none():
    """AC-AI-04.3, first half."""
    assert pricing.estimate_cost("some-model-nobody-priced", 4120, 812) is None


def test_an_unpriced_model_increments_the_counter():
    """AC-AI-04.3, second half - the thing that makes it visible."""
    pricing.estimate_cost("some-model-nobody-priced", 100, 10)
    pricing.estimate_cost("some-model-nobody-priced", 100, 10)

    assert pricing.unpriced_count("some-model-nobody-priced") == 2
    assert pricing.unpriced_count() == 2


def test_the_estimate_is_not_zero():
    """The assertion this file exists for.

    `None` and `0` are both falsy, so a test written as `assert not cost` would
    pass for either - and the bug being guarded against is exactly the one that
    produces zero.
    """
    cost = pricing.estimate_cost("some-model-nobody-priced", 4120, 812)

    assert cost is None
    assert cost != Decimal(0)


def test_a_priced_model_does_not_touch_the_counter():
    """The control. A counter that incremented on every call would alert
    constantly, and an alert that always fires is an alert nobody reads."""
    assert pricing.estimate_cost("gemini-3.8-flash", 1000, 100) is not None
    assert pricing.unpriced_count() == 0


def test_the_usage_row_carries_the_null_through():
    """`17-data-model.md` §2.12 writes `est_cost_usd` as nullable for this.

    A row that turned `None` into `0.0` on the way to the database would undo
    the whole thing one layer down.
    """
    row = build_row(
        provider="gemini",
        model="some-model-nobody-priced",
        feature="pack_generate",
        outcome=Outcome.OK,
        input_tokens=4120,
        output_tokens=812,
        est_cost_usd=pricing.estimate_cost("some-model-nobody-priced", 4120, 812),
    )

    assert row["est_cost_usd"] is None


def test_a_length_tiered_model_is_deliberately_unpriced():
    """§4's table cannot hold a price that depends on prompt length.

    A single number for `gemini-2.5-pro` would be wrong for every prompt over
    200k tokens, and a wrong price is worse than a known-unknown one: it looks
    authoritative.
    """
    for model in pricing.LENGTH_TIERED:
        assert not pricing.is_priced(model)
        assert pricing.estimate_cost(model, 1000, 100) is None


# -- the priced path ---------------------------------------------------------


def test_the_three_configured_tiers_are_priced():
    """`.env.example` selects these. A deployment whose own models were unpriced
    would alert on every call, which is the same as not alerting."""
    for model in ("gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-embedding-001"):
        assert pricing.is_priced(model), f"{model} is selected but has no price"


def test_the_arithmetic_is_per_million_tokens():
    """`AC-AI-03.3` - "matches `MODEL_PRICING` to within a rounding cent"."""
    cost = pricing.estimate_cost("gemini-3.5-flash-lite", 1_000_000, 1_000_000)

    assert cost == Decimal("0.30") + Decimal("2.50")


def test_a_realistic_call_costs_a_fraction_of_a_cent():
    """The number that makes `est_cost_usd` a float in the data model and an
    integer nowhere: cents cannot hold it."""
    cost = pricing.estimate_cost("gemini-3.5-flash-lite", 4120, 812)

    assert cost is not None
    assert Decimal("0.0001") < cost < Decimal("0.01")


def test_the_arithmetic_is_decimal_not_float():
    """`0.30 * 3` in binary floating point is not `0.90`. Over a day of calls
    that drift is the difference between a cap that trips and one that does
    not."""
    price = pricing.MODEL_PRICING["gemini-3.5-flash-lite"]

    assert isinstance(price.input_per_million, Decimal)
    assert isinstance(price.output_per_million, Decimal)
    assert isinstance(pricing.estimate_cost("gemini-3.5-flash-lite", 3, 0), Decimal)


def test_a_zero_token_call_costs_zero_not_none():
    """A real call that used no tokens is genuinely free. Only an *unknown*
    model is `None`, and conflating the two would make the alert meaningless."""
    assert pricing.estimate_cost("gemini-3.8-flash", 0, 0) == Decimal(0)


# -- the recorded date, and the price that expires ---------------------------


def test_every_price_records_when_it_was_verified():
    """§5.2: "verified against Gemini's documentation at implementation time and
    recorded with a date"."""
    for model, price in pricing.MODEL_PRICING.items():
        assert price.verified_on is not None, f"{model} has no verification date"


def test_no_model_id_is_written_in_this_module():
    """`AC-AI-02.2` - the table is a data file, not a `.py` literal.

    Not tidiness: a provider changes prices on their schedule, and a table that
    needed a release to update is a table that is wrong between releases.
    """
    source = pathlib.Path(pricing.__file__).read_text(encoding="utf-8")

    assert "gemini-" not in source
    assert pricing.PRICING_FILE.is_file()
    assert pricing.PRICING_FILE.suffix == ".yaml"


def test_the_verification_is_not_stale():
    """The date is only worth recording if something reads it.

    Ninety days, matching `AC-AI-05.1`'s review window for the compliance
    document - the two go stale together, and should be refreshed together.
    """
    assert pricing.stale_prices() == []


def test_a_stale_verification_is_reported():
    """The control: the freshness check can fail."""
    with clock.freeze(clock.now() + timedelta(days=pricing.MAX_PRICE_AGE_DAYS + 1)):
        stale = pricing.stale_prices()

    assert stale, "the freshness check never fires, so it proves nothing"
    assert any("older than" in entry for entry in stale)


def test_an_announced_price_change_applies_by_itself():
    """Gemini's 3.x Flash rates double on 2027-01-01.

    A table holding only today's number would report half the real cost from
    that morning onward - on every dashboard, and in every budget check - and
    nobody would be told, because nothing failed.
    """
    before = datetime(2026, 12, 31, tzinfo=UTC)
    after = datetime(2027, 1, 1, tzinfo=UTC)

    assert pricing.estimate_cost("gemini-3.8-flash", 1_000_000, 0, at=before) == Decimal("0.75")
    assert pricing.estimate_cost("gemini-3.8-flash", 1_000_000, 0, at=after) == Decimal("1.50")


def test_the_change_uses_the_products_clock():
    """HR-10. A price that read `datetime.now()` would ignore a frozen clock,
    and the test above would be asserting about the wall calendar."""
    with clock.freeze(datetime(2027, 6, 1, tzinfo=UTC)):
        assert pricing.estimate_cost("gemini-3.8-flash", 1_000_000, 0) == Decimal("1.50")


def test_a_price_that_changed_with_no_successor_is_reported_stale():
    """An entry saying "this changes on a date" and not saying to what is a
    price that silently keeps its old value."""
    from datetime import date as date_type

    name = next(iter(pricing.MODEL_PRICING))
    original = pricing.MODEL_PRICING[name]
    pricing.MODEL_PRICING[name] = pricing.Price(
        original.input_per_million,
        original.output_per_million,
        verified_on=original.verified_on,
        changes_on=date_type(2026, 1, 1),
    )
    try:
        assert any("no new rate" in entry for entry in pricing.stale_prices())
    finally:
        pricing.MODEL_PRICING[name] = original
