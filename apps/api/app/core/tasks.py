"""Background tasks - `FOUND-10`.

`01-foundations.md` §10: "Long or expensive work runs off the request path,
survives a restart, retries safely, and never runs twice in a way the user can
notice."

The last clause is the hard one, and it is why almost everything here is a rule
enforced at import time rather than a convention in a style guide.

**A task takes IDs and small scalars only** (`AC-FOUND-10.1`). A queued job is a
message that outlives the deploy that wrote it: a fat payload in Redis goes
stale between enqueue and run, and a schema change breaks every job already in
the queue, at the worst moment - the deploy. A task that needs a document loads
it, and gets the current one.

**Every task states its idempotency key** (`AC-FOUND-10.2`), in a docstring line
that this module refuses to import without. Not documentation for its own sake:
the retry, the restart and the duplicate event all re-run the task, so "what
makes this converge rather than duplicate" is a fact the author knows once and
everyone after them has to reconstruct. Writing it down is the cheapest moment
to notice there is no answer.

**Retries are bounded and end somewhere visible.** Three tries, exponential
backoff with jitter, then the job goes to `failed_tasks` with its arguments and
traceback (`AC-FOUND-10.5`). A task that retries forever is an outage that never
pages anyone; a task that fails silently is a user waiting for something that
will never arrive.

**Cron tasks tolerate overlap** (`AC-FOUND-10.6`). Each takes a Redis lock named
for itself and exits quietly if it is held. Without it, a minute-cron whose run
takes ninety seconds runs two copies forever, and `reminders.dispatch` sends
everything twice.

The registry is the inventory. `R1_TASKS` transcribes §10's table, and
`tests/spec/test_task_signatures.py` compares the two - so a task implemented
but never declared, or declared and quietly dropped, fails the build rather than
drifting.
"""

from __future__ import annotations

import abc
import asyncio
import inspect
import logging
import random
import re
import traceback as traceback_module
from collections.abc import Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, get_args, get_origin, get_type_hints

from pydantic import Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.core import clock
from app.core.documents import BaseDoc

logger = logging.getLogger("app.tasks")

#: §10: "Retries: max 3, exponential backoff with jitter".
DEFAULT_MAX_TRIES = 3
BACKOFF_BASE = timedelta(seconds=5)
BACKOFF_JITTER = 0.25

#: §10: "A task must set a timeout shorter than the queue's visibility window."
#: ARQ's is `job_timeout`; this is the ceiling every task is checked against, so
#: a task cannot declare a timeout that lets the queue hand the same job to a
#: second worker while the first is still holding it.
QUEUE_VISIBILITY = timedelta(minutes=15)
DEFAULT_TIMEOUT = timedelta(seconds=60)

#: §10: "A task expected to exceed 60 s must checkpoint by splitting itself".
#: Not enforced - a long timeout is sometimes right and the alternative would be
#: an override flag that means "ignore this rule" - but stated where the author
#: is choosing the number.
CHUNK_THRESHOLD = timedelta(seconds=60)

#: The prefix `AC-FOUND-10.2` requires.
KEY_PREFIX = "Idempotency key:"

#: `str`, `int`, `bool`, `float`, or a list of those (`AC-FOUND-10.1`).
SCALARS: tuple[type, ...] = (str, int, bool, float)


class TaskDefinitionError(Exception):
    """A task that breaks one of §10's rules.

    Raised at import, so a worker with a malformed task does not start. The
    alternative is finding out when the job runs, which is after it was
    enqueued and therefore after the user was told it would happen.
    """


# -- the declared inventory --------------------------------------------------


@dataclass(frozen=True)
class TaskDeclaration:
    """One row of §10's R1 task/cron inventory."""

    name: str
    trigger: str
    natural_key: str
    note: str

    @property
    def cron(self) -> str | None:
        """The schedule, for the rows whose trigger is a cron expression.

        Matched as five cron fields rather than "the text between backticks":
        the table's markup is presentation, and a transcription that depended on
        it would break the day someone reformatted a row.
        """
        if "cron" not in self.trigger:
            return None
        found = re.search(r"[\d*/,-]+(?: [\d*/,-]+){4}", self.trigger)
        return found.group(0) if found else None


