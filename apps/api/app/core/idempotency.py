"""Request idempotency - `FOUND-08`.

`01-foundations.md` §8: "A retried request never causes a second side effect - a
second pack generation, a second AI charge, a second reminder."

The failure this prevents is not exotic. A user on a train taps *Generate pack*,
the response is lost to a dead cell, the client retries, and the account is
charged twice for two packs the user did not ask for. Nothing in the server saw
anything wrong: both requests were valid, authenticated and well-formed. The only
thing that distinguishes them is a key the client sent with both.

Four states, and the reason each answers the way it does.

**Fresh.** No record for `(user_id, route, key)`. Claim it as `in_progress` and
run. The claim is atomic - a set-if-absent, never a read followed by a write -
because the whole point is the two-requests-at-once case, and a check-then-set
loses exactly that race.

**In progress.** A duplicate arrived while the first is still running. `409
idempotency_in_progress`. Not a wait, and not a replay of a result that does not
exist yet: making the second request block would hold a connection for as long as
the first takes, which on pack generation is an AI call.

**Completed.** Replay the original status and body verbatim, with
`Idempotent-Replay: true`. Verbatim matters - a client that retried and got a
*differently shaped* success cannot tell whether its first attempt landed.

**Body changed.** Same key, different body hash: `422 idempotency_key_reuse`,
and no side effect. This is a client bug - a key reused across two genuinely
different requests - and serving either one would be wrong. Refusing is the only
answer that cannot silently do the wrong thing.

**And if the store is down**, the request fails with 503 rather than proceeding
(`AC-FOUND-08.5`). Running without protection is how the double charge happens,
so an outage of the thing that prevents it is not a reason to stop preventing it.

`ARQ` tasks are idempotent separately, by their own natural key (§10). This layer
covers one HTTP request; a task the worker retries never reaches it.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol, Self

from fastapi import Request

from app.core import clock
from app.core.errors import AppError, ErrorCode

logger = logging.getLogger("app.idempotency")

#: §8: "Stored in Redis with a 24 h TTL". That is the *completed* record - the
#: window in which a retry gets its replay.
TTL = timedelta(hours=24)

#: The `in_progress` claim expires far sooner, and this is not a tuning knob.
#: §8 gives `in_progress` one meaning: "a request with this key is still
#: running". A process killed mid-request leaves a claim that means nothing, and
#: at the completed record's 24 h it would answer every retry with 409 for a
#: day. Ten minutes is longer than any request this API makes - the slowest is a
#: pack generation behind an AI call - and short enough that a crash costs a
#: coffee break rather than a support ticket.
IN_PROGRESS_TTL = timedelta(minutes=10)

#: The header a client sends, and the one it gets back on a replay.
KEY_HEADER = "Idempotency-Key"
REPLAY_HEADER = "Idempotent-Replay"

#: Long enough for a UUID, a ULID, or a client that prefixes one; short enough
#: that a key is never a place to smuggle a payload.
MAX_KEY_LENGTH = 200


class State(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


# -- the failures -----------------------------------------------------------


class IdempotencyInProgress(AppError):
    """`AC-FOUND-08.2` - the concurrent duplicate loses.

    409 rather than blocking until the winner finishes: waiting would hold a
    connection open for the length of an AI call, and a client that retried
    because it thought the first attempt was lost is exactly the client least
    able to wait.
    """

    code = ErrorCode.IDEMPOTENCY_IN_PROGRESS
    http_status = 409


class IdempotencyKeyReuse(AppError):
    """`AC-FOUND-08.3` - the same key with a different body.

    422, and no side effect. A client that reuses a key across two different
    requests has a bug; serving either request would be a guess about which one
    it meant.
    """

    code = ErrorCode.IDEMPOTENCY_KEY_REUSE
    http_status = 422


class IdempotencyUnavailable(AppError):
    """`AC-FOUND-08.5` - fail closed.

    Proceeding without the store is proceeding without the protection, which is
    the double charge this module exists to prevent. A 503 asks the client to
    retry; running unprotected asks the user to notice their statement.
    """

    code = ErrorCode.SERVICE_UNAVAILABLE
    http_status = 503


# -- the record --------------------------------------------------------------


@dataclass(frozen=True)
class Scope:
    """§8: "Key scope is `(user_id, route, key)`."

    Scoped by user so one client's key cannot collide with - or probe for -
    another's. Scoped by route so a key reused across two endpoints is two
    independent operations rather than a replay of the wrong one.
    """

    user_id: str
    route: str
    key: str

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("an idempotency key must not be blank")
        if len(self.key) > MAX_KEY_LENGTH:
            raise ValueError(f"an idempotency key is at most {MAX_KEY_LENGTH} characters")

    @property
    def storage_key(self) -> str:
        # Hashed rather than concatenated: the parts are user-supplied and a
        # separator in a raw key is a way to make two different scopes collide.
        digest = hashlib.sha256(
            "\x00".join((self.user_id, self.route, self.key)).encode("utf-8")
        ).hexdigest()
        return f"idem:{digest}"


@dataclass(frozen=True)
class Record:
    """What was claimed, and - once it finishes - what was answered."""

    body_hash: str
    state: State
    claimed_at: datetime
    status_code: int | None = None
    body: Any = None
    #: `AC-FOUND-08.1`'s "identical response bodies" includes the headers a
    #: client acts on, so the ones the route set are replayed too.
    headers: dict[str, str] = field(default_factory=dict)
    spent: bool = False

    def to_json(self) -> str:
        return json.dumps(
            {
                "h": self.body_hash,
                "s": str(self.state),
                "t": self.claimed_at.isoformat(),
                "c": self.status_code,
                "b": self.body,
                "x": self.headers,
                "p": self.spent,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, raw: str) -> Self:
        body = json.loads(raw)
        return cls(
            body_hash=body["h"],
            state=State(body["s"]),
            claimed_at=datetime.fromisoformat(body["t"]),
            status_code=body["c"],
            body=body["b"],
            headers=body.get("x") or {},
            spent=body.get("p", False),
        )


def body_hash(body: bytes | str | Mapping[str, Any] | None) -> str:
    """A stable digest of the request body.

    A mapping is dumped with sorted keys, because two JSON encodings of the same
    object differ in whitespace and key order and neither is a different
    request. Raw bytes are hashed as they arrived, which is the honest thing for
    a body this layer does not parse.
    """
    if body is None:
        payload = b""
    elif isinstance(body, bytes):
        payload = body
    elif isinstance(body, str):
        payload = body.encode("utf-8")
    else:
        payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# -- the store ---------------------------------------------------------------


class IdempotencyStore(Protocol):
    """The three operations this module needs, and no others.

    `claim` must be atomic - set-if-absent in one round trip. A `get` followed
    by a `set` loses the concurrent case, which is the only case that matters.
    """

    async def claim(self, key: str, record: Record, ttl: timedelta) -> Record | None:
        """Store `record` if nothing is there. Return the existing one if there is."""
        ...

    async def read(self, key: str) -> Record | None: ...

    async def finish(self, key: str, record: Record, ttl: timedelta) -> None: ...


class MemoryStore:
    """One process, no Redis.

    Correct for a single worker, which is local development and every test.
    Wrong the moment two containers serve the same user, which is why
    `RedisStore` exists and why the setting that selects one is not a
    convenience.
    """

    def __init__(self) -> None:
        self._records: dict[str, tuple[Record, datetime]] = {}

    def _live(self, key: str) -> Record | None:
        entry = self._records.get(key)
        if entry is None:
            return None
        record, expires = entry
        if clock.now() >= expires:
            del self._records[key]
            return None
        return record

    async def claim(self, key: str, record: Record, ttl: timedelta) -> Record | None:
        existing = self._live(key)
        if existing is not None:
            return existing
        self._records[key] = (record, clock.now() + ttl)
        return None

    async def read(self, key: str) -> Record | None:
        return self._live(key)

    async def finish(self, key: str, record: Record, ttl: timedelta) -> None:
        self._records[key] = (record, clock.now() + ttl)

    def __len__(self) -> int:
        return len(self._records)


class RedisStore:
    """§8's store.

    `SET key value NX PX ttl` is the claim: one round trip, atomic by
    definition, and it returns whether it won. That is the entire concurrency
    argument, and it is why this is not implemented as `GET` then `SET`.

    The client is injected rather than constructed here (§2: no module reads the
    environment), which is also what lets the failure path be tested without
    taking a real Redis down.
    """

    def __init__(self, client: Any) -> None:
        self._redis = client

    async def claim(self, key: str, record: Record, ttl: timedelta) -> Record | None:
        won = await self._redis.set(
            key, record.to_json(), nx=True, px=int(ttl.total_seconds() * 1000)
        )
        if won:
            return None
        existing = await self._redis.get(key)
        if existing is None:
            # The record expired between the failed claim and the read. Treat it
            # as ours: the alternative is a 409 for a key nothing holds.
            return await self.claim(key, record, ttl)
        return Record.from_json(_text(existing))

    async def read(self, key: str) -> Record | None:
        raw = await self._redis.get(key)
        return None if raw is None else Record.from_json(_text(raw))

    async def finish(self, key: str, record: Record, ttl: timedelta) -> None:
        await self._redis.set(key, record.to_json(), px=int(ttl.total_seconds() * 1000))


def _text(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


# -- the guard ---------------------------------------------------------------


@dataclass(frozen=True)
class Replay:
    """A completed request, served again."""

    status_code: int
    body: Any
    headers: dict[str, str]

    def response_headers(self) -> dict[str, str]:
        return {**self.headers, REPLAY_HEADER: "true"}


class Idempotency:
    """The dependency a `POST` with a side effect declares.

    §8's "must honour" list is not advisory: pack generation, regeneration,
    applied-confirmation, custom reminders, export requests and admin connector
    runs each either spend money, send a message, or create a durable artifact.
    `tests/contract/test_idempotent_routes.py` asserts every one of them carries
    this, from an allowlist kept in the test rather than inferred - inferring it
    would mean a new spending route is protected only if someone remembers to
    name it in a pattern.
    """

    def __init__(
        self,
        store: IdempotencyStore,
        *,
        durable: IdempotencyStore | None = None,
        ttl: timedelta = TTL,
        claim_ttl: timedelta = IN_PROGRESS_TTL,
    ) -> None:
        self._store = store
        # §8: "plus a durable record for anything that spent money". Redis is a
        # cache with a TTL; a charge that outlives it must still be answerable.
        self._durable = durable
        self._ttl = ttl
        self._claim_ttl = claim_ttl

    async def run[T](
        self,
        scope: Scope,
        body: bytes | str | Mapping[str, Any] | None,
        handler: Callable[[], Awaitable[tuple[int, T, dict[str, str]]]],
        *,
        spends_money: bool = False,
    ) -> tuple[int, T, dict[str, str]]:
        """Run `handler` at most once for this scope.

        Returns `(status, body, headers)` either from the handler or from the
        stored original. The handler is called exactly zero or one times per
        scope; there is no path on which it runs twice.
        """
        digest = body_hash(body)
        storage_key = scope.storage_key
        claim = Record(body_hash=digest, state=State.IN_PROGRESS, claimed_at=clock.now())

        existing = await _guarded(self._store.claim(storage_key, claim, self._claim_ttl))
        if existing is not None:
            replay = self._resolve(existing, digest)
            return replay.status_code, replay.body, replay.response_headers()

        # A handler that raises leaves the claim standing until `IN_PROGRESS_TTL`
        # expires. Deliberately not released: this layer cannot know whether the
        # exception happened before or after the side effect, and releasing on
        # the assumption that it was before is exactly how the double charge
        # gets back in. The short claim TTL is what keeps that from becoming a
        # day-long lockout.
        status, result, headers = await handler()

        done = Record(
            body_hash=digest,
            state=State.COMPLETED,
            claimed_at=claim.claimed_at,
            status_code=status,
            body=result,
            headers=dict(headers),
            spent=spends_money,
        )
        await _guarded(self._store.finish(storage_key, done, self._ttl))
        if spends_money and self._durable is not None:
            await _guarded(self._durable.finish(storage_key, done, self._ttl))
        return status, result, headers

    def _resolve(self, existing: Record, digest: str) -> Replay:
        """What a duplicate gets.

        Body-hash first: a key reused with a different body is a client bug
        whether or not the original finished, and answering 409 for it would
        send the client back to retry a request that will never be accepted.
        """
        if existing.body_hash != digest:
            raise IdempotencyKeyReuse("this Idempotency-Key was used with a different request body")
        if existing.state is State.IN_PROGRESS:
            raise IdempotencyInProgress("a request with this Idempotency-Key is still running")
        logger.info("idempotent replay", extra={"status": existing.status_code})
        return Replay(
            status_code=existing.status_code or 200,
            body=existing.body,
            headers=dict(existing.headers),
        )


async def _guarded[T](awaitable: Awaitable[T]) -> T:
    """`AC-FOUND-08.5` - a store failure is a 503, not a bypass.

    Every `AppError` passes through untouched: a 409 or a 422 raised inside is
    this module's own answer, not an outage.
    """
    try:
        return await awaitable
    except AppError:
        raise
    except Exception as exc:
        logger.error(
            "the idempotency store is unavailable; failing closed",
            extra={"error": type(exc).__name__},
        )
        raise IdempotencyUnavailable(
            "idempotency protection is unavailable, so this request was not "
            "attempted. Retry with the same Idempotency-Key."
        ) from exc


def read_key(headers: Mapping[str, str]) -> str | None:
    """The `Idempotency-Key` header, if the client sent one.

    Not validated as a UUID. §8 says clients generate a UUIDv4, and they should;
    but a client sending a ULID is not a correctness problem, and rejecting it
    would be a requirement the specification does not state.
    """
    for name, value in headers.items():
        if name.lower() == KEY_HEADER.lower():
            return value.strip() or None
    return None


# -- the FastAPI binding -----------------------------------------------------
#
# §8's Outputs: "`core/idempotency.py` dependency". This is the only place in
# `core` that imports FastAPI, and it does so because the specification puts the
# dependency here - a route declares protection by depending on it, and
# `tests/contract/test_idempotent_routes.py` detects it by looking for exactly
# this object in the route's dependency tree.


class RequiresIdempotency:
    """Declared by every `POST` on §8's "must honour" list.

    A class rather than a function so the contract test can recognise it by
    type. A decorator or a naming convention would be detectable too, and both
    are detectable *by accident* - a route named `create_pack_idempotent` would
    satisfy a name check while doing nothing.
    """

    def __init__(self, *, spends_money: bool = False) -> None:
        #: §8: "a durable record for anything that spent money".
        self.spends_money = spends_money

    async def __call__(self, request: Request) -> Scope:
        """Build the scope from the request, or say what is missing.

        The key is required, not optional-with-a-fallback. A route on this list
        that quietly proceeded without one would be unprotected for exactly the
        clients that most need it - the ones retrying because something went
        wrong.
        """
        key = read_key(request.headers)
        if key is None:
            raise AppError(
                f"this endpoint requires an {KEY_HEADER} header, because a "
                "retry of it would otherwise repeat the side effect",
                code=ErrorCode.VALIDATION_ERROR,
                http_status=422,
            )
        user_id = getattr(request.state, "user_id", "")
        # The route *template*, not the resolved path: `(user, route, key)` must
        # identify the operation, and `/applications/A/pack` and
        # `/applications/B/pack` are the same operation on different resources -
        # which the body hash already distinguishes.
        matched = request.scope.get("route")
        template = getattr(matched, "path", None) or request.url.path
        return Scope(user_id=user_id, route=f"{request.method} {template}", key=key)


__all__ = [
    "IN_PROGRESS_TTL",
    "KEY_HEADER",
    "MAX_KEY_LENGTH",
    "REPLAY_HEADER",
    "TTL",
    "Idempotency",
    "IdempotencyInProgress",
    "IdempotencyKeyReuse",
    "IdempotencyStore",
    "IdempotencyUnavailable",
    "MemoryStore",
    "Record",
    "RedisStore",
    "RequiresIdempotency",
    "Replay",
    "Scope",
    "State",
    "body_hash",
    "read_key",
]
