"""T-FOUND-10.5 - where a job goes after its last retry.

`AC-FOUND-10.5`: "A task that exhausts retries appears in `failed_tasks` with
arguments and traceback, and increments the failure metric."

Two properties, and both are about what happens *after* nobody is watching.

**It ends somewhere.** A task that retries forever is an outage that never pages
anyone: the queue drains, the metrics look fine, and a user waits for a pack
that will never arrive. Three tries and then a row.

**The row is enough to act on.** Arguments and traceback, both. Triage without
the arguments is guessing which of four hundred rows is the one the user is
complaining about; triage without the traceback is reading the code and hoping.

`17-data-model.md` §2.12 fixes the shape: `task`, `args`, `attempts`,
`error_type`, `traceback`, `first_failed_at`, `last_failed_at`, `resolved_at`.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from app.core import clock
from app.core.tasks import (
    BACKOFF_BASE,
    DEFAULT_MAX_TRIES,
    FAILURES,
    FailedTask,
    MemoryDeadLetters,
    TaskSpec,
    backoff,
    failure_count,
    run_once,
    run_to_completion,
)

NAME = "resume.process"


class Flaky:
    """Fails a stated number of times, then succeeds."""

    def __init__(self, failures: int, error: type[Exception] = RuntimeError) -> None:
        self.calls = 0
        self._failures = failures
        self._error = error

    async def __call__(self, resume_id: str) -> str:
        self.calls += 1
        if self.calls <= self._failures:
            raise self._error(f"attempt {self.calls} failed")
        return f"processed {resume_id}"


def spec_for(func: Any, *, max_tries: int = DEFAULT_MAX_TRIES) -> TaskSpec:
    """A `TaskSpec` built directly, bypassing the registry.

    The registry refuses a name that is not in §10's inventory and refuses the
    same name twice, both of which are correct for real tasks and useless for a
    failure fixture. What is being asserted here is the retry policy, not the
    registration rules - those are `tests/spec/test_task_signatures.py`'s.
    """
    return TaskSpec(
        name=NAME,
        func=func,
        idempotency_key="resume_id + status guard",
        max_tries=max_tries,
        timeout=timedelta(seconds=5),
        cron=None,
        lock=False,
    )


async def nap(_: float) -> None:
    return None


@pytest.fixture(autouse=True)
def clean_metric():
    """The counter is process-global, as a metric is. Reset around each test so
    one failure does not read as two."""
    FAILURES.clear()
    yield
    FAILURES.clear()


# -- the retry policy --------------------------------------------------------


async def test_a_task_that_recovers_is_not_dead_lettered():
    """The control. Without it, an implementation that dead-lettered everything
    would pass every assertion below."""
    flaky = Flaky(failures=2)
    dead = MemoryDeadLetters()

    outcome = await run_to_completion(
        spec_for(flaky), ("01J0RESUME",), dead_letters=dead, sleep=nap
    )

    assert outcome.completed
    assert outcome.result == "processed 01J0RESUME"
    assert flaky.calls == 3
    assert dead.records == []
    assert failure_count() == 0


async def test_three_tries_and_then_a_row():
    """AC-FOUND-10.5, the count. §10: "Retries: max 3"."""
    flaky = Flaky(failures=99)
    dead = MemoryDeadLetters()

    outcome = await run_to_completion(
        spec_for(flaky), ("01J0RESUME",), dead_letters=dead, sleep=nap
    )

    assert not outcome.completed
    assert outcome.dead_lettered
    assert flaky.calls == DEFAULT_MAX_TRIES == 3
    assert len(dead.records) == 1


async def test_the_row_carries_the_arguments():
    """AC-FOUND-10.5, "with arguments". Without them, triage is guessing which
    of four hundred rows is the one being complained about."""
    dead = MemoryDeadLetters()
    await run_to_completion(
        spec_for(Flaky(failures=99)), ("01J0RESUME", 7), dead_letters=dead, sleep=nap
    )

    assert dead.records[0]["args"] == ["01J0RESUME", 7]


async def test_the_row_carries_the_traceback_and_the_error_type():
    """AC-FOUND-10.5, "and traceback"."""
    dead = MemoryDeadLetters()

    class Specific(RuntimeError):
        pass

    await run_to_completion(
        spec_for(Flaky(failures=99, error=Specific)), ("01J0RESUME",), dead_letters=dead, sleep=nap
    )

    row = dead.records[0]
    assert row["error_type"] == "Specific"
    assert "Traceback" in row["traceback"]
    assert "attempt 3 failed" in row["traceback"]
    assert row["attempts"] == 3


async def test_the_failure_metric_is_incremented():
    """AC-FOUND-10.5, "and increments the failure metric".

    Once per dead letter, not once per attempt: a rate alert on three retries of
    one broken job would fire on every transient outage.
    """
    await run_to_completion(
        spec_for(Flaky(failures=99)), ("01J0RESUME",), dead_letters=MemoryDeadLetters(), sleep=nap
    )

    assert failure_count(NAME) == 1
    assert failure_count() == 1


async def test_the_metric_is_not_incremented_by_a_retry_that_succeeds():
    await run_to_completion(
        spec_for(Flaky(failures=2)), ("01J0RESUME",), dead_letters=MemoryDeadLetters(), sleep=nap
    )
    assert failure_count() == 0


async def test_the_same_job_failing_twice_is_one_row():
    """Keyed on `(task, args)`. Two rows would make the triage queue grow with
    the length of the outage rather than with the number of bugs."""
    dead = MemoryDeadLetters()
    start = clock.now()

    with clock.freeze(start):
        await run_to_completion(
            spec_for(Flaky(failures=99)), ("01J0RESUME",), dead_letters=dead, sleep=nap
        )
    with clock.freeze(start + timedelta(hours=6)):
        await run_to_completion(
            spec_for(Flaky(failures=99)), ("01J0RESUME",), dead_letters=dead, sleep=nap
        )

    assert len(dead.records) == 1
    row = dead.records[0]
    assert row["first_failed_at"] == start
    assert row["last_failed_at"] == start + timedelta(hours=6)


async def test_different_arguments_are_different_rows():
    dead = MemoryDeadLetters()
    for resume_id in ("01J0A", "01J0B"):
        await run_to_completion(
            spec_for(Flaky(failures=99)), (resume_id,), dead_letters=dead, sleep=nap
        )
    assert len(dead.records) == 2


async def test_a_timeout_is_a_failure_like_any_other():
    """§10 gives every task a timeout. A task that hangs must dead-letter rather
    than hold a worker slot until someone notices."""
    import asyncio

    async def hangs(resume_id: str) -> None:
        await asyncio.sleep(60)

    spec = TaskSpec(
        name=NAME,
        func=hangs,
        idempotency_key="resume_id + status guard",
        max_tries=1,
        timeout=timedelta(milliseconds=20),
        cron=None,
        lock=False,
    )
    dead = MemoryDeadLetters()

    outcome = await run_once(spec, ("01J0RESUME",), attempt=1, dead_letters=dead)

    assert outcome.dead_lettered
    assert dead.records[0]["error_type"] == "TimeoutError"


async def test_a_cancellation_is_not_a_failure():
    """A shutdown is not a bug. Dead-lettering on `CancelledError` would fill
    `failed_tasks` with the jobs that were interrupted by a deploy - which are
    exactly the ones that should be retried, not given up on
    (`AC-FOUND-10.4`)."""
    import asyncio

    async def interrupted(resume_id: str) -> None:
        raise asyncio.CancelledError

    dead = MemoryDeadLetters()
    with pytest.raises(asyncio.CancelledError):
        await run_once(spec_for(interrupted), ("01J0RESUME",), attempt=3, dead_letters=dead)

    assert dead.records == []
    assert failure_count() == 0


# -- backoff -----------------------------------------------------------------


def test_the_backoff_is_exponential():
    """§10: "exponential backoff with jitter"."""
    first = [backoff(1).total_seconds() for _ in range(50)]
    second = [backoff(2).total_seconds() for _ in range(50)]
    third = [backoff(3).total_seconds() for _ in range(50)]

    assert max(first) < min(second)
    assert max(second) < min(third)
    assert min(first) > 0


def test_the_backoff_has_jitter():
    """Not decoration. A provider outage fails every queued job at once, and
    without jitter all of them retry at the same instant - three times - which
    is a self-inflicted denial of service against something already struggling.
    """
    draws = {backoff(2).total_seconds() for _ in range(50)}
    assert len(draws) > 40, "the delay is the same every time"


def test_the_backoff_is_centred_on_the_exponential_value():
    base = BACKOFF_BASE.total_seconds()
    draws = [backoff(1).total_seconds() for _ in range(200)]
    assert base * 0.7 < sum(draws) / len(draws) < base * 1.3


async def test_the_worker_waits_between_attempts():
    """Asserted through the runner, because a backoff nothing awaits is a
    comment."""
    waited: list[float] = []

    async def record(seconds: float) -> None:
        waited.append(seconds)

    await run_to_completion(
        spec_for(Flaky(failures=99)),
        ("01J0RESUME",),
        dead_letters=MemoryDeadLetters(),
        sleep=record,
    )

    # Two waits for three attempts: after the first and second, not the last.
    assert len(waited) == 2
    assert waited[0] < waited[1]


# -- the document ------------------------------------------------------------


def test_the_document_has_the_fields_the_data_model_names():
    """`17-data-model.md` §2.12, exactly."""
    assert set(FailedTask.model_fields) >= {
        "task",
        "args",
        "attempts",
        "error_type",
        "traceback",
        "first_failed_at",
        "last_failed_at",
        "resolved_at",
    }


def test_the_collection_is_the_one_the_data_model_names():
    assert FailedTask.Settings.name == "failed_tasks"


def test_an_unresolved_row_has_no_resolution_time():
    """`resolved_at` is the triage state. Defaulting it to now would mark every
    dead letter as already handled.

    Read off the field rather than off an instance: a Beanie `Document` cannot
    be constructed before `init_beanie`, and the default is the fact under test.
    """
    assert FailedTask.model_fields["resolved_at"].default is None
    assert FailedTask.model_fields["attempts"].default == 0
