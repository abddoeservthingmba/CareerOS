"""Long operations and streaming - `FOUND-11`.

`01-foundations.md` §11: "The client can watch a slow operation progress without
polling tightly, and can fall back to polling when streaming is unavailable."

Both halves of that sentence are requirements, and the second one is the one
that gets dropped.

**Every `202` carries two URLs, and both work.** `status_url` is a plain GET
returning the current state; `events_url` is the stream. A client that cannot
use SSE - a corporate proxy that buffers, a mobile network that kills idle
connections, a runtime with no `EventSource` - must be able to finish every flow
with `status_url` alone (`AC-FOUND-11.2`). This is not a fallback in the sense of
"degraded": it is the same information, arriving less often. The stream is an
optimisation over polling, and the moment it becomes the only way to learn that
a pack is ready, a fraction of users can never apply to a job.

**A stream is a read of one resource, authorised like any other.** Same auth,
scoped to one resource owned by the caller, 404 rather than 403 on an ownership
failure (`02-auth-and-account.md` §6). A streaming endpoint that skipped the
check because "it only sends progress" would leak the existence of another
user's resource, one `event: stage` at a time.

**It says when it is still alive, and it stops.** A heartbeat every 15 s, so a
proxy does not reap a quiet connection and a client can tell "still working"
from "the server went away". A close on any terminal status, so a client is
never left waiting on a stream that has nothing more to say. And a hard ceiling
of ten minutes, after which the client re-polls - an unbounded stream is a
connection leak that only shows up at scale.

**Buffering off.** Behind Cloudflare and behind nginx, a proxy that buffers a
`text/event-stream` delivers the whole thing at once at the end, which is
exactly a slow poll with extra steps and no way to notice. `Cache-Control:
no-cache` and `X-Accel-Buffering: no` on every SSE response (`AC-FOUND-11.5`).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field

from app.core import clock

logger = logging.getLogger("app.sse")

#: §11: "a heartbeat comment every 15 s". `AC-FOUND-11.4` allows 20 s of
#: silence, so 15 leaves room for a slow event loop without failing the
#: criterion.
HEARTBEAT_INTERVAL = timedelta(seconds=15)

#: §11: "Maximum stream lifetime 10 min, after which the client re-polls."
MAX_LIFETIME = timedelta(minutes=10)

#: §11: buffering must be disabled for these routes.
SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    # nginx and Cloudflare both honour this. Without it a proxy buffers the
    # whole stream and delivers it at the end, which is a slow poll that nobody
    # can tell is broken.
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


class Status(StrEnum):
    """Where a long operation is.

    Three of these are terminal, and a stream closes on any of them. `cancelled`
    exists so a user who navigated away is distinguishable from a job that
    failed - one is a support ticket and the other is not.
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in (Status.SUCCEEDED, Status.FAILED, Status.CANCELLED)


TERMINAL = frozenset(status for status in Status if status.terminal)


class AcceptedResponse(BaseModel):
    """§11's `202` body: `{task_id, status, status_url, events_url}`.

    A model rather than a dict literal per route, because `AC-FOUND-11.1`
    asserts that *every* `202` validates against it - and a route that
    hand-built the body would satisfy the schema right up until someone renamed
    a field in one place.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str
    status: Status = Status.QUEUED
    #: A plain GET returning the current state. The whole flow must be
    #: completable with this alone (`AC-FOUND-11.2`).
    status_url: str
    #: The SSE stream. An optimisation over `status_url`, never the only way.
    events_url: str


class StreamEvent(BaseModel):
    """§11: "Stream events are `{stage, progress: 0-100, status, detail, at}`."

    `stage` is a per-operation enum declared in the module's own spec file, so
    it is a plain string here: `core` does not know what a resume pipeline's
    stages are, and a union of every module's stages would be `core` importing
    the modules it sits under.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: str
    progress: int = Field(ge=0, le=100)
    status: Status
    detail: str = ""
    at: datetime = Field(default_factory=clock.now)

    def sse(self) -> dict[str, Any]:
        """The event as `sse-starlette` wants it.

        `event:` is the status rather than the stage, because a client's first
        question is "is this over", and switching on the stage would mean every
        client re-deriving that from a per-operation enum it may not know.
        """
        return {
            "event": str(self.status),
            "data": self.model_dump_json(),
        }