#: `01-foundations.md` §10's table, transcribed. `tests/spec/test_task_signatures.py`
#: parses the table and compares, so this cannot drift from the specification,
#: and a task implemented without a row here fails the same test.
R1_TASKS: tuple[TaskDeclaration, ...] = (
    TaskDeclaration(
        "resume.process",
        "on upload",
        "resume_id + status guard",
        "The 04-resume-pipeline.md §2 stage machine",
    ),
    TaskDeclaration(
        "profile.stage_extraction",
        "ResumeExtracted",
        "resume_id",
        "Produces a review draft, never overwrites confirmed fields",
    ),
    TaskDeclaration(
        "ingest.run",
        "cron per connector, default 0 */6 * * *",
        "connector + run window",
        "Lock-guarded",
    ),
    TaskDeclaration(
        "jobs.enrich",
        "after ingest, gated",
        "job_id + enrichment.model",
        "Budget-gated (05-ai-layer.md §3)",
    ),
    TaskDeclaration("jobs.mark_stale", "end of ingest.run", "connector + run id", ""),
    TaskDeclaration(
        "matching.score_new_jobs",
        "JobsIngested",
        "(user_id, job_id) unique index",
        "Chunked at 200 jobs",
    ),
    TaskDeclaration(
        "matching.rescore_user",
        "ProfileUpdated, debounced",
        "(user_id, profile_version)",
        "Skips if a newer version is queued",
    ),
    TaskDeclaration(
        "matching.rationale",
        "top-N selection",
        "(user_id, job_id, prompt_version)",
        "Off in prod at R1",
    ),
    TaskDeclaration(
        "apply.generate_pack", "route (idempotent)", "application_id + content_hash", ""
    ),
    TaskDeclaration(
        "notifications.reconcile_reminders",
        "status/interview change",
        "dedup_key per occurrence",
        "Cancels stale, schedules new",
    ),
    TaskDeclaration(
        "reminders.dispatch",
        "cron * * * * *",
        "dedup_key",
        "Batches of 200; lock-guarded",
    ),
    TaskDeclaration(
        "account.purge_deleted",
        "cron 0 3 * * *",
        "user_id",
        "7-day hard delete incl. storage",
    ),
    # ADR-013's four retention sweeps. §5's table names a mechanism for every
    # row and its first constraint makes that non-negotiable - "a retention
    # rule with no mechanism is a defect" - but §10's inventory declared only
    # `account.purge_deleted`. The conflict surfaced as a failed import, which
    # is `AC-FOUND-10.4` working as intended.
    #
    # All four at 04:00 UTC: after `ops.backup` (02:00) so a purge is always
    # recoverable from that night's backup, and after `account.purge_deleted`
    # (03:00) so a deleted user's rows are gone before the sweeps run.
    TaskDeclaration(
        "jobs.purge_expired",
        "cron 0 4 * * *",
        "expired_at window + reference check",
        "Clears descriptions on referenced jobs rather than deleting them",
    ),
    TaskDeclaration("connector_runs.purge", "cron 0 4 * * *", "started_at window", "180 days"),
    TaskDeclaration(
        "notifications.purge",
        "cron 0 4 * * *",
        "created_at window",
        "Covers notifications and sent/cancelled reminders",
    ),
    TaskDeclaration(
        "ops.purge_failed_tasks",
        "cron 0 4 * * *",
        "resolved_at window",
        "90 days, resolved only",
    ),
    TaskDeclaration("ops.backup", "cron 0 2 * * *", "date", "mongodump → R2"),
    TaskDeclaration("ops.heartbeat", "cron * * * * *", "minute", "Liveness signal from P0 onward"),
)

