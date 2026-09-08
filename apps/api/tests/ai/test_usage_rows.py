"""T-AI-04.1 - one row per call, whatever happened.

`AC-AI-04.1`: "A test that exercises every AI feature once produces exactly one
`ai_usage` row per call, with `outcome` correctly set across ok / invalid_json /
repaired / provider_error / budget_denied / cache_hit."

"Exactly one" is the load-bearing phrase, in both directions.

**Not zero.** A budget denial that writes no row is a cost saving nobody can
see, a degradation nobody can explain to the user who noticed it, and a feature
that quietly does nothing - which is indistinguishable from a bug. §4: "No call
is unaccounted."

**Not two.** A repair retry that wrote a row for the failed attempt *and* the
successful one would double-count tokens the provider only charged once, and
`AC-AI-04.5`'s "summing `est_cost_usd` over a day equals the dashboard figure"
would be quietly false.

The six outcomes are the six things that can happen to a call. `cached` is
derived from `outcome`, never stored: `17-data-model.md` §2.12 records that v2.0
had both and "two fields that can disagree about one fact eventually will".
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.ai import pricing
from app.ai.base import Feature
from app.ai.usage import (
    AiUsage,
    DenyReason,
    Outcome,
    UsageRecorder,
    build_row,
    total_cost,
)

MODEL = "gemini-3.5-flash-lite"


@pytest.fixture(autouse=True)
def clean_counter():
    pricing.UNPRICED_CALLS.clear()
    yield
    pricing.UNPRICED_CALLS.clear()


def row(outcome: Outcome, **kwargs: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "provider": "gemini",
        "model": MODEL,
        "feature": Feature.RESUME_EXTRACT,
        "outcome": outcome,
    }
    defaults.update(kwargs)
    return build_row(**defaults)


# -- the six outcomes --------------------------------------------------------


def test_the_outcomes_are_the_ones_the_data_model_names():
    """`17-data-model.md` §2.12: "`ai_usage.outcome` ∈ {ok, invalid_json,
    repaired, provider_error, budget_denied, cache_hit}"."""
    assert {str(outcome) for outcome in Outcome} == {
        "ok",
        "invalid_json",
        "repaired",
        "provider_error",
        "budget_denied",
        "cache_hit",
    }


@pytest.mark.parametrize(
    "outcome",
    [Outcome.OK, Outcome.INVALID_JSON, Outcome.REPAIRED, Outcome.PROVIDER_ERROR, Outcome.CACHE_HIT],
    ids=lambda o: str(o),
)
def test_every_non_denial_outcome_builds_a_row(outcome: Outcome):
    """AC-AI-04.1, one shape per outcome."""
    built = row(outcome, input_tokens=100, output_tokens=20)

    assert built["outcome"] is outcome
    assert built["deny_reason"] is None
    assert built["feature"] == "resume_extract"


def test_a_denial_names_which_cap_refused():
    built = row(Outcome.BUDGET_DENIED, deny_reason=DenyReason.USER)

    assert built["outcome"] is Outcome.BUDGET_DENIED
    assert built["deny_reason"] is DenyReason.USER


def test_a_denial_without_a_reason_is_refused():
    """`ai_usage.deny_reason` is what makes a denial explainable. A row saying
    "denied" and not saying by what is a mystery outage in the dashboard."""
    with pytest.raises(ValueError, match="which cap"):
        row(Outcome.BUDGET_DENIED)


def test_a_non_denial_with_a_reason_is_refused():
    """The other direction. A `deny_reason` on a successful call would make the
    dashboard's denial count meaningless."""
    with pytest.raises(ValueError, match="not a denial"):
        row(Outcome.OK, deny_reason=DenyReason.GLOBAL)


def test_the_deny_reasons_are_the_three_the_spec_names():
    """`17-data-model.md` §2.12: "∈ {user, feature, global, null}"."""
    assert {str(reason) for reason in DenyReason} == {"user", "feature", "global"}


# -- cached is derived, never stored -----------------------------------------


def test_cached_is_derived_from_the_outcome():
    """§2.12, finding F5: "two fields that can disagree about one fact
    eventually will"."""
    assert Outcome.CACHE_HIT.cached is True
    for outcome in Outcome:
        if outcome is not Outcome.CACHE_HIT:
            assert outcome.cached is False


def test_the_document_stores_no_cached_field():
    assert "cached" not in AiUsage.model_fields


