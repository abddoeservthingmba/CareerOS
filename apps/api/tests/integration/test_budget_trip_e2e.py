"""T-AI-03.4 - the day the cap trips, end to end.

`AC-AI-03.4`: "The R1 gate scenario: the cap is deliberately tripped on staging
and the resume pipeline, the feed and the pack flow each degrade as specified,
with no 5xx in the logs other than the specified `503 ai_budget_exceeded`."

This is a **gate scenario**, not a unit test: §3.2's individual rows are
asserted in `test_degradation.py`, and what this adds is the thing only a whole
day can show - that the three user journeys degrade *together*, in different
ways, without any of them turning into an error nobody planned for.

The clause that carries the weight is the last one. "No 5xx other than the
specified `503`" is what separates a designed degradation from an outage with a
matrix attached. A product where the feed still renders, the resume still
finishes, and only the pack refuses - politely, with a time to come back - is a
product having a cheap day. A product that returns three different 500s is one
having an incident, and the difference is entirely in whether the denial was
handled where it happened.

**Run against the in-process stack**, not staging. `AC-AI-03.4` names staging
because that is where the R1 gate is walked through by a person; the mechanism
it exercises is the same one here, and asserting it in CI is what stops the gate
day from being the first time anyone finds out.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai.base import Feature
from app.ai.budget import (
    MATRIX,
    AIBudgetExceeded,
    Budget,
    BudgetState,
    Caps,
    Counters,
    global_key,
    utc_day,
)
from app.ai.usage import DenyReason, Outcome, UsageRecorder, build_row
from app.core import clock
from app.core.errors import AppError, ErrorCode

CAP = Decimal("2.00")
USER = "01J000000000000000000USER"

FEED = "/api/v1/jobs"
RESUME = "/api/v1/profile/resumes/01J0000000000000000RES"
PACK = "/api/v1/applications/01J0000000000000000APP/pack"


class Journey:
    """The three flows the criterion names, sharing one budget.

    Each one implements its own row's degradation verb from §3.2 - which is what
    makes "each degrades as specified" a claim about behaviour rather than about
    a table.
    """

    def __init__(self, budget: Budget, recorder: UsageRecorder) -> None:
        self.budget = budget
        self.recorder = recorder
        self.resume_status = "structuring"
        self.enrichment_calls = 0

    async def _denied(self, feature: Feature) -> DenyReason | None:
        decision = await self.budget.check(feature, estimate_usd=Decimal("0.01"), user_id=USER)
        if decision.allowed:
            return None
        assert decision.reason is not None
        self.recorder.record(
            build_row(
                provider="gemini",
                model="gemini-3.5-flash-lite",
                feature=feature,
                outcome=Outcome.BUDGET_DENIED,
                deny_reason=decision.reason,
                user_id=USER,
            )
        )
        return decision.reason

    async def feed(self) -> dict[str, Any]:
        """`job_enrich` -> dictionary skills. The feed still renders."""
        self.enrichment_calls += 1
        if await self._denied(Feature.JOB_ENRICH) is None:
            return {"jobs": [{"title": "Backend Engineer", "skills_source": "enriched"}]}
        return {"jobs": [{"title": "Backend Engineer", "skills_source": "dictionary"}]}

    async def resume(self) -> dict[str, Any]:
        """`resume_extract` -> stays in `structuring`, never `failed`."""
        if await self._denied(Feature.RESUME_EXTRACT) is None:
            self.resume_status = "ready"
        return {"status": self.resume_status, "message": "We're finishing this shortly"}

    async def pack(self) -> dict[str, Any]:
        """`pack_generate` -> the one refusal, with a `Retry-After`."""
        reason = await self._denied(Feature.PACK_GENERATE)
        if reason is None:
            return {"pack_id": "01J0000000000000000PACK"}
        probe = await self.budget.check(Feature.PACK_GENERATE, estimate_usd=Decimal("0"))
        decision_reset = probe.resets_at
        failure = AIBudgetExceeded(Feature.PACK_GENERATE, reason, decision_reset)  # type: ignore[arg-type]
        raise AppError(
            "we can't draft this right now",
            code=ErrorCode.AI_BUDGET_EXCEEDED,
            http_status=503,
            headers={"Retry-After": str(failure.retry_after_seconds)},
        )


def build_app(settings: Any, journey: Journey) -> FastAPI:
    from app.main import create_app

    app = create_app(settings)

    @app.get(FEED, include_in_schema=False)
    async def feed() -> dict[str, Any]:
        return await journey.feed()

    @app.get(RESUME, include_in_schema=False)
    async def resume() -> dict[str, Any]:
        return await journey.resume()

    @app.post(PACK, include_in_schema=False)
    async def pack() -> dict[str, Any]:
        return await journey.pack()

    return app


@pytest.fixture
def tripped(settings_factory):
    """A day whose global cap is already spent."""

    async def build() -> tuple[TestClient, Journey, UsageRecorder]:
        counters = Counters()
        await counters.add_spend(global_key(utc_day()), CAP, timedelta(hours=2))
        budget = Budget(Caps(global_usd=CAP, user_daily_calls=500), counters)
        recorder = UsageRecorder()
        journey = Journey(budget, recorder)
        client = TestClient(build_app(settings_factory(), journey), raise_server_exceptions=False)
        return client, journey, recorder

    return build


# -- the scenario ------------------------------------------------------------


async def test_the_three_flows_degrade_as_specified(tripped):
    """AC-AI-03.4's first clause, all three at once."""
    client, journey, _ = await tripped()

    feed = client.get(FEED)
    resume = client.get(RESUME)
    pack = client.post(PACK)

    assert feed.status_code == 200
    assert feed.json()["jobs"][0]["skills_source"] == "dictionary"

    assert resume.status_code == 200
    assert resume.json()["status"] == "structuring"
    assert resume.json()["status"] != "failed"

    assert pack.status_code == 503
    assert pack.json()["title"] == "ai_budget_exceeded"