DECLARED: dict[str, TaskDeclaration] = {row.name: row for row in R1_TASKS}


# -- the registry -------------------------------------------------------------


@dataclass(frozen=True)
class TaskSpec:
    """An implemented task, with everything the worker needs to run it."""

    name: str
    func: Callable[..., Awaitable[Any]]
    idempotency_key: str
    max_tries: int
    timeout: timedelta
    cron: str | None
    lock: bool

    @property
    def parameters(self) -> list[inspect.Parameter]:
        return list(inspect.signature(self.func).parameters.values())


REGISTRY: dict[str, TaskSpec] = {}


def _scalar(annotation: Any) -> bool:
    """`AC-FOUND-10.1` - `str`, `int`, `bool`, `float`, or a list of those."""
    if annotation in SCALARS:
        return True
    origin = get_origin(annotation)
    if origin in (list, Sequence):
        inner = get_args(annotation)
        return len(inner) == 1 and inner[0] in SCALARS
    return False


#: The spellings a scalar annotation can have as a *string*, which is what
#: `from __future__ import annotations` leaves behind when the real type cannot
#: be resolved - a locally-defined model, say. Refusing an unresolvable
#: annotation is the point: a task parameter whose type nobody can name is a
#: task parameter nobody checked.
SCALAR_SPELLINGS = frozenset(
    {"str", "int", "bool", "float"}
    | {f"list[{name}]" for name in ("str", "int", "bool", "float")}
    | {f"Sequence[{name}]" for name in ("str", "int", "bool", "float")}
)


def annotations_of(func: Callable[..., Awaitable[Any]]) -> dict[str, Any]:
    """Resolved type hints, or the raw strings when they cannot be resolved.

    `get_type_hints` raises `NameError` for an annotation naming something not
    reachable from the module's globals. That is not a reason to skip the check
    - it is the check: an unresolvable annotation is refused below.
    """
    try:
        return dict(get_type_hints(func))
    except (NameError, TypeError):
        return {
            name: parameter.annotation
            for name, parameter in inspect.signature(func).parameters.items()
        }


def _check_signature(name: str, func: Callable[..., Awaitable[Any]]) -> None:
    hints = annotations_of(func)
    for parameter in inspect.signature(func).parameters.values():
        if parameter.name == "ctx":
            # ARQ's own first argument. Not part of the message.
            continue
        annotation = hints.get(parameter.name, parameter.annotation)
        if annotation is inspect.Parameter.empty:
            raise TaskDefinitionError(
                f"{name}: parameter {parameter.name!r} has no annotation, so "
                "AC-FOUND-10.1 cannot be checked on it"
            )
        if isinstance(annotation, str):
            if annotation.replace(" ", "") in SCALAR_SPELLINGS:
                continue
            raise TaskDefinitionError(
                f"{name}: parameter {parameter.name!r} is annotated {annotation!r}, "
                "which could not be resolved to a type. A task signature takes "
                "IDs and small scalars only (§10), and an annotation nobody can "
                "resolve is one nobody checked."
            )
        if not _scalar(annotation):
            raise TaskDefinitionError(
                f"{name}: parameter {parameter.name!r} is {annotation!r}. A task "
                "signature takes IDs and small scalars only (§10): a document in "
                "the queue goes stale between enqueue and run, and a schema "
                "change breaks every job already queued. Pass the id and load it."
            )


def _idempotency_key(name: str, func: Callable[..., Awaitable[Any]]) -> str:
    """`AC-FOUND-10.2` - the docstring line, or a refusal to import."""
    doc = inspect.getdoc(func) or ""
    for line in doc.split("\n"):
        stripped = line.strip()
        if stripped.startswith(KEY_PREFIX):
            key = stripped[len(KEY_PREFIX) :].strip()
            if key:
                return key
    raise TaskDefinitionError(
        f"{name}: no docstring line starting {KEY_PREFIX!r}. Every task is "
        "re-run - by a retry, by a restart, by a duplicate event - and what "
        "makes it converge rather than duplicate is a fact only the author "
        "knows. Writing it down is the cheapest moment to notice there is no "
        "answer."
    )


