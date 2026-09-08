"""The worker entrypoint - `FOUND-10`.

`01-foundations.md` §1: "`worker.py` - ARQ WorkerSettings + cron table". §10:
"Worker settings and the cron table in `app/worker.py`, in one place."

In one place because a cron schedule spread across the modules that own the
tasks is a schedule nobody can read. The question an operator asks at 3 a.m. is
"what is supposed to be running right now", and the answer has to be one file.

**One image, two entrypoints** (ADR-002). This module and `main.py` are peers:
both compose things the layers below them provide, and neither is imported by
anything else. The `layers` contract names them together for that reason - a
module importing the worker would be a module that knows how it is deployed.

**The tasks themselves live in their modules.** `resume.process` is
`modules/resume`'s, and this file only collects them. The exceptions are the
`ops.*` rows of §10's inventory, which belong to no product module: backing up
the database and emitting a liveness beat are things the deployment does, not
things a feature does.

At P0 the inventory is one row deep. `00-scope-and-phases.md` §5 gives this
phase "ARQ ping + heartbeat cron", and `ops.heartbeat` is both: it proves the
queue is wired end to end and it is the signal that says the worker is alive.
The other thirteen rows arrive with the modules that own them, and
`tests/spec/test_task_signatures.py` holds the inventory to §10's table in the
meantime, so a task cannot appear without a row or a row be quietly dropped.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from app.core import clock
from app.core.config import Settings, get_settings
from app.core.tasks import (
    REGISTRY,
    MongoDeadLetters,
    TaskSpec,
    cron_lock,
    run_once,
    task,
)

logger = logging.getLogger("app.worker")

#: The last beat, in-process. `OPS-05`'s external check reads it through the
#: metric; this is what `ops.heartbeat` updates and what a test can observe
#: without one.
LAST_HEARTBEAT: dict[str, Any] = {"at": None, "beats": 0}


@task("ops.heartbeat", cron="* * * * *", timeout=timedelta(seconds=10))
async def heartbeat(ctx: dict[str, Any] | None = None) -> str:
    """Say the worker is alive, once a minute.

    Idempotency key: the minute. Two beats in the same minute leave the same
    state - a timestamp truncated to the minute and a count that is only ever
    read as "did this change" - so an overlapping cron run is harmless even
    before the lock catches it.

    This is the R1 task that exists from P0 (`00-scope-and-phases.md` §5): it is
    the end-to-end proof that the queue is wired, and the signal whose absence
    is the first thing anyone notices when the worker is wedged.
    """
    now = clock.now()
    minute = now.replace(second=0, microsecond=0)
    if LAST_HEARTBEAT["at"] != minute:
        LAST_HEARTBEAT["at"] = minute
        LAST_HEARTBEAT["beats"] = int(LAST_HEARTBEAT["beats"]) + 1
    logger.info("worker heartbeat", extra={"minute": minute.isoformat()})
    return minute.isoformat()


async def run_task(spec: TaskSpec, ctx: dict[str, Any], *args: Any) -> Any:
    """One attempt, with §10's retry and dead-letter policy applied.

    ARQ owns the retry loop - it re-enqueues with `job_try` incremented - so
    this reports the attempt number it was given rather than counting its own.
    A worker that tracked tries in memory would forget them on the restart that
    `AC-FOUND-10.4` is about.
    """
    attempt = int(ctx.get("job_try", 1))
    outcome = await run_once(spec, args, attempt=attempt, dead_letters=MongoDeadLetters())
    if outcome.completed:
        return outcome.result
    if outcome.dead_lettered:
        # Swallowed on purpose: the job is recorded in `failed_tasks` with its
        # arguments and traceback, and re-raising here would make ARQ retry a
        # job that has already been given up on.
        return None
    assert outcome.error is not None
    raise outcome.error


def _bind(spec: TaskSpec) -> Any:
    """Wrap a registered task in the shape ARQ expects: `f(ctx, *args)`."""

    async def runner(ctx: dict[str, Any], *args: Any) -> Any:
        if spec.lock:
            # `AC-FOUND-10.6`. The redis connection ARQ hands the task in `ctx`,
            # so the lock lives in the same place the queue does and cannot be
            # taken against a different Redis by accident.
            async with cron_lock(ctx["redis"], spec.name) as held:
                if not held:
                    logger.info("cron run skipped; lock held", extra={"task": spec.name})
                    return None
                return await run_task(spec, ctx, *args)
        return await run_task(spec, ctx, *args)

    runner.__name__ = spec.name.replace(".", "_")
    runner.__qualname__ = runner.__name__
    return runner


def functions() -> list[Any]:
    """Every registered task, bound for ARQ."""
    return [_bind(spec) for spec in REGISTRY.values()]


def cron_jobs() -> list[Any]:
    """§10's cron table, derived from the registry rather than restated.

    Derived so the schedule in the specification, the schedule on the task, and
    the schedule the worker runs are one fact. A hand-written table here is a
    fourth copy, and the one that is actually in effect.
    """
    from arq import cron

    jobs = []
    for spec in REGISTRY.values():
        if spec.cron is None:
            continue
        jobs.append(cron(_bind(spec), **_crontab(spec.cron), run_at_startup=False))
    return jobs


def _crontab(expression: str) -> dict[str, Any]:
    """A five-field cron expression, as ARQ's keyword arguments.

    ARQ takes `minute`/`hour`/`day`/`month`/`weekday` sets rather than a string,
    so the specification's `0 */6 * * *` has to be translated. Only the forms
    §10 actually uses are supported - `*`, a number, and `*/n` - because a
    general parser here would be a second cron implementation to keep correct,
    and a wrong one silently runs things at the wrong time.
    """
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError(f"{expression!r} is not a five-field cron expression")
    names = ("minute", "hour", "day", "month", "weekday")
    ranges = {"minute": 60, "hour": 24, "day": 32, "month": 13, "weekday": 7}
    out: dict[str, Any] = {}
    for name, value in zip(names, fields, strict=True):
        if value == "*":
            continue
        start = 1 if name in ("day", "month") else 0
        if value.startswith("*/"):
            step = int(value[2:])
            out[name] = {n for n in range(start, ranges[name]) if n % step == 0}
        elif value.isdigit():
            out[name] = int(value)
        else:
            raise ValueError(
                f"{expression!r}: {value!r} uses cron syntax this translator does "
                "not support. Supported: `*`, a number, `*/n`."
            )
    return out


async def startup(ctx: dict[str, Any]) -> None:
    """Open what every task needs: the database, and the settings.

    The same connections `main.py` opens, in the same way. One image, two
    entrypoints (ADR-002) means the worker is not a second application with its
    own idea of how to reach Mongo.
    """
    from app.documents import all_documents
    from app.infra import mongo

    settings: Settings = get_settings()
    ctx["settings"] = settings
    ctx["mongo"] = mongo.build_client(settings.MONGODB_URI.get_secret_value())
    ctx["database"] = ctx["mongo"][settings.MONGODB_DB]
    # `DATA-02`, from the same registry `main.py` uses. A worker bound to a
    # subset of the documents would fail on whichever task first touched a
    # collection it had not registered - and a task failure is retried three
    # times before anyone sees it.
    await mongo.init_documents(ctx["database"], all_documents())
    logger.info("worker started", extra={"tasks": len(REGISTRY)})


async def shutdown(ctx: dict[str, Any]) -> None:
    client = ctx.get("mongo")
    if client is not None:
        await client.close()


class WorkerSettings:
    """§10's worker settings, in the one place §1 puts them.

    `max_tries = 1` at this level is deliberate and not a weakening: the retry
    policy is `core.tasks`', so that it is the same policy whether a task is run
    by ARQ, by a test, or by a script. Two retry budgets - ARQ's and ours -
    would multiply into nine attempts against a provider that is already down.
    """

    functions = functions()
    cron_jobs = cron_jobs()
    on_startup = startup
    on_shutdown = shutdown

    #: Longer than any task's own timeout, which `core.tasks` checks against
    #: `QUEUE_VISIBILITY` - so the queue never hands a job to a second worker
    #: while the first still holds it.
    job_timeout = 900
    max_tries = 1
    keep_result = 3600
    health_check_interval = 60

    @staticmethod
    def redis_settings() -> Any:
        from arq.connections import RedisSettings

        return RedisSettings.from_dsn(str(get_settings().REDIS_URL))


__all__ = [
    "LAST_HEARTBEAT",
    "WorkerSettings",
    "cron_jobs",
    "functions",
    "heartbeat",
    "run_task",
]
