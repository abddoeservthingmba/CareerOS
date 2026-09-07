"""T-AI-03.9 - `ok`, `soft`, `hard`, and one alert a day.

`AC-AI-03.9`: "`ai_budget_state` reports `ok`, `soft` and `hard` at the specified
thresholds, and `soft` raises exactly one alert per day per feature."

`05-ai-layer.md` §3.1's table:

| `ok`   | spend < 80% of the binding cap        | Normal                          |
| `soft` | 80-100% of the binding cap  | Normal, plus a warning and one alert a day |
| `hard` | estimate would cross the cap | `AIBudgetExceeded` before the provider call |

`soft` is the state that earns its keep. `hard` is a fact you discover by being
denied; `soft` is a warning delivered while there is still a day left to act on
it - to raise the cap, to find the loop, or to decide the day is going to end
degraded and say so.

**"Exactly one alert per day per feature"** is the difference between a useful
warning and a pager that nobody reads. A feature at 85% of its cap stays at 85%
for hours; alerting on every call in that window would produce thousands of
identical messages and train everyone to mute the channel - which is how the
`hard` alert, when it comes, is also missed.

**The binding cap** is the feature's own if it has one, otherwise the global.
Reporting a feature against the global cap while a tighter per-feature cap
governs it would say `ok` right up to the moment that feature stopped working.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app.ai.base import Feature
from app.ai.budget import (
    SOFT_THRESHOLD_PCT,
    STATE_VALUE,
    Budget,
    BudgetState,
    Caps,
    Counters,
    feature_key,
    global_key,
    utc_day,
)
from app.core import clock

FEATURE = Feature.JOB_ENRICH
OTHER = Feature.MATCH_RATIONALE
CAP = Decimal("2.00")
HOUR = timedelta(hours=1)


async def at_spend(amount: str, *, per_feature: bool = False) -> Budget:
    counters = Counters()
    key = feature_key(FEATURE, utc_day()) if per_feature else global_key(utc_day())
    await counters.add_spend(key, Decimal(amount), HOUR)
    caps = Caps(
        global_usd=CAP,
        user_daily_calls=500,
        per_feature_usd={str(FEATURE): CAP} if per_feature else {},
    )
    return Budget(caps, counters)


# -- the three states at the stated thresholds -------------------------------


@pytest.mark.parametrize(
    ("spend", "expected"),
    [
        ("0.00", BudgetState.OK),
        ("0.50", BudgetState.OK),
        ("1.59", BudgetState.OK),
        ("1.60", BudgetState.SOFT),  # exactly 80%
        ("1.90", BudgetState.SOFT),
        ("1.99", BudgetState.SOFT),
        ("2.00", BudgetState.HARD),  # exactly 100%
        ("3.00", BudgetState.HARD),
    ],
)
async def test_the_state_at_each_threshold(spend: str, expected: BudgetState):
    """AC-AI-03.9, against §3.1's table."""
    budget = await at_spend(spend)

    assert await budget.state(FEATURE) is expected


def test_the_soft_threshold_is_the_one_the_spec_states():
    """80%. Read from the module rather than restated, so the two cannot
    drift."""
    assert SOFT_THRESHOLD_PCT == 80


async def test_eighty_percent_is_soft_not_ok():
    """The boundary is inclusive: at exactly 80% the warning is due. Exclusive
    would mean the warning arrives one call later, which is a distinction
    nobody wants to reason about during an incident."""
    assert await (await at_spend("1.60")).state(FEATURE) is BudgetState.SOFT


async def test_one_hundred_percent_is_hard_not_soft():
    """At the cap there is no headroom, so the next call is denied. Reporting
    `soft` there would say "still normal" about a feature that has stopped."""
    assert await (await at_spend("2.00")).state(FEATURE) is BudgetState.HARD


# -- the binding cap ---------------------------------------------------------


async def test_a_feature_with_its_own_cap_is_measured_against_it():
    """A feature at 90% of its own $2 cap is in `soft`, even though the global
    spend is the same $1.80 against the same $2 - the point is that the two can
    differ, and the tighter one is what governs."""
    budget = await at_spend("1.80", per_feature=True)

    assert await budget.state(FEATURE) is BudgetState.SOFT


async def test_a_feature_without_its_own_cap_is_measured_against_the_global_one():
    budget = await at_spend("1.80")

    assert await budget.state(OTHER) is BudgetState.SOFT


async def test_a_features_own_spend_does_not_move_another_features_state():
    """Two features with their own caps are independent. One at its limit must
    not make the other look degraded."""
    counters = Counters()
    await counters.add_spend(feature_key(FEATURE, utc_day()), Decimal("2.00"), HOUR)
    budget = Budget(
        Caps(
            global_usd=Decimal("100"),
            user_daily_calls=500,
            per_feature_usd={str(FEATURE): CAP, str(OTHER): CAP},
        ),
        counters,
    )

    assert await budget.state(FEATURE) is BudgetState.HARD
    assert await budget.state(OTHER) is BudgetState.OK