def task(
    name: str,
    *,
    max_tries: int = DEFAULT_MAX_TRIES,
    timeout: timedelta = DEFAULT_TIMEOUT,
    cron: str | None = None,
    lock: bool | None = None,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Register a background task, or refuse to import.

    Every check here could have been a code-review convention. Each of them is
    instead a failure at import time, because the cost of getting one wrong is
    paid by a user waiting for something that already silently happened twice.
    """

    def decorate(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        if not asyncio.iscoroutinefunction(func):
            raise TaskDefinitionError(f"{name} must be async; the worker awaits it")
        if name in REGISTRY:
            raise TaskDefinitionError(f"{name} is registered twice")
        if name not in DECLARED:
            raise TaskDefinitionError(
                f"{name} is not in §10's R1 task inventory. Add the row to the "
                "specification and to R1_TASKS, or name the task as one that is: "
                f"{sorted(DECLARED)}"
            )
        if timeout >= QUEUE_VISIBILITY:
            raise TaskDefinitionError(
                f"{name}: a timeout of {timeout} is not shorter than the queue's "
                f"visibility window ({QUEUE_VISIBILITY}), so the queue could hand "
                "this job to a second worker while the first still holds it (§10)"
            )
        if max_tries < 1:
            raise TaskDefinitionError(f"{name}: max_tries must be at least 1")

        _check_signature(name, func)
        key = _idempotency_key(name, func)
        declared_cron = DECLARED[name].cron
        if cron is None and declared_cron is not None:
            raise TaskDefinitionError(
                f"{name} is a cron task in §10 (`{declared_cron}`) but was "
                "registered without a schedule"
            )

        REGISTRY[name] = TaskSpec(
            name=name,
            func=func,
            idempotency_key=key,
            max_tries=max_tries,
            timeout=timeout,
            cron=cron,
            # §10: "Cron tasks must tolerate overlapping runs". Defaulted from
            # the schedule rather than asked for, because the author who forgets
            # is the author who wrote a cron.
            lock=(cron is not None) if lock is None else lock,
        )
        if timeout > CHUNK_THRESHOLD:
            logger.info(
                "task declares a timeout over the chunking threshold",
                extra={"task": name, "timeout_seconds": timeout.total_seconds()},
            )
        return func

    return decorate


# -- dead letters -------------------------------------------------------------


class FailedTask(BaseDoc):
    """`17-data-model.md` §2.12 - a job that exhausted its retries.

    Owned by `core`, because the queue is infrastructure and a dead letter
    belongs to whoever operates it rather than to the module whose task failed.

    The arguments and the traceback are both kept, because triage without the
    arguments is guessing and triage without the traceback is reading the code
    and hoping.
    """

    task: str
    args: list[Any] = Field(default_factory=list)
    attempts: int = 0
    error_type: str = ""
    traceback: str = ""
    first_failed_at: datetime
    last_failed_at: datetime
    resolved_at: datetime | None = None

    class Settings:
        name = "failed_tasks"
        indexes = [
            # Triage: "what has been failing, most recent first". Not TTL - a
            # dead-lettered job is work that did not happen, and expiring the
            # record would quietly discard the evidence that it did not.
            IndexModel([("task", ASCENDING), ("last_failed_at", DESCENDING)], name="task_recent"),
        ]


#: `AC-FOUND-10.5`'s "increments the failure metric". A counter here, exported
#: by `OPS-03`'s `/metrics` when it lands - kept in one place so the exporter
#: reads rather than recounts.
FAILURES: dict[str, int] = {}


def failure_count(task_name: str | None = None) -> int:
    if task_name is None:
        return sum(FAILURES.values())
    return FAILURES.get(task_name, 0)


class DeadLetters(abc.ABC):
    """Where a task goes after its last retry.

    A protocol-shaped seam rather than a direct `FailedTask.insert`, so the
    retry policy is testable without Mongo and so `ops` can point it somewhere
    else if the collection is ever unavailable - the one moment you least want
    to lose the traceback.
    """

    @abc.abstractmethod
    async def record(
        self, task_name: str, args: Sequence[Any], error: BaseException, attempts: int
    ) -> None:
        """Store the dead letter, keyed on `(task, args)`.

        Abstract rather than a `NotImplementedError` body: a store that forgot
        to implement it then fails at import, not at the moment a traceback was
        about to be written down - which is the moment you least want to lose it.
        """


class MemoryDeadLetters(DeadLetters):
    """The in-process implementation, for tests and for local runs with no Mongo."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def record(
        self, task_name: str, args: Sequence[Any], error: BaseException, attempts: int
    ) -> None:
        now = clock.now()
        existing = next(
            (row for row in self.records if row["task"] == task_name and row["args"] == list(args)),
            None,
        )
        if existing is not None:
            # Keyed on `(task, args)`: a job that fails on Monday and again on
            # Tuesday is one problem, and two rows would make the triage queue
            # grow with the outage rather than with the number of bugs.
            existing.update(
                attempts=attempts,
                error_type=type(error).__name__,
                traceback=_traceback(error),
                last_failed_at=now,
            )
            return
        self.records.append(
            {
                "task": task_name,
                "args": list(args),
                "attempts": attempts,
                "error_type": type(error).__name__,
                "traceback": _traceback(error),
                "first_failed_at": now,
                "last_failed_at": now,
                "resolved_at": None,
            }
        )