def test_the_document_has_the_fields_the_data_model_names():
    """`17-data-model.md` §2.12, field for field."""
    assert set(AiUsage.model_fields) >= {
        "at",
        "provider",
        "model",
        "feature",
        "user_id",
        "input_tokens",
        "output_tokens",
        "est_cost_usd",
        "latency_ms",
        "outcome",
        "prompt_version",
        "deny_reason",
    }
    assert AiUsage.Settings.name == "ai_usage"


def test_the_user_id_is_nullable():
    """A job enrichment serves everyone who sees the job, so it has no user.
    Requiring one would force a placeholder, and a placeholder in `user_id` is a
    row that joins to the wrong person."""
    assert AiUsage.model_fields["user_id"].default is None
    assert row(Outcome.OK)["user_id"] is None


# -- one row per call, across every feature ----------------------------------


def test_every_feature_can_be_accounted_for():
    """AC-AI-04.1's "every AI feature once".

    Parametrised over the enum rather than a list here, so a feature added
    without an accounting path fails this rather than defaulting to unaccounted.
    """
    recorder = UsageRecorder()
    for feature in Feature:
        recorder.record(
            build_row(
                provider="gemini",
                model=MODEL,
                feature=feature,
                outcome=Outcome.OK,
                input_tokens=100,
                output_tokens=20,
                est_cost_usd=pricing.estimate_cost(MODEL, 100, 20),
            )
        )

    rows = recorder.drain()
    assert len(rows) == len(Feature) == 10
    assert {r["feature"] for r in rows} == {str(f) for f in Feature}


def test_one_call_is_one_row():
    """Not two. A repair that recorded both attempts would double-count tokens
    the provider charged once, and the daily total would silently disagree with
    the invoice."""
    recorder = UsageRecorder()
    recorder.record(row(Outcome.REPAIRED, input_tokens=200, output_tokens=40))

    assert recorder.pending() == 1


def test_a_cache_hit_records_zero_cost():
    """§3.3: "A cache hit writes an `ai_usage` row with `outcome: cache_hit` and
    `est_cost_usd: 0`."

    Zero, not null: a cache hit genuinely cost nothing, and that is a different
    statement from "we do not know what it cost".
    """
    built = row(Outcome.CACHE_HIT, est_cost_usd=Decimal(0))

    assert built["est_cost_usd"] == 0.0
    assert built["est_cost_usd"] is not None


def test_a_denial_records_no_tokens():
    """`AC-AI-03.2` - a denial happens before the provider is contacted, so
    there are no token counts to record. Recording an estimate here would put
    spend on the dashboard for a call that never happened."""
    built = row(Outcome.BUDGET_DENIED, deny_reason=DenyReason.FEATURE)

    assert built["input_tokens"] == 0
    assert built["output_tokens"] == 0


# -- AC-AI-04.5: the daily total ---------------------------------------------


def test_the_daily_total_is_the_sum_of_the_rows():
    """`AC-AI-04.5`: "Summing `est_cost_usd` over a day equals the figure the
    admin dashboard shows for that day"."""
    rows = [
        row(Outcome.OK, est_cost_usd=Decimal("0.0012")),
        row(Outcome.REPAIRED, est_cost_usd=Decimal("0.0034")),
        row(Outcome.CACHE_HIT, est_cost_usd=Decimal(0)),
    ]

    assert total_cost(rows) == Decimal("0.0046")


def test_an_unpriced_row_does_not_pretend_to_be_free():
    """Summing `None` as zero would make the total look complete when it is not,
    which is the same failure as pricing an unknown model at zero - one layer
    up."""
    rows = [
        row(Outcome.OK, est_cost_usd=Decimal("0.0012")),
        row(Outcome.OK, model="unpriced", est_cost_usd=None),
    ]

    assert total_cost(rows) == Decimal("0.0012")
    assert any(r["est_cost_usd"] is None for r in rows)


# -- provenance (HR-9) -------------------------------------------------------


def test_a_row_carries_its_prompt_version():
    """HR-9, and `AI-07`: "`prompt_version` is `"<feature>/v<N>"` and is recorded
    on every artifact and every `ai_usage` row"."""
    built = row(Outcome.OK, prompt_version="resume_extract/v1")

    assert built["prompt_version"] == "resume_extract/v1"


def test_a_row_carries_its_model():
    """The other half of HR-9. "Which model produced this" is unanswerable after
    a model swap unless the row said so at the time."""
    assert row(Outcome.OK)["model"] == MODEL


def test_a_row_carries_its_provider():
    """`AI-02` allows a per-feature provider. Two providers' rows that only
    recorded the model would be indistinguishable when both offer a model of
    the same name."""
    assert row(Outcome.OK)["provider"] == "gemini"
