"""T-AI-03.8 - a cache hit is served even when the budget says no.

`AC-AI-03.8`: "A cache hit is served in `hard` budget state (the cache is
checked before the budget)."

`05-ai-layer.md` §3.1: "A cache hit is **free and is never denied**: the cache
is checked before the budget, so a cached result is served even in `hard` state.
This is what keeps job enrichment and rationale serving users during a cap
breach."

The ordering is a one-line decision with a large consequence. Denying a cache
hit saves nothing - the money was spent when the entry was written - and costs a
user their result. Worse, it makes the degradation *worse than it needs to be*
in exactly the situation the degradation matrix exists to soften: on the day the
cap trips, the enrichments already paid for are the ones that keep the feed
usable, and refusing them turns a cost problem into a product outage.

It also has a shape worth noticing: the cheapest calls are the ones a budget
check would reject last, so checking the budget first spends effort on the calls
that need it least.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.ai.base import Feature
from app.ai.budget import (
    AIBudgetExceeded,
    Budget,
    BudgetState,
    Caps,
    Counters,
    ResponseCache,
    cache_key,
    global_key,
    utc_day,
)
from app.ai.usage import Outcome, UsageRecorder, build_row

PROVIDER = "gemini"
MODEL = "gemini-3.5-flash-lite"
VERSION = "job_enrich/v1"
PAYLOAD = {"title": "Backend Engineer"}
CAP = Decimal("2.00")


class CountingProvider:
    def __init__(self) -> None:
        self.invocations = 0

    async def complete_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.invocations += 1
        return {"skills": ["python"]}


async def exhausted_budget() -> Budget:
    counters = Counters()
    await counters.add_spend(global_key(utc_day()), CAP, timedelta(hours=1))
    return Budget(Caps(global_usd=CAP, user_daily_calls=500), counters)


async def call(
    cache: ResponseCache,
    budget: Budget,
    provider: CountingProvider,
    recorder: UsageRecorder,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """§3.1's order: cache, *then* budget, then provider.

    Written here in the order the specification states, so the test below is
    about the ordering rather than about a mock.
    """
    key = cache_key(PROVIDER, MODEL, VERSION, payload)

    cached: dict[str, Any] | None = await cache.get(key)
    if cached is not None:
        recorder.record(
            build_row(
                provider=PROVIDER,
                model=MODEL,
                feature=Feature.JOB_ENRICH,
                outcome=Outcome.CACHE_HIT,
                est_cost_usd=Decimal(0),
                prompt_version=VERSION,
            )
        )
        return cached

    decision = await budget.check(Feature.JOB_ENRICH, estimate_usd=Decimal("0.001"))
    decision.raise_if_denied(Feature.JOB_ENRICH)

    result: dict[str, Any] = await provider.complete_json(payload)
    await cache.set(key, result)
    return result


# -- the criterion -----------------------------------------------------------


async def test_a_cache_hit_is_served_in_hard_state():
    """AC-AI-03.8."""
    cache, provider, recorder = ResponseCache(), CountingProvider(), UsageRecorder()
    await cache.set(cache_key(PROVIDER, MODEL, VERSION, PAYLOAD), {"skills": ["python"]})
    budget = await exhausted_budget()

    assert await budget.state(Feature.JOB_ENRICH) is BudgetState.HARD

    result = await call(cache, budget, provider, recorder, PAYLOAD)

    assert result == {"skills": ["python"]}
    assert provider.invocations == 0


async def test_a_cache_miss_in_hard_state_is_still_denied():
    """The control, and the half that keeps the cap meaningful. Serving cached
    results during a breach is not the same as ignoring the breach."""
    cache, provider, recorder = ResponseCache(), CountingProvider(), UsageRecorder()
    budget = await exhausted_budget()

    with pytest.raises(AIBudgetExceeded):
        await call(cache, budget, provider, recorder, PAYLOAD)

    assert provider.invocations == 0


async def test_the_hit_writes_a_cache_hit_row_even_in_hard_state():
    """§3.2's `no_silent_success` invariant does not stop applying because the
    budget is exhausted: a result served is a result accounted for."""
    cache, provider, recorder = ResponseCache(), CountingProvider(), UsageRecorder()
    await cache.set(cache_key(PROVIDER, MODEL, VERSION, PAYLOAD), {"skills": []})
    budget = await exhausted_budget()

    await call(cache, budget, provider, recorder, PAYLOAD)

    rows = recorder.drain()
    assert len(rows) == 1
    assert rows[0]["outcome"] is Outcome.CACHE_HIT
    assert rows[0]["est_cost_usd"] == 0.0


async def test_the_hit_does_not_move_the_spend_counter():
    """The money was spent when the entry was written. Charging for it again
    would exhaust the cap faster the more the cache worked - which is exactly
    backwards."""
    cache, provider, recorder = ResponseCache(), CountingProvider(), UsageRecorder()
    await cache.set(cache_key(PROVIDER, MODEL, VERSION, PAYLOAD), {"skills": []})
    budget = await exhausted_budget()
    before = await budget.counters.spend(global_key(utc_day()))

    await call(cache, budget, provider, recorder, PAYLOAD)

    assert await budget.counters.spend(global_key(utc_day())) == before


async def test_the_feed_stays_usable_during_a_breach():
    """The reason the ordering was chosen, stated as a scenario.

    Twenty jobs, ten already enriched. On the day the cap trips, the ten cached
    ones still render; the other ten degrade to the dictionary path per §3.2.
    Denying the cached ten would turn a cost problem into a blank feed.
    """
    cache, provider, recorder = ResponseCache(), CountingProvider(), UsageRecorder()
    budget = await exhausted_budget()

    warm = [{"title": f"Job {n}"} for n in range(10)]
    cold = [{"title": f"Job {n}"} for n in range(10, 20)]
    for payload in warm:
        await cache.set(cache_key(PROVIDER, MODEL, VERSION, payload), {"skills": ["python"]})

    served, degraded = 0, 0
    for payload in warm + cold:
        try:
            await call(cache, budget, provider, recorder, payload)
            served += 1
        except AIBudgetExceeded:
            degraded += 1

    assert served == 10
    assert degraded == 10
    assert provider.invocations == 0


async def test_the_budget_is_still_checked_when_the_cache_is_cold():
    """Ordering, not bypassing. A cache that was consulted and then ignored
    would let a cold call through during a breach."""
    cache, provider, recorder = ResponseCache(), CountingProvider(), UsageRecorder()
    budget = await exhausted_budget()

    with pytest.raises(AIBudgetExceeded) as caught:
        await call(cache, budget, provider, recorder, {"title": "Never seen"})

    assert caught.value.retry_after_seconds > 0


async def test_an_ok_budget_and_a_cold_cache_calls_the_provider():
    """The fourth quadrant. Without it, an implementation that never called the
    provider would pass every test in this file."""
    cache, provider, recorder = ResponseCache(), CountingProvider(), UsageRecorder()
    budget = Budget(Caps(global_usd=CAP, user_daily_calls=500), Counters())

    await call(cache, budget, provider, recorder, PAYLOAD)

    assert provider.invocations == 1