class MongoDeadLetters(DeadLetters):
    """`failed_tasks`, as `17-data-model.md` §2.12 describes it."""

    async def record(
        self, task_name: str, args: Sequence[Any], error: BaseException, attempts: int
    ) -> None:
        now = clock.now()
        existing = await FailedTask.find_one(
            FailedTask.task == task_name, FailedTask.args == list(args)
        )
        if existing is not None:
            existing.attempts = attempts
            existing.error_type = type(error).__name__
            existing.traceback = _traceback(error)
            existing.last_failed_at = now
            await existing.save()
            return
        await FailedTask(
            task=task_name,
            args=list(args),
            attempts=attempts,
            error_type=type(error).__name__,
            traceback=_traceback(error),
            first_failed_at=now,
            last_failed_at=now,
        ).insert()


def _traceback(error: BaseException) -> str:
    return "".join(traceback_module.format_exception(type(error), error, error.__traceback__))


# -- running ------------------------------------------------------------------


def backoff(attempt: int) -> timedelta:
    """§10: "exponential backoff with jitter".

    Jitter is not decoration. A provider outage fails every queued job at once,
    and without it all of them retry at the same instant - three times - which
    is a self-inflicted denial of service against the thing that is already
    struggling.
    """
    base = BACKOFF_BASE.total_seconds() * (2 ** max(0, attempt - 1))
    spread = base * BACKOFF_JITTER
    return timedelta(seconds=base + random.uniform(-spread, spread))


@dataclass
class Outcome:
    """What one attempt did, for the worker to act on."""

    completed: bool
    result: Any = None
    retry_in: timedelta | None = None
    dead_lettered: bool = False
    error: BaseException | None = None