async def test_no_cap_at_all_is_always_ok():
    """A cap of zero means "no cap of its own". A budget with no global cap
    either is a deployment that has chosen not to limit spend, and reporting
    `hard` would be a lie about a limit that does not exist."""
    budget = Budget(Caps(global_usd=Decimal(0), user_daily_calls=0), Counters())

    assert await budget.state(FEATURE) is BudgetState.OK


# -- the alert ---------------------------------------------------------------


async def test_soft_raises_exactly_one_alert_per_day_per_feature():
    """AC-AI-03.9's second half.

    A feature at 85% stays there for hours. Alerting per call would produce
    thousands of identical messages and train everyone to mute the channel -
    after which the `hard` alert is missed too.
    """
    budget = await at_spend("1.70")

    for _ in range(20):
        await budget.check(FEATURE, estimate_usd=Decimal("0.001"), user_id=None)

    assert budget.alerts_raised(FEATURE) == 1


async def test_two_features_in_soft_raise_two_alerts():
    """ "per day per feature". One alert for the whole system would say "spend is
    high" and not say where."""
    budget = await at_spend("1.70")

    await budget.check(FEATURE, estimate_usd=Decimal("0.001"))
    await budget.check(OTHER, estimate_usd=Decimal("0.001"))

    assert budget.alerts_raised() == 2
    assert budget.alerts_raised(FEATURE) == 1
    assert budget.alerts_raised(OTHER) == 1


async def test_the_alert_resets_with_the_day():
    """ "one alert per day" - so a sustained problem alerts again tomorrow.

    The counters are date-keyed and reset with the day, so day two starts at
    zero spend: this re-spends to the same point and asserts the alert fires
    again. An alert marker that was not date-keyed would go quiet on day two of
    a problem that was still happening.
    """
    counters = Counters()
    budget = Budget(Caps(global_usd=CAP, user_daily_calls=500), counters)
    start = clock.now()

    with clock.freeze(start):
        await counters.add_spend(global_key(utc_day()), Decimal("1.70"), HOUR)
        await budget.check(FEATURE, estimate_usd=Decimal("0.001"))
        assert budget.alerts_raised(FEATURE) == 1
        # A second call the same day stays quiet.
        await budget.check(FEATURE, estimate_usd=Decimal("0.001"))
        assert budget.alerts_raised(FEATURE) == 1

    tomorrow = start + timedelta(days=1)
    with clock.freeze(tomorrow):
        await counters.add_spend(global_key(utc_day()), Decimal("1.70"), HOUR)
        await budget.check(FEATURE, estimate_usd=Decimal("0.001"))

    assert budget.alerts_raised(FEATURE) == 2


async def test_ok_raises_no_alert():
    """The control. An alert on every call would satisfy "at least one"."""
    budget = await at_spend("0.10")

    for _ in range(5):
        await budget.check(FEATURE, estimate_usd=Decimal("0.001"))

    assert budget.alerts_raised() == 0


async def test_a_denial_does_not_raise_the_soft_alert():
    """`hard` is a different signal with a different urgency. Folding it into
    the `soft` count would make "we are being warned" and "we have stopped"
    look the same on the dashboard."""
    budget = await at_spend("2.00")

    await budget.check(FEATURE, estimate_usd=Decimal("0.001"))

    assert budget.alerts_raised() == 0


# -- the gauge ---------------------------------------------------------------


async def test_the_state_reaches_the_gauge():
    """`OPS-04` §4.2: "`ai_budget_state{feature}` | Are users being degraded
    right now". A state nothing exports answers that question for nobody."""
    from app.core import metrics

    budget = await at_spend("1.70")
    await budget.check(FEATURE, estimate_usd=Decimal("0.001"))

    body = metrics.render().decode()
    assert f'ai_budget_state{{feature="{FEATURE}"}}' in body


async def test_a_denial_reports_hard_on_the_gauge():
    from app.core import metrics

    budget = await at_spend("2.00")
    await budget.check(OTHER, estimate_usd=Decimal("0.001"))

    body = metrics.render().decode()
    line = next(
        entry
        for entry in body.split("\n")
        if entry.startswith(f'ai_budget_state{{feature="{OTHER}"}}')
    )
    assert line.endswith(str(float(STATE_VALUE[BudgetState.HARD])))


def test_the_gauge_values_are_ordered_by_severity():
    """A gauge cannot hold a string, so the states are numbers - and a dashboard
    thresholds on them. Unordered values would make "alert above 1" meaningless.
    """
    assert STATE_VALUE[BudgetState.OK] < STATE_VALUE[BudgetState.SOFT]
    assert STATE_VALUE[BudgetState.SOFT] < STATE_VALUE[BudgetState.HARD]


def test_the_states_are_the_three_the_spec_names():
    assert {str(state) for state in BudgetState} == {"ok", "soft", "hard"}