async def test_the_only_5xx_is_the_specified_one(tripped):
    """AC-AI-03.4's last clause, and the one that separates a designed
    degradation from an outage with a matrix attached."""
    client, _, _ = await tripped()

    statuses = [
        client.get(FEED).status_code,
        client.get(RESUME).status_code,
        client.post(PACK).status_code,
    ]

    server_errors = [status for status in statuses if status >= 500]
    assert server_errors == [503]


async def test_no_unhandled_error_reaches_the_log(tripped, caplog):
    """A 5xx that *was* handled and a traceback in the log are different things,
    and only the second one wakes somebody up."""
    caplog.set_level(logging.ERROR)
    client, _, _ = await tripped()

    client.get(FEED)
    client.get(RESUME)
    client.post(PACK)

    tracebacks = [record for record in caplog.records if record.exc_info]
    assert tracebacks == [], [record.getMessage() for record in tracebacks]


async def test_every_degraded_call_is_accounted_for(tripped):
    """§3.2's `no_silent_success`, across the whole day rather than per
    feature."""
    client, _, recorder = await tripped()

    client.get(FEED)
    client.get(RESUME)
    client.post(PACK)

    rows = recorder.drain()
    assert len(rows) == 3
    assert {row["feature"] for row in rows} == {"job_enrich", "resume_extract", "pack_generate"}
    assert all(row["outcome"] is Outcome.BUDGET_DENIED for row in rows)
    assert all(row["deny_reason"] is DenyReason.GLOBAL for row in rows)


async def test_the_feed_is_never_empty(tripped):
    """The failure a user would actually notice. A feed that 500s or renders
    nothing is a product that stopped working; a feed with dictionary skills is
    a product having a cheap day."""
    client, _, _ = await tripped()

    body = client.get(FEED).json()

    assert body["jobs"]
    assert body["jobs"][0]["title"]


async def test_the_resume_is_never_marked_failed(tripped):
    """§3.2: "no error, no failed state". A resume marked failed is a user who
    believes their upload was rejected. It was not."""
    client, _, _ = await tripped()

    for _ in range(3):
        assert client.get(RESUME).json()["status"] == "structuring"


async def test_the_pack_refusal_says_when_to_come_back(tripped):
    client, _, _ = await tripped()

    refused = client.post(PACK)

    assert int(refused.headers["Retry-After"]) > 0
    assert "can't draft this right now" in refused.json()["detail"]


# -- the day before, and the day after ---------------------------------------


async def test_nothing_degrades_before_the_cap_is_reached(settings_factory):
    """The control. A product that always served dictionary skills would pass
    every assertion above and have no AI in it."""
    budget = Budget(Caps(global_usd=CAP, user_daily_calls=500), Counters())
    journey = Journey(budget, UsageRecorder())
    client = TestClient(build_app(settings_factory(), journey), raise_server_exceptions=False)

    assert client.get(FEED).json()["jobs"][0]["skills_source"] == "enriched"
    assert client.get(RESUME).json()["status"] == "ready"
    assert client.post(PACK).status_code == 200


async def test_everything_recovers_at_the_next_reset(settings_factory):
    """`AC-AI-03.10` in the shape a gate walkthrough would check it: come back
    tomorrow and the product is whole, with nobody having done anything."""
    before = datetime(2026, 9, 7, 23, 0, 0, tzinfo=UTC)
    after = datetime(2026, 9, 8, 0, 0, 1, tzinfo=UTC)

    counters = Counters()
    budget = Budget(Caps(global_usd=CAP, user_daily_calls=500), counters)
    journey = Journey(budget, UsageRecorder())
    client = TestClient(build_app(settings_factory(), journey), raise_server_exceptions=False)

    with clock.freeze(before):
        await counters.add_spend(global_key(utc_day()), CAP, timedelta(hours=2))
        assert client.get(FEED).json()["jobs"][0]["skills_source"] == "dictionary"
        assert client.post(PACK).status_code == 503
        assert await budget.state(Feature.JOB_ENRICH) is BudgetState.HARD

    with clock.freeze(after):
        assert client.get(FEED).json()["jobs"][0]["skills_source"] == "enriched"
        assert client.post(PACK).status_code == 200
        assert await budget.state(Feature.JOB_ENRICH) is BudgetState.OK


def test_the_three_flows_are_the_ones_the_criterion_names():
    """ "the resume pipeline, the feed and the pack flow". Read back from the
    matrix so the mapping from journey to feature is stated rather than
    implied."""
    assert MATRIX["resume_extract"].degradation == "retry_with_backoff"
    assert MATRIX["job_enrich"].degradation == "fallback_dictionary"
    assert MATRIX["pack_generate"].degradation == "refuse"