async def run_once(
    spec: TaskSpec,
    args: Sequence[Any],
    *,
    attempt: int = 1,
    dead_letters: DeadLetters | None = None,
) -> Outcome:
    """One attempt at `spec`, with §10's retry and dead-letter policy.

    Separated from the worker so the policy can be asserted without a Redis, a
    worker process, and a wall clock - which is the difference between a test
    that runs in a millisecond and one nobody runs.
    """
    try:
        result = await asyncio.wait_for(spec.func(*args), timeout=spec.timeout.total_seconds())
    except asyncio.CancelledError:
        # A shutdown, not a failure. Re-raised so the worker stops; the job goes
        # back to the queue and the task's idempotency key makes the re-run safe
        # (`AC-FOUND-10.4`).
        raise
    except Exception as error:
        if attempt < spec.max_tries:
            wait = backoff(attempt)
            logger.warning(
                "task failed; retrying",
                extra={
                    "task": spec.name,
                    "attempt": attempt,
                    "error": type(error).__name__,
                    "retry_in_seconds": round(wait.total_seconds(), 2),
                },
            )
            return Outcome(completed=False, retry_in=wait, error=error)

        FAILURES[spec.name] = FAILURES.get(spec.name, 0) + 1
        if dead_letters is not None:
            await dead_letters.record(spec.name, args, error, attempt)
        logger.error(
            "task exhausted its retries",
            extra={"task": spec.name, "attempts": attempt, "error": type(error).__name__},
        )
        return Outcome(completed=False, dead_lettered=True, error=error)

    return Outcome(completed=True, result=result)


async def run_to_completion(
    spec: TaskSpec,
    args: Sequence[Any],
    *,
    dead_letters: DeadLetters | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> Outcome:
    """Every attempt, in order. What the worker does, without the worker."""
    wait = sleep or asyncio.sleep
    for attempt in range(1, spec.max_tries + 1):
        outcome = await run_once(spec, args, attempt=attempt, dead_letters=dead_letters)
        if outcome.completed or outcome.dead_lettered:
            return outcome
        if outcome.retry_in is not None:
            await wait(outcome.retry_in.total_seconds())
    return outcome  # pragma: no cover - the loop always returns


# -- cron locks ---------------------------------------------------------------

#: Long enough that a slow run keeps its lock, short enough that a killed worker
#: does not block the schedule for an hour.
LOCK_TTL = timedelta(minutes=5)


@asynccontextmanager
async def cron_lock(redis: Any, name: str, ttl: timedelta = LOCK_TTL) -> Any:
    """`AC-FOUND-10.6` - one run does the work, the other exits quietly.

    `SET key value NX PX` again: the same primitive as `FOUND-08`'s claim, for
    the same reason. A minute-cron whose run takes ninety seconds otherwise runs
    two copies forever, and for `reminders.dispatch` that means every reminder
    twice.

    Quietly, not loudly: an overlapping run is the expected state of a busy
    system, and a warning per minute is a warning nobody reads.
    """
    key = f"cronlock:{name}"
    held = bool(await redis.set(key, "1", nx=True, px=int(ttl.total_seconds() * 1000)))
    try:
        yield held
    finally:
        if held:
            await redis.delete(key)


async def queue_depth(redis: Any, queue_name: str = "arq:queue") -> int:
    """§10's Outputs: the queue-depth metric.

    The number `OPS-03` scrapes and `15-infra-and-ops.md` §4 alerts on. A queue
    that is growing is the first visible sign that the worker is wedged, and it
    is visible minutes before anything else is.
    """
    return int(await redis.zcard(queue_name))


__all__ = [
    "BACKOFF_BASE",
    "CHUNK_THRESHOLD",
    "DECLARED",
    "DEFAULT_MAX_TRIES",
    "DEFAULT_TIMEOUT",
    "FAILURES",
    "KEY_PREFIX",
    "LOCK_TTL",
    "QUEUE_VISIBILITY",
    "R1_TASKS",
    "REGISTRY",
    "SCALARS",
    "SCALAR_SPELLINGS",
    "DeadLetters",
    "FailedTask",
    "MemoryDeadLetters",
    "MongoDeadLetters",
    "Outcome",
    "TaskDeclaration",
    "TaskDefinitionError",
    "TaskSpec",
    "annotations_of",
    "backoff",
    "cron_lock",
    "failure_count",
    "queue_depth",
    "run_once",
    "run_to_completion",
    "task",
]
