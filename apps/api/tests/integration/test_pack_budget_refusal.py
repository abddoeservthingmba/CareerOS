"""T-AI-03.11 - refusing without losing the user's work.

`AC-AI-03.11`: "`pack_generate` refused for budget preserves every prior user
edit and returns a `Retry-After` equal to the seconds remaining until reset."

`pack_generate` is the only one of the ten features that refuses outright
(§3.2), and it is allowed to because the alternative is worse: a cover letter
drafted from a half-exhausted budget on the cheap tier is a worse artifact than
none, and the user is about to send it to an employer.

But refusing is only acceptable under two conditions, and both are this test:

**Every edit survives.** The user has been in that editor. They have rewritten
the opening line, chosen a tone, answered three screening questions. Discarding
that because a *shared* budget ran out - a fact about the system, not about
them - is the kind of thing people do not forgive. §3.2 calls it the
`no_data_loss` invariant.

**The `Retry-After` is true.** "Try again after 14:00" is a promise. If the
number is the wrong side of the UTC boundary, or a fixed 3600, the user comes
back to the same refusal - and stops coming back.
"""

from __future__ import annotations

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
    Caps,
    Counters,
    global_key,
    next_reset,
    utc_day,
)
from app.ai.usage import DenyReason, Outcome, UsageRecorder, build_row
from app.core import clock
from app.core.errors import AppError, ErrorCode

CAP = Decimal("2.00")
USER = "01J000000000000000000USER"
PACK_PATH = "/api/v1/applications/01J0000000000000000APP/pack"

EDITS = {
    "cover_letter": "Dear hiring manager, I have spent four years on payments...",
    "tone": "direct",
    "answers": {"why_us": "Because the problem is one I have actually had."},
}


class PackDraft:
    """The user's in-progress work, as `APPLY-02` will hold it.

    A store rather than a request body, because the point of the criterion is
    that the edits are *already saved* when the refusal happens - a refusal that
    lost work held only in a request would be a refusal that lost work.
    """

    def __init__(self) -> None:
        self.saved: dict[str, Any] = {}

    def save(self, edits: dict[str, Any]) -> None:
        self.saved.update(edits)


async def exhausted_budget(at: datetime | None = None) -> Budget:
    counters = Counters()
    await counters.add_spend(global_key(utc_day(at)), CAP, timedelta(hours=1))
    return Budget(Caps(global_usd=CAP, user_daily_calls=500), counters)


def build_app(settings: Any, budget: Budget, draft: PackDraft, recorder: UsageRecorder) -> FastAPI:
    """`APPLY-02`'s route in the shape §3.2 prescribes for it."""
    from app.main import create_app

    app = create_app(settings)

    @app.post(PACK_PATH, include_in_schema=False)
    async def generate() -> dict[str, Any]:
        decision = await budget.check(
            Feature.PACK_GENERATE, estimate_usd=Decimal("0.02"), user_id=USER
        )
        if not decision.allowed:
            assert decision.reason is not None
            recorder.record(
                build_row(
                    provider="gemini",
                    model="gemini-3.8-flash",
                    feature=Feature.PACK_GENERATE,
                    outcome=Outcome.BUDGET_DENIED,
                    deny_reason=decision.reason,
                    user_id=USER,
                )
            )
            failure = AIBudgetExceeded(Feature.PACK_GENERATE, decision.reason, decision.resets_at)  # type: ignore[arg-type]
            raise AppError(
                "we can't draft this right now",
                code=ErrorCode.AI_BUDGET_EXCEEDED,
                http_status=MATRIX["pack_generate"].http_status or 503,
                headers={"Retry-After": str(failure.retry_after_seconds)},
            )
        return {"pack_id": "01J0000000000000000PACK"}

    @app.get(PACK_PATH, include_in_schema=False)
    async def read() -> dict[str, Any]:
        return draft.saved

    return app


@pytest.fixture
def context(settings_factory):
    async def build() -> tuple[TestClient, PackDraft, UsageRecorder]:
        draft, recorder = PackDraft(), UsageRecorder()
        draft.save(EDITS)
        app = build_app(settings_factory(), await exhausted_budget(), draft, recorder)
        return TestClient(app, raise_server_exceptions=False), draft, recorder

    return build


# -- the criterion -----------------------------------------------------------


async def test_the_refusal_preserves_every_edit(context):
    """AC-AI-03.11, first half - §3.2's `no_data_loss` invariant."""
    client, draft, _ = await context()

    refused = client.post(PACK_PATH)

    assert refused.status_code == 503
    assert client.get(PACK_PATH).json() == EDITS
    assert draft.saved == EDITS


