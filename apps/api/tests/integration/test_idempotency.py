"""T-FOUND-08.1-.3 - a retried request has one side effect.

`AC-FOUND-08.1`: "The same key sent twice sequentially produces one side effect
and two identical response bodies, the second carrying `Idempotent-Replay:
true`."
`AC-FOUND-08.2`: "The same key sent twice concurrently produces one side effect;
the loser gets 409."
`AC-FOUND-08.3`: "The same key with a changed body gets 422 and produces no side
effect."

Every test here counts the side effect rather than inspecting the record.
Asserting that a key was stored proves the bookkeeping; asserting that the
handler ran once proves the thing the user cares about, which is that they were
charged once. When those two ever disagree, the count is right and the
bookkeeping is the bug.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest

from app.core import clock
from app.core.idempotency import (
    IN_PROGRESS_TTL,
    REPLAY_HEADER,
    TTL,
    Idempotency,
    IdempotencyInProgress,
    IdempotencyKeyReuse,
    MemoryStore,
    Scope,
    body_hash,
)

ALICE = "01J000000000000000000ALICE"
BOB = "01J00000000000000000000BOB"
ROUTE = "POST /api/v1/apply/packs"
KEY = "6f1b0b6e-6d2f-4f0a-9a1f-0e9f6b1a7c21"
BODY = {"job_id": "01J0000000000000000000JOB", "tone": "direct"}


class Effect:
    """A handler that records every time it runs.

    A counter rather than a mock, because the assertion this file makes is
    always "how many times", and a mock's call list invites asserting on
    arguments instead - which is the bookkeeping again.
    """

    def __init__(self, status: int = 201, body: Any = None, headers: Any = None) -> None:
        self.runs = 0
        self._status = status
        self._body = body if body is not None else {"pack_id": "01J000000000000000PACK"}
        self._headers = headers or {"Location": "/api/v1/apply/packs/01J000000000000000PACK"}
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.blocking = False

    async def __call__(self) -> tuple[int, Any, dict[str, str]]:
        self.runs += 1
        if self.blocking:
            self.started.set()
            await self.release.wait()
        return self._status, self._body, dict(self._headers)


def guard(**kwargs: Any) -> Idempotency:
    return Idempotency(MemoryStore(), **kwargs)


def scope(key: str = KEY, user: str = ALICE, route: str = ROUTE) -> Scope:
    return Scope(user_id=user, route=route, key=key)


# -- AC-FOUND-08.1: the sequential retry -------------------------------------


async def test_the_same_key_twice_runs_the_handler_once():
    """AC-FOUND-08.1, the side effect."""
    protection, effect = guard(), Effect()

    first = await protection.run(scope(), BODY, effect)
    second = await protection.run(scope(), BODY, effect)

    assert effect.runs == 1, "the handler ran twice"
    assert first[0] == second[0] == 201
    assert first[1] == second[1]


async def test_the_replay_says_it_is_a_replay():
    """AC-FOUND-08.1, the header.

    Without it a client cannot tell "my retry worked" from "my retry created a
    second one", which is the exact ambiguity the retry was trying to resolve.
    """
    protection, effect = guard(), Effect()

    _, _, first_headers = await protection.run(scope(), BODY, effect)
    _, _, second_headers = await protection.run(scope(), BODY, effect)

    assert REPLAY_HEADER not in first_headers
    assert second_headers[REPLAY_HEADER] == "true"


async def test_the_replay_carries_the_original_headers():
    """A `Location` the client follows must survive the replay, or the retry
    succeeds and the client still cannot find what it made."""
    protection, effect = guard(), Effect()

    await protection.run(scope(), BODY, effect)
    _, _, headers = await protection.run(scope(), BODY, effect)

    assert headers["Location"] == "/api/v1/apply/packs/01J000000000000000PACK"


async def test_the_replay_reproduces_the_original_status():
    """§8: "the **original response body and status**". A 201 replayed as 200
    tells a client it found something rather than made it."""
    protection = guard()
    await protection.run(scope(), BODY, Effect(status=202, body={"queued": True}))
    status, body, _ = await protection.run(scope(), BODY, Effect(status=500, body={"no": True}))

    assert status == 202
    assert body == {"queued": True}


async def test_ten_retries_still_run_once():
    protection, effect = guard(), Effect()
    for _ in range(10):
        await protection.run(scope(), BODY, effect)
    assert effect.runs == 1


# -- the scope ---------------------------------------------------------------


async def test_a_different_user_with_the_same_key_is_a_different_request():
    """§8: "Key scope is `(user_id, route, key)`."

    Two clients generating the same UUID is not the case that matters; a client
    that reuses one key for a user across a sign-out is. Either way, one user's
    key must never replay another's response - that would be a data leak wearing
    a cache's clothes.
    """
    protection, effect = guard(), Effect()

    await protection.run(scope(user=ALICE), BODY, effect)
    _, _, headers = await protection.run(scope(user=BOB), BODY, effect)

    assert effect.runs == 2
    assert REPLAY_HEADER not in headers


async def test_the_same_key_on_a_different_route_is_a_different_request():
    protection, effect = guard(), Effect()

    await protection.run(scope(route="POST /api/v1/apply/packs"), BODY, effect)
    await protection.run(scope(route="POST /api/v1/reminders"), BODY, effect)

    assert effect.runs == 2


async def test_a_different_key_is_a_different_request():
    protection, effect = guard(), Effect()

    await protection.run(scope(key="key-one"), BODY, effect)
    await protection.run(scope(key="key-two"), BODY, effect)

    assert effect.runs == 2


def test_a_blank_key_is_refused():
    with pytest.raises(ValueError, match="blank"):
        Scope(ALICE, ROUTE, "   ")


def test_an_absurdly_long_key_is_refused():
    """A key is an identifier, not a place to put a payload."""
    with pytest.raises(ValueError, match="at most"):
        Scope(ALICE, ROUTE, "x" * 5000)


# -- AC-FOUND-08.2: the concurrent duplicate ---------------------------------


async def test_a_concurrent_duplicate_gets_409_and_the_handler_runs_once():
    """AC-FOUND-08.2.

    The second request arrives while the first is inside the handler - the
    window a check-then-set implementation loses, and the only window that
    matters. The handler is held open explicitly rather than raced by timing,
    so this fails deterministically if the claim stops being atomic.
    """
    protection, effect = guard(), Effect()
    effect.blocking = True

    winner = asyncio.create_task(protection.run(scope(), BODY, effect))
    await asyncio.wait_for(effect.started.wait(), timeout=2)

    with pytest.raises(IdempotencyInProgress):
        await protection.run(scope(), BODY, effect)

    effect.release.set()
    await winner
    assert effect.runs == 1


async def test_the_winner_still_completes_normally():
    """A 409 for the loser is only correct if the winner's answer arrives."""
    protection, effect = guard(), Effect()
    effect.blocking = True

    winner = asyncio.create_task(protection.run(scope(), BODY, effect))
    await asyncio.wait_for(effect.started.wait(), timeout=2)
    with pytest.raises(IdempotencyInProgress):
        await protection.run(scope(), BODY, effect)
    effect.release.set()

    status, body, headers = await winner
    assert status == 201
    assert REPLAY_HEADER not in headers


