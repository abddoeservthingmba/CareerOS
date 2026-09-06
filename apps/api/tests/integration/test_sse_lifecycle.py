"""T-FOUND-11.4 - a stream says it is alive, and it stops.

`AC-FOUND-11.4`: "A stream emits a heartbeat within 20 s of silence and closes
within 1 s of a terminal status."

Both numbers are about a client that cannot see the server.

**The heartbeat.** From a client's side, "still generating your pack" and "the
server fell over" look identical: a connection with nothing on it. So does a
proxy that has quietly decided an idle connection is dead - which is what the
heartbeat really prevents, because a reaped stream is a progress bar that stops
at 40% for ever. Fifteen seconds, inside the criterion's twenty, leaving room
for a busy event loop.

**The close.** A stream that stays open after the terminal event leaves the
client waiting on something that has nothing more to say - and holding a
connection the server also has to hold. One second is generous; the close
happens on the same iteration that yields the terminal event.

**And a ceiling.** Ten minutes, after which the client re-polls (§11). Said in
the stream as an `expired` event rather than by silence, so a client can tell a
ceiling from a crash and knows to go back to `status_url` rather than retry.

Driven against `event_stream` directly rather than over HTTP. The generator
*is* the lifecycle; putting an ASGI server, an event-source encoder and an
in-process transport between the assertion and its subject would add three
things that can hang and nothing that can fail informatively. The HTTP layer is
covered by `test_accepted_responses.py` and `test_sse_headers.py`.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest

from app.core import clock
from app.core.sse import (
    HEARTBEAT_INTERVAL,
    MAX_LIFETIME,
    OperationState,
    OperationStore,
    Status,
    StreamEvent,
    event_stream,
)

OWNER = "01J000000000000000000OWNER"
TASK = "01J00000000000000000TASK01"

TINY = timedelta(milliseconds=30)


def started() -> tuple[OperationStore, OperationState, asyncio.Queue[StreamEvent]]:
    store = OperationStore()
    state = store.start(TASK, OWNER)
    return store, state, store.subscribe(TASK)


async def drain(stream: Any, limit: int = 20) -> list[dict[str, Any]]:
    """Everything the stream yields, until it closes or `limit` is reached."""
    out: list[dict[str, Any]] = []
    async for chunk in stream:
        out.append(chunk)
        if len(out) >= limit:
            break
    return out


# -- the numbers §11 states --------------------------------------------------


def test_the_intervals_are_the_ones_the_specification_gives():
    """§11: "a heartbeat comment every 15 s"; "Maximum stream lifetime 10 min"."""
    assert timedelta(seconds=15) == HEARTBEAT_INTERVAL
    assert timedelta(minutes=10) == MAX_LIFETIME


def test_the_heartbeat_is_inside_the_criterions_window():
    """`AC-FOUND-11.4` allows 20 s of silence. Fifteen leaves five seconds of
    slack for a busy event loop, which is the difference between a criterion
    that holds under load and one that holds on an idle laptop."""
    assert timedelta(seconds=20) > HEARTBEAT_INTERVAL


# -- the close ---------------------------------------------------------------


async def test_the_stream_closes_on_a_terminal_status():
    """AC-FOUND-11.4, second half."""
    store, state, queue = started()
    store.advance(TASK, "gathering", 0, Status.RUNNING)
    store.advance(TASK, "ready", 100, Status.SUCCEEDED)

    events = await drain(event_stream(state, queue, heartbeat=TINY))

    assert [chunk["event"] for chunk in events] == ["running", "succeeded"]


@pytest.mark.parametrize(
    "status", [Status.SUCCEEDED, Status.FAILED, Status.CANCELLED], ids=lambda s: str(s)
)
async def test_every_terminal_status_closes_the_stream(status: Status):
    """All three, because a stream that only closed on success would leave every
    failed pack streaming until the ten-minute ceiling."""
    store, state, queue = started()
    store.advance(TASK, "generating", 50, status)

    events = await drain(event_stream(state, queue, heartbeat=TINY))

    assert len(events) == 1
    assert events[0]["event"] == str(status)


async def test_a_running_status_does_not_close_the_stream():
    """The control. A stream that closed on the first event of any kind would
    pass every assertion above."""
    store, state, queue = started()
    store.advance(TASK, "gathering", 0, Status.RUNNING)

    stream = event_stream(state, queue, heartbeat=TINY)
    first = await anext(stream)
    second = await asyncio.wait_for(anext(stream), timeout=1)

    assert first["event"] == "running"
    assert "comment" in second, "the stream ended after a non-terminal event"
    await stream.aclose()


async def test_a_stream_opened_after_completion_replays_and_closes():
    """A client that reconnects after the work finished must not hang waiting
    for an event that already happened.

    This is the common case on a flaky mobile connection, and the one where "the
    stream is live-only" turns into a spinner that never resolves.
    """
    store, state, queue = started()
    store.advance(TASK, "gathering", 0, Status.RUNNING)
    store.advance(TASK, "ready", 100, Status.SUCCEEDED)

    late = store.subscribe(TASK)
    events = await drain(event_stream(state, late, heartbeat=TINY))

    assert [chunk["event"] for chunk in events] == ["running", "succeeded"]
    assert queue is not late


async def test_the_replay_carries_every_event_the_client_missed():
    """A progress bar built from live events alone would sit at zero until the
    last stage on a fast pipeline - which is most of them."""
    store, state, _ = started()
    for stage, progress in (("gathering", 0), ("generating", 25), ("checking", 75)):
        store.advance(TASK, stage, progress, Status.RUNNING)

    stream = event_stream(state, store.subscribe(TASK), heartbeat=TINY)
    replayed = [await anext(stream) for _ in range(3)]
    await stream.aclose()

    import json

    assert [json.loads(chunk["data"])["stage"] for chunk in replayed] == [
        "gathering",
        "generating",
        "checking",
    ]


# -- the heartbeat -----------------------------------------------------------


async def test_a_silent_stream_emits_a_heartbeat():
    """AC-FOUND-11.4, first half.

    A comment, not an event: `EventSource` handlers never see it, and every
    proxy between here and the client counts it as traffic.
    """
    store, state, queue = started()

    stream = event_stream(state, queue, heartbeat=TINY)
    chunk = await asyncio.wait_for(anext(stream), timeout=2)
    await stream.aclose()

    assert chunk == {"comment": "heartbeat"}


async def test_the_heartbeat_repeats_while_the_stream_is_silent():
    store, state, queue = started()

    stream = event_stream(state, queue, heartbeat=TINY)
    beats = [await asyncio.wait_for(anext(stream), timeout=2) for _ in range(3)]
    await stream.aclose()

    assert all(chunk == {"comment": "heartbeat"} for chunk in beats)


async def test_an_event_arriving_during_the_wait_is_delivered_not_delayed():
    """The heartbeat is a timeout on waiting for an event, not a tick that
    events queue behind. A client should not wait fifteen seconds to learn its
    pack is ready because the event landed just after a beat."""
    store, state, queue = started()
    stream = event_stream(state, queue, heartbeat=timedelta(seconds=5))

    async def publish() -> None:
        await asyncio.sleep(0.01)
        store.advance(TASK, "ready", 100, Status.SUCCEEDED)

    publisher = asyncio.create_task(publish())
    chunk = await asyncio.wait_for(anext(stream), timeout=2)
    await publisher

    assert chunk["event"] == "succeeded"


async def test_a_heartbeat_does_not_close_the_stream():
    """A beat is a sign of life, not an ending. Closing after one would make
    every slow operation look finished."""
    store, state, queue = started()
    stream = event_stream(state, queue, heartbeat=TINY)

    await asyncio.wait_for(anext(stream), timeout=2)
    store.advance(TASK, "ready", 100, Status.SUCCEEDED)
    following = await asyncio.wait_for(anext(stream), timeout=2)

    assert following["event"] == "succeeded"


# -- the ceiling -------------------------------------------------------------


async def test_the_stream_ends_at_its_lifetime():
    """§11: "Maximum stream lifetime 10 min, after which the client re-polls."

    An unbounded stream is a connection leak that becomes visible at exactly the
    scale where it is hardest to fix.
    """
    store, state, queue = started()

    events = await drain(event_stream(state, queue, heartbeat=TINY, lifetime=timedelta(0)))

    assert len(events) == 1
    assert events[0]["event"] == "expired"


async def test_the_ceiling_is_announced_rather_than_silent():
    """A client that saw the connection drop cannot tell a ceiling from a crash.
    One retries the stream; the other should go back to `status_url`."""
    store, state, queue = started()

    events = await drain(event_stream(state, queue, heartbeat=TINY, lifetime=timedelta(0)))

    assert "max_lifetime" in events[0]["data"]


async def test_the_ceiling_is_measured_from_the_clock_not_from_events():
    """HR-10 - `core.clock`, so this is assertable without waiting ten minutes
    and so a frozen-clock test elsewhere does not silently disable the ceiling.
    """
    store, state, queue = started()
    start = clock.now()

    with clock.freeze(start):
        stream = event_stream(state, queue, heartbeat=TINY, lifetime=timedelta(minutes=10))
        first = await asyncio.wait_for(anext(stream), timeout=2)
        assert "comment" in first

    with clock.freeze(start + timedelta(minutes=11)):
        expired = await asyncio.wait_for(anext(stream), timeout=2)

    assert expired["event"] == "expired"


async def test_a_terminal_status_beats_the_ceiling():
    """An operation that finished has finished. Reporting `expired` for it would
    send the client back to poll for a result it was just handed."""
    store, state, queue = started()
    store.advance(TASK, "ready", 100, Status.SUCCEEDED)

    events = await drain(event_stream(state, queue, heartbeat=TINY, lifetime=timedelta(0)))

    assert events[0]["event"] == "succeeded"


# -- disconnection -----------------------------------------------------------


async def test_a_disconnected_client_ends_the_stream():
    """The server should stop doing work for a client that has gone.

    Wired to `Request.is_disconnected` in a real route; injected here, because
    an in-process ASGI transport never delivers `http.disconnect` and a test
    against it would assert nothing while appearing to.
    """
    store, state, queue = started()
    gone = {"value": False}

    stream = event_stream(state, queue, heartbeat=TINY, is_disconnected=lambda: gone["value"])
    await asyncio.wait_for(anext(stream), timeout=2)
    gone["value"] = True

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(stream), timeout=2)


async def test_a_coroutine_disconnect_check_is_awaited():
    """`Request.is_disconnected` is a coroutine. A check that treated it as a
    plain value would see a truthy coroutine object and close every stream
    immediately."""
    store, state, queue = started()

    async def connected() -> bool:
        return False

    stream = event_stream(state, queue, heartbeat=TINY, is_disconnected=connected)
    chunk = await asyncio.wait_for(anext(stream), timeout=2)
    await stream.aclose()

    assert chunk == {"comment": "heartbeat"}


async def test_no_disconnect_check_is_a_valid_configuration():
    """Not every caller has a request - the worker-side tests here do not."""
    store, state, queue = started()
    store.advance(TASK, "ready", 100, Status.SUCCEEDED)

    events = await drain(event_stream(state, queue, heartbeat=TINY))

    assert events[0]["event"] == "succeeded"
