"""T-AI-03.7 - which cap gets the blame.

`AC-AI-03.7`: "The three caps deny in the fixed order: with all three breached,
`deny_reason` is `user`; with feature and global breached, `feature`; with only
global breached, `global`."

`05-ai-layer.md` §3.1: "Check order is fixed and the first failure wins, so a
denial always has one unambiguous reason recorded in `ai_usage.deny_reason`."

The order is not arbitrary, and the rationale is worth keeping next to the test
because it is what makes the order *correct* rather than merely fixed:

> an abusive account should be stopped before it is allowed to exhaust a shared
> budget, and a single feature's runaway should be attributed to that feature
> rather than reported as a global outage.

Both halves matter operationally. If the global cap were checked first, one
looping account would exhaust it and every other user would see the outage while
`deny_reason` said `global` - pointing the investigation at the budget rather
than at the account. And if a single feature's runaway reported `global`, the
dashboard would show "we are out of money" rather than "job enrichment is
broken", which are different incidents with different fixes.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.ai.base import Feature
from app.ai.budget import Budget, Caps, Counters, feature_key, global_key, user_key, utc_day
from app.ai.usage import DenyReason

FEATURE = Feature.JOB_ENRICH
USER = "01J000000000000000000USER"
TINY = Decimal("0.0001")


async def budget_with(
    *, user_breached: bool, feature_breached: bool, global_breached: bool
) -> Budget:
    """A budget whose three caps are in exactly the stated states."""
    counters = Counters()
    caps = Caps(
        global_usd=Decimal("2.00"),
        user_daily_calls=5,
        per_feature_usd={str(FEATURE): Decimal("1.00")},
    )
    day = utc_day()
    from datetime import timedelta

    hour = timedelta(hours=1)

    if user_breached:
        for _ in range(5):
            await counters.add_call(user_key(USER, day), hour)
    if feature_breached:
        await counters.add_spend(feature_key(FEATURE, day), Decimal("1.00"), hour)
    if global_breached:
        await counters.add_spend(global_key(day), Decimal("2.00"), hour)

    return Budget(caps, counters)


# -- the criterion, exactly as written ---------------------------------------


async def test_all_three_breached_blames_the_user():
    """AC-AI-03.7, first clause.

    The abusive account is stopped before it is allowed to exhaust a shared
    budget - and, just as importantly, the investigation is pointed at the
    account rather than at the budget.
    """
    budget = await budget_with(user_breached=True, feature_breached=True, global_breached=True)

    decision = await budget.check(FEATURE, estimate_usd=TINY, user_id=USER)

    assert decision.allowed is False
    assert decision.reason is DenyReason.USER


async def test_feature_and_global_breached_blames_the_feature():
    """AC-AI-03.7, second clause.

    "job enrichment is broken" and "we are out of money" are different
    incidents with different fixes, and this is what tells them apart.
    """
    budget = await budget_with(user_breached=False, feature_breached=True, global_breached=True)

    decision = await budget.check(FEATURE, estimate_usd=TINY, user_id=USER)

    assert decision.reason is DenyReason.FEATURE


async def test_only_global_breached_blames_the_global_cap():
    """AC-AI-03.7, third clause."""
    budget = await budget_with(user_breached=False, feature_breached=False, global_breached=True)

    decision = await budget.check(FEATURE, estimate_usd=TINY, user_id=USER)

    assert decision.reason is DenyReason.GLOBAL


async def test_nothing_breached_allows_the_call():
    """The control. An implementation that denied unconditionally would satisfy
    all three assertions above."""
    budget = await budget_with(user_breached=False, feature_breached=False, global_breached=False)

    decision = await budget.check(FEATURE, estimate_usd=TINY, user_id=USER)

    assert decision.allowed is True
    assert decision.reason is None


# -- the pairs the criterion does not spell out ------------------------------


async def test_user_and_global_breached_blames_the_user():
    budget = await budget_with(user_breached=True, feature_breached=False, global_breached=True)

    assert (await budget.check(FEATURE, estimate_usd=TINY, user_id=USER)).reason is DenyReason.USER


async def test_user_and_feature_breached_blames_the_user():
    budget = await budget_with(user_breached=True, feature_breached=True, global_breached=False)

    assert (await budget.check(FEATURE, estimate_usd=TINY, user_id=USER)).reason is DenyReason.USER


async def test_only_the_feature_breached_blames_the_feature():
    budget = await budget_with(user_breached=False, feature_breached=True, global_breached=False)

    assert (
        await budget.check(FEATURE, estimate_usd=TINY, user_id=USER)
    ).reason is DenyReason.FEATURE


async def test_only_the_user_breached_blames_the_user():
    budget = await budget_with(user_breached=True, feature_breached=False, global_breached=False)

    assert (await budget.check(FEATURE, estimate_usd=TINY, user_id=USER)).reason is DenyReason.USER


# -- the shape of the rule ---------------------------------------------------


async def test_a_call_with_no_user_skips_the_user_cap():
    """A job enrichment serves everyone who sees the job and belongs to nobody.
    Charging it to a user would be arbitrary, and denying it because *some* user
    is over their limit would be wrong."""
    budget = await budget_with(user_breached=True, feature_breached=False, global_breached=False)

    decision = await budget.check(FEATURE, estimate_usd=TINY, user_id=None)

    assert decision.allowed is True


async def test_a_feature_with_no_cap_of_its_own_is_bound_by_the_global_one():
    """Most features have no cap. A missing per-feature cap must mean "the
    global one applies", not "no limit"."""
    counters = Counters()
    from datetime import timedelta

    await counters.add_spend(global_key(utc_day()), Decimal("2.00"), timedelta(hours=1))
    budget = Budget(Caps(global_usd=Decimal("2.00"), user_daily_calls=500), counters)

    decision = await budget.check(Feature.PACK_GENERATE, estimate_usd=TINY, user_id=USER)

    assert decision.reason is DenyReason.GLOBAL