async def test_many_concurrent_duplicates_produce_one_side_effect():
    """AC-FOUND-08.2 at the scale a retrying mobile client actually produces."""
    protection, effect = guard(), Effect()
    effect.blocking = True

    winner = asyncio.create_task(protection.run(scope(), BODY, effect))
    await asyncio.wait_for(effect.started.wait(), timeout=2)

    losers = await asyncio.gather(
        *(protection.run(scope(), BODY, effect) for _ in range(20)),
        return_exceptions=True,
    )
    effect.release.set()
    await winner

    assert effect.runs == 1
    assert all(isinstance(outcome, IdempotencyInProgress) for outcome in losers)


async def test_a_retry_after_completion_replays_rather_than_409s():
    """The `in_progress` answer must not outlive the request it describes."""
    protection, effect = guard(), Effect()
    await protection.run(scope(), BODY, effect)

    _, _, headers = await protection.run(scope(), BODY, effect)
    assert headers[REPLAY_HEADER] == "true"


# -- AC-FOUND-08.3: the changed body -----------------------------------------


async def test_the_same_key_with_a_changed_body_is_422_with_no_side_effect():
    """AC-FOUND-08.3."""
    protection, effect = guard(), Effect()
    await protection.run(scope(), BODY, effect)

    with pytest.raises(IdempotencyKeyReuse):
        await protection.run(scope(), {**BODY, "tone": "warm"}, effect)

    assert effect.runs == 1


