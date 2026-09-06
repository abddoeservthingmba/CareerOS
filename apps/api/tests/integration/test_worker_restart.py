"""T-FOUND-10.4 - the worker dies mid-task and the work still happens once.

`AC-FOUND-10.4`: "Killing the worker mid-task and restarting it completes the
work exactly once, verified for `resume.process` and `reminders.dispatch`."

This is the criterion that decides whether the other five matter. A deploy kills
the worker several times a week; so does an OOM, a node drain, and a spot
instance going away. Every one of them lands in the middle of some task. Two
outcomes are unacceptable and only one of them is obvious:

* the work never happens - the user waits for a pack that is not coming;
* the work happens **twice** - the user is charged twice, or reminded twice, and
  nobody finds out because both halves look like success.

The mechanism is the same one §10 asks every task to state: the idempotency key
is what makes the re-run converge. A killed task's job goes back on the queue,
and the guard the task checks on the way in is what stops the second run from
repeating the first one's side effect.

**`resume.process` and `reminders.dispatch` are not implemented yet** - they are
P2 and P6, and `app/modules/` is empty. What is asserted here is the framework
the criterion depends on: that a cancellation is not a failure, that an
interrupted job is not dead-lettered, and that a status-guarded task run twice
across an interruption does its work once. Those are the properties the two
named tasks will rely on, and the model below is the shape §10's inventory
prescribes for both - `resume_id` + status guard, and `dedup_key`.

Written now rather than with the tasks, because a test written alongside its
subject is shaped to agree with it.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest

from app.core import clock
from app.core.tasks import (
    MemoryDeadLetters,
    TaskSpec,
    run_once,
    run_to_completion,
)


def spec_for(name: str, func: Any, key: str, *, max_tries: int = 3) -> TaskSpec:
    return TaskSpec(
        name=name,
        func=func,
        idempotency_key=key,
        max_tries=max_tries,
        timeout=timedelta(seconds=5),
        cron=None,
        lock=False,
    )


async def nap(_: float) -> None:
    return None


# -- the shape §10 prescribes for `resume.process` ---------------------------


class StatusGuarded:
    """`resume.process(resume_id)`, keyed on `resume_id` + a status guard.

    The stage machine of `04-resume-pipeline.md` §2 in miniature: a row with a
    status, a task that only acts when the status is `pending`, and a commit
    that moves it to `done`. Everything that matters about the restart case is
    in the ordering of those three steps.
    """

    def __init__(self) -> None:
        self.rows: dict[str, str] = {}
        self.side_effects: list[str] = []
        self.interrupt_at: str | None = None
        self.started = asyncio.Event()

    def stage(self, resume_id: str) -> None:
        self.rows[resume_id] = "pending"

    async def __call__(self, resume_id: str) -> str:
        status = self.rows.get(resume_id)
        if status != "pending":
            # The guard. A restart re-runs the job; this is what makes the
            # second run converge instead of extracting the resume again.
            return f"skipped {resume_id} ({status})"

        self.started.set()
        if self.interrupt_at == resume_id:
            # Killed *after* the guard read and *before* the side effect - the
            # window where a naive implementation loses the work entirely.
            self.interrupt_at = None
            raise asyncio.CancelledError

        self.side_effects.append(resume_id)
        self.rows[resume_id] = "done"
        return f"processed {resume_id}"


async def test_a_task_killed_before_its_side_effect_is_re_run():
    """The work is not lost. The job goes back on the queue and the guard still
    reads `pending`, so the restart does it."""
    task = StatusGuarded()
    task.stage("01J0RESUME")
    task.interrupt_at = "01J0RESUME"
    spec = spec_for("resume.process", task, "resume_id + status guard")

    with pytest.raises(asyncio.CancelledError):
        await run_once(spec, ("01J0RESUME",), attempt=1)
    assert task.side_effects == []

    # The worker restarts and the queue redelivers.
    outcome = await run_to_completion(spec, ("01J0RESUME",), sleep=nap)

    assert outcome.completed
    assert task.side_effects == ["01J0RESUME"]


async def test_a_task_killed_after_its_side_effect_is_not_repeated():
    """AC-FOUND-10.4's "exactly once", from the other side.

    The dangerous half. The first run finished its work and the acknowledgement
    never reached the queue, so the job is redelivered. The guard is what makes
    the second run a no-op.
    """
    task = StatusGuarded()
    task.stage("01J0RESUME")
    spec = spec_for("resume.process", task, "resume_id + status guard")

    await run_to_completion(spec, ("01J0RESUME",), sleep=nap)
    assert task.side_effects == ["01J0RESUME"]

    redelivered = await run_to_completion(spec, ("01J0RESUME",), sleep=nap)

    assert redelivered.completed
    assert task.side_effects == ["01J0RESUME"], "the restart repeated the work"
    assert "skipped" in str(redelivered.result)


async def test_ten_redeliveries_do_the_work_once():
    """A queue that redelivers on every restart, and a deploy loop that keeps
    restarting - the state a bad rollout actually produces."""
    task = StatusGuarded()
    task.stage("01J0RESUME")
    spec = spec_for("resume.process", task, "resume_id + status guard")

    for _ in range(10):
        await run_to_completion(spec, ("01J0RESUME",), sleep=nap)

    assert task.side_effects == ["01J0RESUME"]


async def test_an_interrupted_task_is_not_dead_lettered():
    """A deploy is not a bug.

    Recording `CancelledError` in `failed_tasks` would fill the triage queue
    with the jobs most likely to succeed on their next attempt, and - worse -
    would mark them given up on.
    """
    task = StatusGuarded()
    task.stage("01J0RESUME")
    task.interrupt_at = "01J0RESUME"
    dead = MemoryDeadLetters()
    spec = spec_for("resume.process", task, "resume_id + status guard", max_tries=1)

    with pytest.raises(asyncio.CancelledError):
        await run_once(spec, ("01J0RESUME",), attempt=1, dead_letters=dead)

    assert dead.records == []


async def test_the_kill_lands_inside_the_task_not_before_it():
    """The control. If the interruption fired before the task started, every
    assertion above would be about a task that never ran."""
    task = StatusGuarded()
    task.stage("01J0RESUME")
    task.interrupt_at = "01J0RESUME"
    spec = spec_for("resume.process", task, "resume_id + status guard")

    with pytest.raises(asyncio.CancelledError):
        await run_once(spec, ("01J0RESUME",), attempt=1)

    assert task.started.is_set()


# -- the shape §10 prescribes for `reminders.dispatch` -----------------------


class DedupKeyed:
    """`reminders.dispatch()`, keyed on `dedup_key`.

    `17-data-model.md` §2.11: "`dedup_key` is unique - it is the whole
    idempotency mechanism (NOTIF-05)". A batch claims each key before sending,
    so a batch killed halfway resends nothing it already claimed.
    """

    def __init__(self, due: list[str]) -> None:
        self.due = list(due)
        self.claimed: set[str] = set()
        self.sent: list[str] = []
        self.interrupt_after: int | None = None

    async def __call__(self, batch_size: int = 200) -> int:
        sent = 0
        for key in self.due[:batch_size]:
            if key in self.claimed:
                continue
            self.claimed.add(key)
            if self.interrupt_after is not None and sent >= self.interrupt_after:
                # Killed mid-batch, with some keys claimed and one just claimed
                # but not yet sent.
                self.interrupt_after = None
                raise asyncio.CancelledError
            self.sent.append(key)
            sent += 1
        return sent


async def test_a_batch_killed_halfway_does_not_resend_what_it_sent():
    """AC-FOUND-10.4 for `reminders.dispatch`.

    The failure this prevents is a user getting the same "your interview is
    tomorrow" message four times because the worker restarted four times.
    """
    dispatch = DedupKeyed([f"key-{n}" for n in range(10)])
    dispatch.interrupt_after = 4
    spec = spec_for("reminders.dispatch", dispatch, "dedup_key")

    with pytest.raises(asyncio.CancelledError):
        await run_once(spec, (), attempt=1)
    assert dispatch.sent == ["key-0", "key-1", "key-2", "key-3"]

    await run_to_completion(spec, (), sleep=nap)

    assert len(dispatch.sent) == len(set(dispatch.sent)), "a reminder went out twice"
    # Nine of ten. `key-4` was claimed in the instant before the process died
    # and is deliberately not resent - see the test below for why that is the
    # right way round.
    assert sorted(dispatch.sent) == sorted(f"key-{n}" for n in range(10) if n != 4)


async def test_the_key_claimed_at_the_moment_of_the_kill_is_not_resent():
    """Claim-then-send, deliberately: the key claimed just before the process
    died is *not* sent on the restart.

    That is a lost reminder rather than a duplicate one, and it is the right way
    round. `FOUND-16`'s idempotency window is what lets a send be retried
    safely; nothing makes an unwanted duplicate un-received.
    """
    dispatch = DedupKeyed([f"key-{n}" for n in range(5)])
    dispatch.interrupt_after = 2
    spec = spec_for("reminders.dispatch", dispatch, "dedup_key")

    with pytest.raises(asyncio.CancelledError):
        await run_once(spec, (), attempt=1)
    claimed_at_death = dispatch.claimed - set(dispatch.sent)
    assert len(claimed_at_death) == 1

    await run_to_completion(spec, (), sleep=nap)

    assert claimed_at_death.isdisjoint(dispatch.sent)
    assert len(dispatch.sent) == len(set(dispatch.sent))


async def test_a_dispatch_with_nothing_due_is_a_no_op():
    """The minute-cron case: 1,439 runs a day do nothing, and every one of them
    must stay cheap and silent."""
    dispatch = DedupKeyed([])
    spec = spec_for("reminders.dispatch", dispatch, "dedup_key")
    outcome = await run_to_completion(spec, (), sleep=nap)
    assert outcome.completed
    assert outcome.result == 0
    assert dispatch.sent == []


async def test_two_concurrent_dispatches_do_not_double_send():
    """The overlap `AC-FOUND-10.6`'s lock prevents, asserted here against the
    dedup key as well - defence in depth, because the lock has a TTL and the
    key does not."""
    dispatch = DedupKeyed([f"key-{n}" for n in range(50)])
    spec = spec_for("reminders.dispatch", dispatch, "dedup_key")

    await asyncio.gather(
        run_to_completion(spec, (), sleep=nap),
        run_to_completion(spec, (), sleep=nap),
    )

    assert len(dispatch.sent) == len(set(dispatch.sent)) == 50


# -- what the criterion needs from the framework -----------------------------


async def test_a_cancellation_propagates_rather_than_being_swallowed():
    """The worker has to stop when it is told to.

    A runner that caught `CancelledError` and retried would keep working through
    a shutdown, and the orchestrator would eventually `SIGKILL` it - in the
    middle of whatever it had started instead.
    """

    async def cancelled() -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await run_to_completion(spec_for("ops.backup", cancelled, "date"), (), sleep=nap)


async def test_an_ordinary_failure_still_retries_after_all_this():
    """The control: cancellation is special-cased, and the special case must not
    have swallowed the normal path."""
    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("not yet")
        return "ok"

    outcome = await run_to_completion(spec_for("ops.backup", flaky, "date"), (), sleep=nap)

    assert outcome.completed
    assert calls["n"] == 3


async def test_the_clock_is_the_frozen_one_across_a_restart():
    """HR-10. A task that read `datetime.now()` directly would compute a
    different window on the restart than on the first run, and a
    window-keyed task would then do its work twice."""
    start = clock.now()
    seen: list[Any] = []

    async def windowed(connector: str) -> str:
        seen.append(clock.now())
        return connector

    spec = spec_for("ingest.run", windowed, "connector + run window")
    with clock.freeze(start):
        await run_to_completion(spec, ("adzuna",), sleep=nap)
        await run_to_completion(spec, ("adzuna",), sleep=nap)

    assert seen == [start, start]