@dataclass
class OperationState:
    """What `status_url` returns, and what the stream is a view of.

    One object, two renderings. That is what makes `AC-FOUND-11.2` true by
    construction rather than by discipline: a poller and a streamer cannot
    disagree, because there is nothing for them to disagree about.
    """

    task_id: str
    owner_id: str
    status: Status = Status.QUEUED
    stage: str = ""
    progress: int = 0
    detail: str = ""
    updated_at: datetime | None = None
    events: list[StreamEvent] | None = None

    def __post_init__(self) -> None:
        if self.updated_at is None:
            self.updated_at = clock.now()
        if self.events is None:
            self.events = []

    def advance(self, stage: str, progress: int, status: Status, detail: str = "") -> StreamEvent:
        """Record one step, and return the event describing it."""
        event = StreamEvent(stage=stage, progress=progress, status=status, detail=detail)
        self.stage, self.progress, self.status = stage, progress, status
        self.detail, self.updated_at = detail, event.at
        assert self.events is not None
        self.events.append(event)
        return event

    @property
    def terminal(self) -> bool:
        return self.status.terminal

    def snapshot(self) -> dict[str, Any]:
        """`status_url`'s body.

        Deliberately the same fields a stream event carries, plus the id. A
        polling client that received a *differently shaped* answer would need
        two parsers for one operation, and the second one gets less testing.
        """
        return {
            "task_id": self.task_id,
            "status": str(self.status),
            "stage": self.stage,
            "progress": self.progress,
            "detail": self.detail,
            "at": (self.updated_at or clock.now()).isoformat(),
            "terminal": self.terminal,
        }


class OperationStore:
    """Where long operations live between the `202` and the terminal event.

    In process for now. `FOUND-10`'s Redis replaces it when the worker and the
    API stop being the same process - which is already true in production and is
    why this is a class with a seam rather than a module-level dict.
    """

    def __init__(self) -> None:
        self._operations: dict[str, OperationState] = {}
        self._waiters: dict[str, list[asyncio.Queue[StreamEvent]]] = {}

    def start(self, task_id: str, owner_id: str) -> OperationState:
        state = OperationState(task_id=task_id, owner_id=owner_id)
        self._operations[task_id] = state
        return state

    def get(self, task_id: str, owner_id: str) -> OperationState | None:
        """The operation, if it is this caller's.

        Ownership is checked here rather than in each route, and a mismatch
        returns `None` - which the routes render as 404, never 403
        (`02-auth-and-account.md` §6). A 403 would confirm that the id exists.
        """
        state = self._operations.get(task_id)
        if state is None or state.owner_id != owner_id:
            return None
        return state

    def advance(
        self, task_id: str, stage: str, progress: int, status: Status, detail: str = ""
    ) -> StreamEvent | None:
        state = self._operations.get(task_id)
        if state is None:
            return None
        event = state.advance(stage, progress, status, detail)
        for queue in self._waiters.get(task_id, []):
            queue.put_nowait(event)
        return event

    def subscribe(self, task_id: str) -> asyncio.Queue[StreamEvent]:
        """A queue carrying everything so far, then everything after.

        The backlog is loaded *and* the queue registered in one synchronous
        step, so there is no instant in which an event could be both replayed
        and delivered live. Replaying separately - read the history, then start
        listening - looks equivalent and duplicates every event that lands
        between the two, which on a fast pipeline is most of them.
        """
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        state = self._operations.get(task_id)
        for event in list(state.events or []) if state is not None else []:
            queue.put_nowait(event)
        self._waiters.setdefault(task_id, []).append(queue)
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue[StreamEvent]) -> None:
        waiters = self._waiters.get(task_id)
        if waiters and queue in waiters:
            waiters.remove(queue)
        if waiters is not None and not waiters:
            del self._waiters[task_id]

    def __len__(self) -> int:
        return len(self._operations)


class StreamClosed(StrEnum):
    """Why a stream ended, for the log line that says so."""

    TERMINAL = "terminal"
    LIFETIME = "lifetime"
    DISCONNECTED = "disconnected"