async def test_a_changed_body_is_422_even_while_the_first_is_running():
    """The body-hash check comes before the state check, on purpose: 409 tells
    the client to retry, and this request will never be accepted."""
    protection, effect = guard(), Effect()
    effect.blocking = True

    winner = asyncio.create_task(protection.run(scope(), BODY, effect))
    await asyncio.wait_for(effect.started.wait(), timeout=2)

    with pytest.raises(IdempotencyKeyReuse):
        await protection.run(scope(), {"job_id": "other"}, effect)

    effect.release.set()
    await winner
    assert effect.runs == 1


async def test_a_reordered_body_is_the_same_body():
    """Two JSON encodings of one object are one request. Hashing the raw bytes
    of a re-serialised body would make every retry a 422."""
    protection, effect = guard(), Effect()

    await protection.run(scope(), {"a": 1, "b": 2}, effect)
    _, _, headers = await protection.run(scope(), {"b": 2, "a": 1}, effect)

    assert effect.runs == 1
    assert headers[REPLAY_HEADER] == "true"


def test_the_body_hash_is_stable_across_encodings():
    assert body_hash({"a": 1, "b": 2}) == body_hash({"b": 2, "a": 1})
    assert body_hash(None) == body_hash(b"")
    assert body_hash("x") == body_hash(b"x")
    assert body_hash({"a": 1}) != body_hash({"a": 2})


async def test_an_empty_body_is_a_body():
    """A `POST` with no body still gets one side effect per key."""
    protection, effect = guard(), Effect()
    await protection.run(scope(), None, effect)
    await protection.run(scope(), None, effect)
    assert effect.runs == 1


# -- expiry ------------------------------------------------------------------


async def test_the_record_expires_after_twenty_four_hours():
    """§8's window. After it, the same key is a new request - which is correct:
    a client retrying a day later is not retrying, it is asking again."""
    protection, effect = guard(), Effect()
    start = clock.now()

    with clock.freeze(start):
        await protection.run(scope(), BODY, effect)
    with clock.freeze(start + TTL - timedelta(minutes=1)):
        await protection.run(scope(), BODY, effect)
        assert effect.runs == 1
    with clock.freeze(start + TTL + timedelta(seconds=1)):
        await protection.run(scope(), BODY, effect)

    assert effect.runs == 2


async def test_a_crashed_request_does_not_lock_the_key_for_a_day():
    """A claim left by a killed process means nothing, and at the completed
    record's 24 h it would answer every retry with 409 for a day.

    The claim is *not* released on the exception: this layer cannot know whether
    the failure happened before or after the side effect, and assuming "before"
    is how the double charge gets back in. The short claim TTL is what keeps
    that honest rather than punitive.
    """
    protection = guard()
    start = clock.now()

    async def explode() -> tuple[int, Any, dict[str, str]]:
        raise RuntimeError("the process died here")

    with clock.freeze(start), pytest.raises(RuntimeError):
        await protection.run(scope(), BODY, explode)

    effect = Effect()
    with clock.freeze(start + timedelta(minutes=1)):
        with pytest.raises(IdempotencyInProgress):
            await protection.run(scope(), BODY, effect)
        assert effect.runs == 0

    with clock.freeze(start + IN_PROGRESS_TTL + timedelta(seconds=1)):
        await protection.run(scope(), BODY, effect)
    assert effect.runs == 1


# -- the durable record ------------------------------------------------------


async def test_a_spending_request_is_recorded_durably():
    """§8: "plus a durable record for anything that spent money".

    Redis is a cache with a TTL. A charge that outlives it must still be
    answerable, or the reconciliation question "did we bill this twice" has no
    source.
    """
    durable = MemoryStore()
    protection = Idempotency(MemoryStore(), durable=durable)

    await protection.run(scope(), BODY, Effect(), spends_money=True)

    assert len(durable) == 1
    record = await durable.read(scope().storage_key)
    assert record is not None
    assert record.spent is True


