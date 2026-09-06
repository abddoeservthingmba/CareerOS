"""T-FOUND-08.5 - the store is down, so the request does not happen.

`AC-FOUND-08.5`: "Redis being unavailable causes the request to fail closed
(503) rather than proceeding without protection."

The tempting alternative is to log a warning and carry on: the user gets their
pack, the outage is invisible, nobody files anything. It is also the exact
window in which a retrying client is charged twice, because the only thing that
would have stopped it is the store that is down. A 503 asks the client to try
again in a minute. Proceeding asks the user to notice their statement.

The failure is injected rather than staged against a real Redis. A store that
raises on every call is what an unreachable Redis *is* from this module's side,
and taking a container down mid-suite would make this the flakiest test in the
repository for no extra fidelity.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from app.core.errors import ErrorCode
from app.core.idempotency import (
    Idempotency,
    IdempotencyInProgress,
    IdempotencyKeyReuse,
    IdempotencyUnavailable,
    MemoryStore,
    Record,
    Scope,
    State,
)

ALICE = "01J000000000000000000ALICE"
SCOPE = Scope(ALICE, "POST /api/v1/apply/packs", "6f1b0b6e-6d2f-4f0a-9a1f-0e9f6b1a7c21")
BODY = {"job_id": "01J0000000000000000000JOB"}


class Unreachable:
    """Every operation raises what a dead connection raises."""

    def __init__(self, failure: type[Exception] = ConnectionError) -> None:
        self._failure = failure

    async def claim(self, key: str, record: Record, ttl: timedelta) -> Record | None:
        raise self._failure("Error 111 connecting to redis:6379. Connection refused.")

    async def read(self, key: str) -> Record | None:
        raise self._failure("Error 111 connecting to redis:6379. Connection refused.")

    async def finish(self, key: str, record: Record, ttl: timedelta) -> None:
        raise self._failure("Error 111 connecting to redis:6379. Connection refused.")


class FailsOnFinish(MemoryStore):
    """Claims fine, dies before the result can be stored.

    The nastier outage: the side effect *has* happened, and the record of it has
    not.
    """

    async def finish(self, key: str, record: Record, ttl: timedelta) -> None:
        raise ConnectionError("redis went away mid-request")


class Effect:
    def __init__(self) -> None:
        self.runs = 0

    async def __call__(self) -> tuple[int, Any, dict[str, str]]:
        self.runs += 1
        return 201, {"pack_id": "01J000000000000000PACK"}, {}


async def test_an_unreachable_store_fails_the_request():
    """AC-FOUND-08.5."""
    protection, effect = Idempotency(Unreachable()), Effect()

    with pytest.raises(IdempotencyUnavailable):
        await protection.run(SCOPE, BODY, effect)

    assert effect.runs == 0, "the handler ran without protection"


async def test_the_failure_is_a_503():
    protection = Idempotency(Unreachable())
    with pytest.raises(IdempotencyUnavailable) as caught:
        await protection.run(SCOPE, BODY, Effect())

    assert caught.value.http_status == 503
    assert caught.value.code is ErrorCode.SERVICE_UNAVAILABLE


async def test_the_message_tells_the_client_what_to_do():
    """A 503 with no instruction gets retried with a *new* key, which is how a
    fail-closed outage still ends in a double charge."""
    protection = Idempotency(Unreachable())
    with pytest.raises(IdempotencyUnavailable) as caught:
        await protection.run(SCOPE, BODY, Effect())

    message = str(caught.value)
    assert "not attempted" in message
    assert "same Idempotency-Key" in message


@pytest.mark.parametrize(
    "failure", [ConnectionError, TimeoutError, OSError], ids=lambda f: f.__name__
)
async def test_every_kind_of_outage_fails_closed(failure: type[Exception]):
    """A timeout is an outage too, and it is the one that looks like success for
    long enough to be waved through."""
    protection, effect = Idempotency(Unreachable(failure)), Effect()

    with pytest.raises(IdempotencyUnavailable):
        await protection.run(SCOPE, BODY, effect)
    assert effect.runs == 0


async def test_a_store_that_dies_after_the_side_effect_still_reports_failure():
    """The side effect happened and the record did not, so a retry will run it
    again. Reporting success would hide that; reporting failure at least tells
    the client and the operator that something is inconsistent.

    This is the honest answer, not a good one - `AC-FOUND-08.5` covers the
    unavailable store, and this is the sharp edge inside it.
    """
    protection, effect = Idempotency(FailsOnFinish()), Effect()

    with pytest.raises(IdempotencyUnavailable):
        await protection.run(SCOPE, BODY, effect)

    assert effect.runs == 1


async def test_the_modules_own_answers_are_not_mistaken_for_an_outage():
    """A 409 and a 422 are decisions, not failures.

    If the fail-closed wrapper swallowed them into 503s, every duplicate would
    look like an outage and the two conditions `AC-FOUND-08.2` and `.3` describe
    would be unobservable.
    """
    store = MemoryStore()
    protection, effect = Idempotency(store), Effect()

    await protection.run(SCOPE, BODY, effect)
    with pytest.raises(IdempotencyKeyReuse):
        await protection.run(SCOPE, {"job_id": "different"}, effect)

    await store.finish(
        SCOPE.storage_key,
        Record(
            body_hash=(await store.read(SCOPE.storage_key)).body_hash,  # type: ignore[union-attr]
            state=State.IN_PROGRESS,
            claimed_at=(await store.read(SCOPE.storage_key)).claimed_at,  # type: ignore[union-attr]
        ),
        timedelta(minutes=10),
    )
    with pytest.raises(IdempotencyInProgress):
        await protection.run(SCOPE, BODY, effect)

    assert effect.runs == 1


async def test_a_durable_store_outage_also_fails_closed():
    """The durable record is the answer to "did we bill this twice". Losing it
    silently is losing the only source for that question."""
    protection, effect = Idempotency(MemoryStore(), durable=Unreachable()), Effect()

    with pytest.raises(IdempotencyUnavailable):
        await protection.run(SCOPE, BODY, effect, spends_money=True)


async def test_a_working_store_does_not_report_an_outage():
    """The control. Without it, an implementation that raised 503 unconditionally
    would pass every test above."""
    protection, effect = Idempotency(MemoryStore()), Effect()
    status, _, _ = await protection.run(SCOPE, BODY, effect)
    assert status == 201
    assert effect.runs == 1
