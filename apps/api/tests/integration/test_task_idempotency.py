"""T-FOUND-10.3 - running a task twice leaves the same state.

`AC-FOUND-10.3`: "Running any task twice with the same arguments produces the
same end state and no duplicate side effect (parametrized over the inventory)."

Parametrized over `REGISTRY`, which is the implemented half of §10's fourteen-row
inventory. At P0 that is `ops.heartbeat` alone: the other thirteen arrive with
the modules that own them, and `tests/spec/test_task_signatures.py` holds the
declared set to §10's table so none of them can appear here unnoticed.

That makes this file thin today and load-bearing later, which is the right way
round. The alternative - writing it when `resume.process` lands - is a test
written by someone looking at the implementation, and it will be shaped to
agree with whatever that implementation does.

**Same end state, not same return value.** A task that returns a new id every
run can still be idempotent; a task that returns the same string while writing
a second row is not. The assertions below read state, and the state a task
touches is what its declared idempotency key is about.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from app.core import clock
from app.core.tasks import (
    REGISTRY,
    MemoryDeadLetters,
    TaskSpec,
    run_to_completion,
)

import app.worker as worker  # noqa: E402  isort:skip

#: One representative argument tuple per implemented task. A task added to the
#: registry with no entry here fails `test_every_implemented_task_has_arguments`
#: rather than being quietly skipped, which is the failure mode a `.get()` with
#: a default would have.
ARGUMENTS: dict[str, tuple[Any, ...]] = {
    "ops.heartbeat": (),
}


#: How to read the state each task touches, so "the same end state" is a
#: comparison rather than a hope.
def heartbeat_state() -> Any:
    return dict(worker.LAST_HEARTBEAT)


STATE: dict[str, Any] = {
    "ops.heartbeat": heartbeat_state,
}


async def nap(_: float) -> None:
    """Retry backoff is asserted in `test_failed_tasks.py`; here it is delay."""
    return None


def test_every_implemented_task_has_arguments():
    """A task added to the registry without an entry above would silently not be
    covered by any of the parametrized tests below."""
    assert set(REGISTRY) == set(ARGUMENTS) == set(STATE)


@pytest.mark.parametrize("name", sorted(REGISTRY))
async def test_running_twice_leaves_the_same_state(name: str):
    """AC-FOUND-10.3."""
    spec: TaskSpec = REGISTRY[name]
    args = ARGUMENTS[name]
    dead = MemoryDeadLetters()

    first = await run_to_completion(spec, args, dead_letters=dead, sleep=nap)
    after_first = STATE[name]()
    second = await run_to_completion(spec, args, dead_letters=dead, sleep=nap)
    after_second = STATE[name]()

    assert first.completed and second.completed
    assert after_first == after_second, f"{name} changed state on its second run"
    assert dead.records == [], f"{name} dead-lettered a successful run"


@pytest.mark.parametrize("name", sorted(REGISTRY))
async def test_running_five_times_leaves_the_same_state(name: str):
    """Twice is the criterion; five times catches the task that alternates.

    A guard written as "if the flag is set, unset it" converges on every even
    run and diverges on every odd one, and passes a two-run test exactly half
    the time.
    """
    spec = REGISTRY[name]
    args = ARGUMENTS[name]

    await run_to_completion(spec, args, sleep=nap)
    baseline = STATE[name]()
    for _ in range(4):
        await run_to_completion(spec, args, sleep=nap)

    assert STATE[name]() == baseline


@pytest.mark.parametrize("name", sorted(REGISTRY))
async def test_the_declared_key_names_something_the_task_reads(name: str):
    """`AC-FOUND-10.2`'s key is a claim about behaviour, not a comment.

    The weakest honest check available without knowing each task's internals:
    the key must name something, and the task must converge. The strong version
    per task is the test above, parametrized over the same inventory.
    """
    assert REGISTRY[name].idempotency_key.strip()


# -- ops.heartbeat, specifically ---------------------------------------------


async def test_the_heartbeat_is_keyed_on_the_minute():
    """Its stated key. Two beats inside one minute leave one beat, which is what
    makes an overlapping cron run harmless even before the lock catches it."""
    start = clock.now().replace(second=0, microsecond=0)
    worker.LAST_HEARTBEAT.update(at=None, beats=0)

    with clock.freeze(start):
        await worker.heartbeat()
        await worker.heartbeat()
        await worker.heartbeat()

    assert worker.LAST_HEARTBEAT["beats"] == 1
    assert worker.LAST_HEARTBEAT["at"] == start


async def test_the_heartbeat_advances_with_the_minute():
    """The negative control. A heartbeat that never advanced would pass every
    idempotency assertion in this file and tell an operator nothing."""
    start = clock.now().replace(second=0, microsecond=0)
    worker.LAST_HEARTBEAT.update(at=None, beats=0)

    with clock.freeze(start):
        await worker.heartbeat()
    with clock.freeze(start + timedelta(minutes=1)):
        await worker.heartbeat()

    assert worker.LAST_HEARTBEAT["beats"] == 2
    assert worker.LAST_HEARTBEAT["at"] == start + timedelta(minutes=1)


async def test_the_heartbeat_ignores_the_seconds_within_a_minute():
    start = clock.now().replace(second=0, microsecond=0)
    worker.LAST_HEARTBEAT.update(at=None, beats=0)

    for second in (0, 17, 59):
        with clock.freeze(start + timedelta(seconds=second)):
            await worker.heartbeat()

    assert worker.LAST_HEARTBEAT["beats"] == 1


async def test_the_heartbeat_returns_the_minute_it_recorded():
    """The return value is what a caller checking liveness reads, so it has to
    be the truncated minute rather than the instant."""
    start = clock.now().replace(second=0, microsecond=0)
    with clock.freeze(start + timedelta(seconds=42)):
        assert await worker.heartbeat() == start.isoformat()