async def test_the_retry_after_is_the_seconds_until_the_utc_reset(context):
    """AC-AI-03.11, second half.

    "Try again after 14:00" is a promise. A fixed 3600, or a number on the wrong
    side of the boundary, brings the user back to the same refusal - and then
    they stop coming back.
    """
    at = datetime(2026, 9, 7, 21, 0, 0, tzinfo=UTC)
    with clock.freeze(at):
        client, _, _ = await context()
        refused = client.post(PACK_PATH)
        expected = int((next_reset() - clock.now()).total_seconds())

    assert refused.headers["Retry-After"] == str(expected)
    assert expected == 3 * 3600


async def test_the_status_and_code_are_the_ones_the_matrix_names(context):
    """§3.2: "`503 ai_budget_exceeded`". A 500 would be indistinguishable from a
    bug; a 429 would say "you are asking too often", which is not what
    happened."""
    client, _, _ = await context()

    refused = client.post(PACK_PATH)

    assert refused.status_code == MATRIX["pack_generate"].http_status
    assert refused.json()["title"] == MATRIX["pack_generate"].error_code
    assert refused.json()["title"] == ErrorCode.AI_BUDGET_EXCEEDED.value


async def test_the_refusal_says_what_the_user_can_do(context):
    """§3.2's user-visible state: "an explicit 'we can't draft this right now,
    try after HH:MM'". A bare 503 gives a user nothing to do but reload."""
    client, _, _ = await context()

    refused = client.post(PACK_PATH)

    assert "can't draft this right now" in refused.json()["detail"]
    assert int(refused.headers["Retry-After"]) > 0


async def test_the_refusal_writes_a_budget_denied_row(context):
    """`no_silent_success`. A refusal nobody recorded is a support ticket with
    no evidence."""
    client, _, recorder = await context()

    client.post(PACK_PATH)

    rows = recorder.drain()
    assert len(rows) == 1
    assert rows[0]["outcome"] is Outcome.BUDGET_DENIED
    assert rows[0]["deny_reason"] is DenyReason.GLOBAL
    assert rows[0]["user_id"] == USER


async def test_repeated_refusals_do_not_erode_the_draft(context):
    """A user who retries three times must not end up with less than they
    started with. The obvious way to break this is to clear the draft on the
    way into the handler."""
    client, draft, _ = await context()

    for _ in range(3):
        assert client.post(PACK_PATH).status_code == 503

    assert draft.saved == EDITS


# -- the idempotency key survives too ----------------------------------------


async def test_the_idempotency_key_is_still_valid_after_a_refusal(settings_factory):
    """§3.2's recovery for this row: "User retries after `Retry-After`; the
    idempotency key is still valid."

    `FOUND-08` records the key *after* the handler succeeds, so a refusal leaves
    it unclaimed - which is what makes the retry the same operation rather than
    a second one.
    """
    from app.core.idempotency import Idempotency, MemoryStore, Scope

    protection = Idempotency(MemoryStore())
    scope = Scope(USER, "POST " + PACK_PATH, "6f1b0b6e-6d2f-4f0a-9a1f-0e9f6b1a7c21")
    budget = await exhausted_budget()

    async def handler() -> tuple[int, Any, dict[str, str]]:
        decision = await budget.check(
            Feature.PACK_GENERATE, estimate_usd=Decimal("0.02"), user_id=USER
        )
        decision.raise_if_denied(Feature.PACK_GENERATE)
        return 201, {"pack_id": "01J0PACK"}, {}

    with pytest.raises(AIBudgetExceeded):
        await protection.run(scope, EDITS, handler)

    # The next day, the same key is still usable and produces the pack.
    tomorrow = clock.now() + timedelta(days=1)
    with clock.freeze(tomorrow):
        status, body, _ = await protection.run(
            scope,
            EDITS,
            lambda: _succeed(),
        )

    assert status == 201
    assert body == {"pack_id": "01J0PACK"}


async def _succeed() -> tuple[int, Any, dict[str, str]]:
    return 201, {"pack_id": "01J0PACK"}, {}


# -- recovery ----------------------------------------------------------------


async def test_the_pack_generates_after_the_reset(settings_factory):
    """The whole point of a `Retry-After` that is true: coming back at the
    stated time works."""
    before = datetime(2026, 9, 7, 23, 0, 0, tzinfo=UTC)
    after = datetime(2026, 9, 8, 0, 0, 1, tzinfo=UTC)

    counters = Counters()
    budget = Budget(Caps(global_usd=CAP, user_daily_calls=500), counters)
    draft, recorder = PackDraft(), UsageRecorder()
    draft.save(EDITS)

    with clock.freeze(before):
        await counters.add_spend(global_key(utc_day()), CAP, timedelta(hours=2))
        client = TestClient(
            build_app(settings_factory(), budget, draft, recorder),
            raise_server_exceptions=False,
        )
        assert client.post(PACK_PATH).status_code == 503

    with clock.freeze(after):
        generated = client.post(PACK_PATH)

    assert generated.status_code == 200
    assert generated.json()["pack_id"] == "01J0000000000000000PACK"
    assert draft.saved == EDITS
