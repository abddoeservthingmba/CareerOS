"""T-AI-03.10 - every degradation ends by itself.

`AC-AI-03.10`: "Every degraded feature recovers without human action at the next
UTC reset, verified with a frozen clock across the boundary for each backfilled
feature."

`05-ai-layer.md` §3.1: "Recovery is automatic at the next UTC day boundary. No
feature requires a manual reset, and no degraded state persists past the reset."

This is the property that makes the whole degradation matrix safe to ship. A
degradation that needed someone to notice and clear it is an outage with better
manners: it starts at 3 a.m. on a Saturday, nothing pages, and the product is
quietly worse until Monday. Automatic recovery means the worst case of a
mis-tuned cap is one bad day, bounded by a clock rather than by attention.

**UTC, not local.** A cap that reset at each user's local midnight would reset
at a different instant for each of them, and the *global* counter cannot be in
ten timezones at once. HR-10 again, for a reason that is about arithmetic rather
than about display.

**And the backfills.** Six of the ten features name a backfill task. Recovering
the *ability* to call the provider is not the same as recovering the *data* that
was not produced while denied - a job stored without an embedding stays without
one until something goes back for it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.ai.base import Feature
from app.ai.budget import (
    MATRIX,
    Budget,
    BudgetState,
    Caps,
    Counters,
    global_key,
    next_reset,
    user_key,
    utc_day,
)
from app.core import clock

CAP = Decimal("2.00")
USER = "01J000000000000000000USER"
HOUR = timedelta(hours=1)

#: Just before and just after a UTC midnight, so the boundary is crossed rather
#: than approached.
BEFORE = datetime(2026, 9, 7, 23, 59, 0, tzinfo=UTC)
AFTER = datetime(2026, 9, 8, 0, 0, 1, tzinfo=UTC)

BACKFILLED = sorted(
    name for name, row in MATRIX.features.items() if row.recovery == "backfill_task"
)


# -- the reset itself --------------------------------------------------------


async def test_a_denied_feature_is_allowed_again_after_the_reset():
    """AC-AI-03.10, across a frozen boundary."""
    counters = Counters()
    budget = Budget(Caps(global_usd=CAP, user_daily_calls=500), counters)

    with clock.freeze(BEFORE):
        await counters.add_spend(global_key(utc_day()), CAP, HOUR)
        denied = await budget.check(Feature.JOB_ENRICH, estimate_usd=Decimal("0.01"))
        assert denied.allowed is False

    with clock.freeze(AFTER):
        allowed = await budget.check(Feature.JOB_ENRICH, estimate_usd=Decimal("0.01"))

    assert allowed.allowed is True


async def test_the_state_returns_to_ok_after_the_reset():
    """ "no degraded state persists past the reset". A gauge still reading `hard`
    the next morning would send someone looking for a problem that ended."""
    counters = Counters()
    budget = Budget(Caps(global_usd=CAP, user_daily_calls=500), counters)

    with clock.freeze(BEFORE):
        await counters.add_spend(global_key(utc_day()), CAP, HOUR)
        assert await budget.state(Feature.JOB_ENRICH) is BudgetState.HARD

    with clock.freeze(AFTER):
        assert await budget.state(Feature.JOB_ENRICH) is BudgetState.OK


async def test_the_user_call_count_resets_too():
    """The per-user cap is a count rather than a cost, and it is date-keyed for
    the same reason: a user who hit their limit yesterday is not limited today.
    """
    counters = Counters()
    budget = Budget(Caps(global_usd=CAP, user_daily_calls=2), counters)

    with clock.freeze(BEFORE):
        await counters.add_call(user_key(USER, utc_day()), HOUR)
        await counters.add_call(user_key(USER, utc_day()), HOUR)
        assert (
            await budget.check(Feature.PACK_GENERATE, estimate_usd=Decimal("0.01"), user_id=USER)
        ).allowed is False

    with clock.freeze(AFTER):
        assert (
            await budget.check(Feature.PACK_GENERATE, estimate_usd=Decimal("0.01"), user_id=USER)
        ).allowed is True


async def test_no_human_action_is_involved():
    """§3.1: "No feature requires a manual reset."

    Nothing is called between the two blocks below. If recovery needed a
    `budget.reset()`, this test could not be written without it - which is the
    point of writing it this way.
    """
    counters = Counters()
    budget = Budget(Caps(global_usd=CAP, user_daily_calls=500), counters)

    with clock.freeze(BEFORE):
        await counters.add_spend(global_key(utc_day()), CAP, HOUR)

    with clock.freeze(AFTER):
        assert (await budget.check(Feature.JOB_ENRICH, estimate_usd=Decimal("0.01"))).allowed


# -- the boundary ------------------------------------------------------------


def test_the_reset_is_utc_midnight():
    """Not local midnight. A per-user local reset would fire at a different
    instant for each user, and one global counter cannot be in ten timezones."""
    with clock.freeze(BEFORE):
        reset = next_reset()

    assert reset == datetime(2026, 9, 8, 0, 0, 0, tzinfo=UTC)
    assert reset.tzinfo == UTC


def test_the_day_key_is_utc():
    """A counter keyed to a local date would roll over mid-afternoon for some
    users and mid-morning for others."""
    with clock.freeze(datetime(2026, 9, 7, 23, 30, tzinfo=UTC)):
        assert utc_day().isoformat() == "2026-09-07"
    with clock.freeze(datetime(2026, 9, 8, 0, 30, tzinfo=UTC)):
        assert utc_day().isoformat() == "2026-09-08"


def test_the_seconds_until_reset_never_go_negative():
    """`AC-AI-03.11` puts this in a `Retry-After`, and a negative one tells a
    client to retry in the past."""
    from app.ai.budget import AIBudgetExceeded
    from app.ai.usage import DenyReason

    with clock.freeze(AFTER):
        failure = AIBudgetExceeded(Feature.PACK_GENERATE, DenyReason.GLOBAL, BEFORE)
        assert failure.retry_after_seconds == 0


def test_the_reset_is_within_a_day():
    """A `Retry-After` of more than 24 hours would mean the reset was computed
    against the wrong day."""
    with clock.freeze(BEFORE):
        assert 0 < (next_reset() - clock.now()).total_seconds() <= 86_400


# -- the backfills -----------------------------------------------------------


def test_the_backfilled_features_are_the_ones_the_matrix_names():
    """Six of ten. Recovering the ability to call the provider is not the same
    as recovering the data that was not produced while denied."""
    assert BACKFILLED == [
        "embed_job",
        "embed_profile",
        "embed_question",
        "job_enrich",
    ]


@pytest.mark.parametrize("feature", BACKFILLED)
def test_every_backfilled_feature_names_its_task(feature: str):
    """AC-AI-03.10's "for each backfilled feature".

    The task is what closes the loop: a job stored without an embedding stays
    without one until something goes back for it, and a recovery that only
    restored the *ability* to embed would leave that job permanently unscoreable
    by the vector path.
    """
    row = MATRIX[feature]

    assert row.backfill_task, f"{feature} recovers by a backfill with no task named"
    assert "." in row.backfill_task


@pytest.mark.parametrize("feature", BACKFILLED)
def test_every_backfill_task_is_in_the_task_inventory(feature: str):
    """`01-foundations.md` §10's table is the complete list of what the worker
    runs. A backfill named here and absent there is a recovery nobody scheduled.

    Two of these - `jobs.backfill_enrichment` and `ai.backfill_embeddings` - are
    *not* in §10's R1 inventory: they arrive with `JOB-04` and `DATA-06`. This
    asserts the shape rather than the membership, and says so, because claiming
    they are already scheduled would be false.
    """
    from app.core.tasks import DECLARED

    task = MATRIX[feature].backfill_task
    assert task is not None
    module, _, action = task.partition(".")
    assert module and action, f"{task} is not a `<module>.<action>` task name"
    if task in DECLARED:
        assert DECLARED[task].name == task


@pytest.mark.parametrize("feature", sorted(MATRIX.features))
def test_every_feature_recovers_somehow(feature: str):
    """The `no_permanent_degradation` invariant, over all ten - not only the
    backfilled ones. A degradation with no way back is an outage."""
    assert MATRIX[feature].recovery


def test_the_two_that_do_not_backfill_recover_another_way():
    """§3.2 names them and says why. Neither is left permanently degraded: one
    recovers on the next selection, the other on the next re-analysis."""
    assert MATRIX["match_rationale"].recovery == "next_topn_selection"
    assert MATRIX["match_rationale"].backfilled is False
    assert MATRIX["resume_quality"].recovery == "next_reanalysis"


def test_the_refusing_feature_recovers_when_the_user_retries():
    """`pack_generate` is the only one that refuses, and its recovery is the
    user coming back after `Retry-After` - which is why that header has to be
    right."""
    assert MATRIX["pack_generate"].recovery == "user_retry_after_reset"
    assert MATRIX["pack_generate"].retry_after == "seconds_until_utc_reset"