async def test_a_zero_cap_means_no_cap_not_no_spending():
    """The state every deployment starts in. Reading zero as "deny everything"
    would make an unset optional variable a total outage."""
    budget = Budget(Caps(global_usd=Decimal("2.00"), user_daily_calls=0), Counters())

    decision = await budget.check(FEATURE, estimate_usd=TINY, user_id=USER)

    assert decision.allowed is True


async def test_the_reason_is_one_of_the_three_the_data_model_names():
    """`17-data-model.md` §2.12: "`ai_usage.deny_reason` ∈ {user, feature,
    global, null}"."""
    budget = await budget_with(user_breached=True, feature_breached=True, global_breached=True)
    decision = await budget.check(FEATURE, estimate_usd=TINY, user_id=USER)

    assert str(decision.reason) in {"user", "feature", "global"}


async def test_the_order_matches_the_matrix_file():
    """`ai-budget.yaml` states `deny_precedence: [user, feature, global]`.

    Read back rather than restated, so the file and the implementation cannot
    drift - and the file is the normative one.
    """
    from app.ai.budget import MATRIX

    order = (DenyReason.USER, DenyReason.FEATURE, DenyReason.GLOBAL)
    assert list(MATRIX.deny_precedence) == [str(reason) for reason in order]


@pytest.mark.parametrize("estimate", [Decimal("0.0001"), Decimal("1000")])
async def test_the_reason_does_not_depend_on_the_estimate(estimate: Decimal):
    """The user cap counts calls, not cost, so an enormous estimate must not
    change who gets the blame when the user is already over."""
    budget = await budget_with(user_breached=True, feature_breached=False, global_breached=False)

    assert (
        await budget.check(FEATURE, estimate_usd=estimate, user_id=USER)
    ).reason is DenyReason.USER