async def event_stream(
    state: OperationState,
    queue: asyncio.Queue[StreamEvent],
    *,
    heartbeat: timedelta = HEARTBEAT_INTERVAL,
    lifetime: timedelta = MAX_LIFETIME,
    is_disconnected: Callable[[], Any] | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """§11's stream: replay, then live, then a close.

    **Replay first.** A client that subscribes after the operation started would
    otherwise miss every event before it connected - and on a fast pipeline that
    is most of them, leaving a progress bar at zero until the last one arrives.

    **Then a heartbeat or an event, whichever comes first.** The heartbeat is an
    SSE comment: it keeps a proxy from reaping the connection, and it tells the
    client the difference between "still working" and "the server went away",
    which is otherwise indistinguishable from a client's side.

    **Then a close** on the first terminal status, or at the lifetime ceiling.
    An unbounded stream is a connection leak that only becomes visible at the
    scale where it is hardest to fix.
    """
    started = clock.now()

    # No separate replay pass: `OperationStore.subscribe` hands back a queue
    # already carrying the backlog, so history and live events arrive through
    # one path and in one order. A client reconnecting after the work finished
    # therefore drains the backlog and closes on the terminal event it contains,
    # rather than waiting for an event that already happened.
    while True:
        # Anything already queued is delivered before anything else is
        # considered. An operation that finished before the client connected has
        # finished: reporting `expired` for it would send the client back to
        # poll for a result it was about to be handed.
        while not queue.empty():
            event = queue.get_nowait()
            yield event.sse()
            if event.status.terminal:
                logger.info("stream closed", extra={"reason": str(StreamClosed.TERMINAL)})
                return

        # Then the ceiling, cheaply. Asking the transport whether the client is
        # still there costs a round trip through the ASGI receive channel, and a
        # stream that has already expired has no reason to make it.
        if clock.now() - started >= lifetime:
            # The client re-polls from here (§11). Said in the stream rather
            # than by silence, so a client can tell a ceiling from a crash.
            yield {"event": "expired", "data": '{"reason":"max_lifetime"}'}
            logger.info("stream closed", extra={"reason": str(StreamClosed.LIFETIME)})
            return
        if is_disconnected is not None and await _truthy(is_disconnected()):
            logger.info("stream closed", extra={"reason": str(StreamClosed.DISCONNECTED)})
            return

        try:
            event = await asyncio.wait_for(queue.get(), timeout=heartbeat.total_seconds())
        except TimeoutError:
            # An SSE comment. Invisible to `EventSource` handlers and enough to
            # keep every proxy between here and the client from reaping this.
            yield {"comment": "heartbeat"}
            continue

        yield event.sse()
        if event.status.terminal:
            logger.info("stream closed", extra={"reason": str(StreamClosed.TERMINAL)})
            return


async def _truthy(value: Any) -> bool:
    """`Request.is_disconnected` is a coroutine; a test's double may not be."""
    if asyncio.iscoroutine(value):
        return bool(await value)
    return bool(value)


def accepted(task_id: str, base_path: str, status: Status = Status.QUEUED) -> AcceptedResponse:
    """Build §11's `202` body from the one place that knows the URL shape.

    Both URLs derived from one path, so a route cannot ship a working
    `events_url` next to a `status_url` that 404s - which is the failure mode
    `AC-FOUND-11.1` exists to catch, and the one that makes
    `AC-FOUND-11.2`'s fallback a fiction.
    """
    stem = base_path.rstrip("/")
    return AcceptedResponse(
        task_id=task_id,
        status=status,
        status_url=f"{stem}/{task_id}",
        events_url=f"{stem}/{task_id}/events",
    )


def sse_response(generator: AsyncIterator[dict[str, Any]], **kwargs: Any) -> Any:
    """`sse-starlette`'s response, with §11's headers attached.

    Wrapped rather than constructed per route, because `AC-FOUND-11.5` is about
    *every* SSE route and a header set copied into each one is a header set that
    is eventually missing from the newest.
    """
    from sse_starlette.sse import EventSourceResponse

    return EventSourceResponse(generator, headers=dict(SSE_HEADERS), **kwargs)


@dataclass(frozen=True)
class Stages:
    """A per-operation stage enum, declared by the module that owns it.

    §11: "Stages are a fixed per-operation enum, declared in the module's spec
    file." Fixed, because a client draws a progress bar from the list and a
    stage that appears only sometimes makes the bar jump backwards.
    """

    operation: str
    names: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.names:
            raise ValueError(f"{self.operation} declares no stages")
        if len(set(self.names)) != len(self.names):
            raise ValueError(f"{self.operation} declares a stage twice: {self.names}")

    def index(self, stage: str) -> int:
        try:
            return self.names.index(stage)
        except ValueError as exc:
            raise ValueError(
                f"{stage!r} is not a stage of {self.operation}; declared: {self.names}"
            ) from exc

    def progress(self, stage: str) -> int:
        """Where the bar sits when this stage begins.

        Derived from the position rather than hand-assigned per stage: two
        places holding "checking is 75%" is two places to forget when a stage is
        inserted, and the symptom is a bar that goes backwards.
        """
        return round(self.index(stage) * 100 / len(self.names))

    @classmethod
    def of(cls, operation: str, *names: str) -> Self:
        return cls(operation, names)


__all__ = [
    "HEARTBEAT_INTERVAL",
    "MAX_LIFETIME",
    "SSE_HEADERS",
    "TERMINAL",
    "AcceptedResponse",
    "OperationState",
    "OperationStore",
    "Stages",
    "Status",
    "StreamClosed",
    "StreamEvent",
    "accepted",
    "event_stream",
    "sse_response",
]
