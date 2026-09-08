"""T-FOUND-10.6 - two cron runs, one lock.

`AC-FOUND-10.6`: "Two concurrent invocations of any cron task result in one
doing work and one exiting on the lock."

`01-foundations.md` §10: "Cron tasks must tolerate overlapping runs: each takes
a Redis lock named for itself and exits quietly if held."

The overlap is not hypothetical. `reminders.dispatch` runs every minute in
batches of 200; the first time a batch takes ninety seconds, two copies are
running, and from then on they never stop overlapping. Without the lock every
reminder in the overlap goes out twice - to a user who is already anxious about
the thing being reminded about.

**Quietly.** An overlapping run is the expected state of a busy system, not an
incident. A warning every minute is a warning nobody reads, and the one that
matters is then invisible.

Against a real Redis in process (`fakeredis`) rather than a dictionary, because
the whole claim is that `SET ... NX PX` is atomic and a dictionary would only
prove that my double is.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest

from app.core.tasks import LOCK_TTL, REGISTRY, cron_lock

# Importing the worker is what registers the tasks. Without it `REGISTRY` is
# empty, every parametrized test below collects nothing, and the file reports
# success while asserting about no task at all.
import app.worker as worker  # noqa: E402  isort:skip


@pytest.fixture
def redis() -> Any:
    from fakeredis import FakeAsyncRedis

    return FakeAsyncRedis()


CRON_TASKS = sorted(name for name, spec in REGISTRY.items() if spec.cron is not None)


# -- the lock ----------------------------------------------------------------


async def test_the_first_holder_wins(redis: Any):
    async with cron_lock(redis, "reminders.dispatch") as held:
        assert held is True


async def test_the_second_holder_is_told_no(redis: Any):
    """AC-FOUND-10.6."""
    async with cron_lock(redis, "reminders.dispatch") as first:
        assert first is True
        async with cron_lock(redis, "reminders.dispatch") as second:
            assert second is False


async def test_the_lock_is_released_when_the_run_ends(redis: Any):
    """A lock that outlived its run would silence the schedule until its TTL."""
    async with cron_lock(redis, "reminders.dispatch"):
        pass
    async with cron_lock(redis, "reminders.dispatch") as again:
        assert again is True


async def test_a_run_that_raises_still_releases(redis: Any):
    """The failure that would otherwise stop a cron for five minutes, silently,
    once."""
    with pytest.raises(RuntimeError):
        async with cron_lock(redis, "reminders.dispatch") as held:
            assert held
            raise RuntimeError("the batch blew up")

    async with cron_lock(redis, "reminders.dispatch") as again:
        assert again is True


async def test_a_loser_does_not_release_the_winners_lock(redis: Any):
    """The bug a naive `finally: delete(key)` produces: the run that was told
    "no" deletes the lock on its way out, and the next tick overlaps the run
    that is still going."""
    async with cron_lock(redis, "reminders.dispatch") as first:
        async with cron_lock(redis, "reminders.dispatch") as second:
            assert (first, second) == (True, False)
        # The loser has exited. The winner's lock must still be held.
        async with cron_lock(redis, "reminders.dispatch") as third:
            assert third is False


async def test_different_tasks_do_not_block_each_other(redis: Any):
    """ "a Redis lock named for itself". A single global cron lock would let one
    slow nightly purge silence every minute-cron for an hour."""
    async with (
        cron_lock(redis, "reminders.dispatch") as first,
        cron_lock(redis, "ops.heartbeat") as second,
    ):
        assert first is True
        assert second is True


async def test_the_lock_expires(redis: Any):
    """A killed worker must not hold the schedule for ever. Five minutes is
    long enough for a slow run and short enough that a crash costs a few ticks.
    """
    ttl = timedelta(milliseconds=60)
    async with cron_lock(redis, "reminders.dispatch", ttl) as held:
        assert held
        assert 0 < await redis.pttl("cronlock:reminders.dispatch") <= 60
        await asyncio.sleep(0.12)
        async with cron_lock(redis, "reminders.dispatch", ttl) as after_expiry:
            assert after_expiry is True, "the lock never expires"


def test_the_default_ttl_is_stated_in_minutes():
    assert timedelta(minutes=5) == LOCK_TTL


# -- concurrently, which is the case that matters ----------------------------


async def test_one_of_two_concurrent_runs_does_the_work(redis: Any):
    """AC-FOUND-10.6, run as two tasks rather than nested blocks.

    Nesting proves the lock is exclusive; racing proves it is *atomic*. A
    check-then-set implementation passes the nested version and fails here, and
    it is the version a busy minute-cron actually produces.
    """
    worked: list[int] = []

    async def run(marker: int) -> None:
        async with cron_lock(redis, "reminders.dispatch") as held:
            if not held:
                return
            await asyncio.sleep(0.02)
            worked.append(marker)

    await asyncio.gather(*(run(index) for index in range(2)))

    assert len(worked) == 1


async def test_twenty_concurrent_runs_still_do_the_work_once(redis: Any):
    """At the scale a minute-cron reaches after an hour of overlap."""
    worked: list[int] = []

    async def run(marker: int) -> None:
        async with cron_lock(redis, "reminders.dispatch") as held:
            if held:
                await asyncio.sleep(0.01)
                worked.append(marker)

    await asyncio.gather(*(run(index) for index in range(20)))

    assert len(worked) == 1


async def test_the_next_tick_after_a_run_finishes_does_work(redis: Any):
    """The control. A lock that never released would pass every assertion above
    and stop the cron for ever."""
    worked: list[int] = []

    async def run(marker: int) -> None:
        async with cron_lock(redis, "ops.heartbeat") as held:
            if held:
                worked.append(marker)

    await run(1)
    await run(2)
    assert worked == [1, 2]


# -- through the worker ------------------------------------------------------


@pytest.mark.parametrize("name", CRON_TASKS)
async def test_a_cron_task_skips_its_overlapping_run(redis: Any, name: str):
    """AC-FOUND-10.6, through the wrapper the worker actually calls.

    Parametrized over every implemented cron task, so a fourteenth task added
    with `lock=False` fails here rather than duplicating in production.
    """
    runner = worker._bind(REGISTRY[name])
    ctx = {"redis": redis, "job_try": 1}

    async def hold() -> Any:
        async with cron_lock(redis, name):
            await asyncio.sleep(0.05)
            return "held"

    holder = asyncio.create_task(hold())
    await asyncio.sleep(0.01)

    assert await runner(ctx) is None, f"{name} ran while its lock was held"
    await holder


@pytest.mark.parametrize("name", CRON_TASKS)
async def test_a_cron_task_runs_when_its_lock_is_free(redis: Any, name: str):
    """The control for the test above: if the wrapper returned `None`
    unconditionally, that one would pass and the cron would never run."""
    runner = worker._bind(REGISTRY[name])
    assert await runner({"redis": redis, "job_try": 1}) is not None


def test_every_cron_task_in_the_registry_is_lock_guarded():
    """§10: "Cron tasks **must** tolerate overlapping runs". Defaulted from the
    schedule in `core.tasks`, so the author who forgets is the author who just
    wrote a cron - asserted here so the default cannot be removed quietly."""
    assert CRON_TASKS, "no cron task is registered, so this file proves nothing"
    for name in CRON_TASKS:
        assert REGISTRY[name].lock, f"{name} runs on a schedule but takes no lock"