async def test_a_free_request_is_not_recorded_durably():
    """The durable record is for money. Writing one for every request would make
    it noise, and the reconciliation question unanswerable again."""
    durable = MemoryStore()
    protection = Idempotency(MemoryStore(), durable=durable)

    await protection.run(scope(), BODY, Effect(), spends_money=False)

    assert len(durable) == 0


# -- the Redis store ---------------------------------------------------------


def redis_backed() -> Idempotency:
    """The store a deployment actually uses, against a real Redis in process.

    `fakeredis` implements the server, not a stub of this module's assumptions.
    That matters here more than anywhere else in the file: `RedisStore.claim` is
    one `SET key value NX PX ttl`, and its whole correctness argument is that
    Redis makes it atomic. Asserting that against a double I wrote would be
    asserting my own belief back at myself.
    """
    from fakeredis import FakeAsyncRedis

    from app.core.idempotency import RedisStore

    return Idempotency(RedisStore(FakeAsyncRedis()))


async def test_redis_the_same_key_twice_runs_the_handler_once():
    """AC-FOUND-08.1, against Redis."""
    protection, effect = redis_backed(), Effect()

    first = await protection.run(scope(), BODY, effect)
    _, _, headers = await protection.run(scope(), BODY, effect)

    assert effect.runs == 1
    assert headers[REPLAY_HEADER] == "true"
    assert first[1] == {"pack_id": "01J000000000000000PACK"}


async def test_redis_replays_the_status_body_and_headers():
    """The record survives a JSON round trip through Redis, which the in-memory
    store never exercises - it hands back the same object."""
    protection = redis_backed()
    await protection.run(scope(), BODY, Effect(status=202, body={"queued": True}))
    status, body, headers = await protection.run(scope(), BODY, Effect())

    assert status == 202
    assert body == {"queued": True}
    assert headers["Location"] == "/api/v1/apply/packs/01J000000000000000PACK"
    assert headers[REPLAY_HEADER] == "true"


async def test_redis_a_concurrent_duplicate_gets_409():
    """AC-FOUND-08.2, against Redis - the case `SET ... NX` exists for."""
    protection, effect = redis_backed(), Effect()
    effect.blocking = True

    winner = asyncio.create_task(protection.run(scope(), BODY, effect))
    await asyncio.wait_for(effect.started.wait(), timeout=2)

    with pytest.raises(IdempotencyInProgress):
        await protection.run(scope(), BODY, effect)

    effect.release.set()
    await winner
    assert effect.runs == 1


async def test_redis_a_changed_body_is_422():
    """AC-FOUND-08.3, against Redis."""
    protection, effect = redis_backed(), Effect()
    await protection.run(scope(), BODY, effect)

    with pytest.raises(IdempotencyKeyReuse):
        await protection.run(scope(), {"job_id": "other"}, effect)
    assert effect.runs == 1


async def test_redis_sets_a_ttl_on_every_record():
    """§8's 24 h. A record with no TTL is a leak that only shows up as a memory
    graph six months later."""
    from fakeredis import FakeAsyncRedis

    from app.core.idempotency import RedisStore

    client = FakeAsyncRedis()
    protection, effect = Idempotency(RedisStore(client)), Effect()

    await protection.run(scope(), BODY, effect)

    remaining = await client.pttl(scope().storage_key)
    assert 0 < remaining <= TTL.total_seconds() * 1000


async def test_redis_gives_the_claim_the_shorter_ttl():
    """The claim and the completed record expire on different clocks, and the
    claim's is what stops a crash locking the key for a day."""
    from fakeredis import FakeAsyncRedis

    from app.core.idempotency import RedisStore

    client = FakeAsyncRedis()
    protection, effect = Idempotency(RedisStore(client)), Effect()
    effect.blocking = True

    running = asyncio.create_task(protection.run(scope(), BODY, effect))
    await asyncio.wait_for(effect.started.wait(), timeout=2)
    claimed = await client.pttl(scope().storage_key)

    effect.release.set()
    await running

    assert 0 < claimed <= IN_PROGRESS_TTL.total_seconds() * 1000
    assert await client.pttl(scope().storage_key) > IN_PROGRESS_TTL.total_seconds() * 1000
