"""T-FOUND-10.1 / T-FOUND-10.2 - what a task is allowed to look like.

`AC-FOUND-10.1`: "Every task function's parameters are `str`, `int`, `bool`,
`float`, or a list of those. A dict or model parameter fails a contract test."
`AC-FOUND-10.2`: "Every task has a docstring line starting `Idempotency key:`."

Both rules exist because a queued job outlives the deploy that wrote it.

A document in the payload is stale by the time it runs, and a schema change
breaks every job already in the queue - at a deploy, which is the moment you are
least able to look at it. The task takes the id and loads the current thing.

The idempotency key is stranger as a rule and more important in practice. Every
task is re-run: by a retry, by a worker restart, by a duplicate event. Whether
that re-run converges or duplicates is a fact only the author knows, at the
moment they write it, and writing it down is the cheapest opportunity anyone
will ever have to notice that there is no answer.

The checks run at *import*, in `core.tasks.task`, so a malformed task stops the
worker from starting rather than surfacing when the job runs - which is after it
was enqueued and therefore after the user was told it would happen. This file
asserts the enforcement works, and holds the implemented set to §10's table.
"""

from __future__ import annotations

import inspect
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.core.tasks import (
    DECLARED,
    KEY_PREFIX,
    QUEUE_VISIBILITY,
    R1_TASKS,
    REGISTRY,
    SCALARS,
    TaskDefinitionError,
    annotations_of,
    task,
)

# Importing the worker is what registers the implemented tasks.
import app.worker  # noqa: F401  isort:skip


# -- the inventory -----------------------------------------------------------


def table_rows(repo: Path) -> list[tuple[str, str, str]]:
    """§10's "R1 task/cron inventory" table, parsed.

    Parsed rather than transcribed twice: a table in a specification and a tuple
    in a module are two copies of one fact, and the only way they stay equal is
    if something compares them.
    """
    text = (repo / "docs" / "spec" / "01-foundations.md").read_text(encoding="utf-8")
    section = text.split("**R1 task/cron inventory**", 1)[1].split("**Inputs.**", 1)[0]
    rows = []
    for line in section.split("\n"):
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        name = re.sub(r"\(.*\)", "", cells[0].strip("`"))
        # The table marks event names and cron expressions with backticks;
        # `R1_TASKS` records the text, so the comparison strips the markup
        # rather than the transcription carrying it.
        rows.append((name, cells[1].replace("`", ""), cells[2].replace("`", "")))
    return rows


def test_the_declared_inventory_is_the_specifications_table(repo: Path):
    """A row added to §10 fails here until `R1_TASKS` grows it."""
    parsed = table_rows(repo)
    assert [row.name for row in R1_TASKS] == [name for name, _, _ in parsed]
    assert [row.trigger for row in R1_TASKS] == [trigger for _, trigger, _ in parsed]
    assert [row.natural_key for row in R1_TASKS] == [key for _, _, key in parsed]


def test_the_inventory_has_eighteen_rows():
    """The number §10 gives. A test that only compared the two lists would pass
    if both were empty.

    Fourteen until ADR-013, which added the four retention sweeps §5's table
    requires and §10 had not declared. The number is asserted rather than
    derived so a fifteenth-through-nineteenth task is a deliberate edit here as
    well as in the specification.
    """
    assert len(R1_TASKS) == 18
    assert len(DECLARED) == 18


def test_every_implemented_task_is_declared():
    """A task with no row in §10 is a task nobody agreed to run.

    Enforced in `core.tasks.task` at import; asserted here so the enforcement
    itself cannot be removed without a failure.
    """
    assert set(REGISTRY) <= set(DECLARED), sorted(set(REGISTRY) - set(DECLARED))


def test_the_p0_task_is_implemented():
    """`00-scope-and-phases.md` §5 gives P0 "ARQ ping + heartbeat cron".

    The other thirteen arrive with the modules that own them. This keeps the
    file from being vacuous while `app/modules/` is empty: if `ops.heartbeat`
    ever stops being registered, every parametrized test below silently
    parametrizes over nothing.
    """
    assert "ops.heartbeat" in REGISTRY
    assert REGISTRY["ops.heartbeat"].cron == "* * * * *"


def test_every_cron_row_keeps_the_schedule_the_specification_gives():
    for row in R1_TASKS:
        spec = REGISTRY.get(row.name)
        if spec is None or row.cron is None:
            continue
        assert spec.cron == row.cron, f"{row.name} runs on a different schedule than §10"


# -- AC-FOUND-10.1: scalars only ---------------------------------------------


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_parameter_is_a_scalar(name: str):
    """AC-FOUND-10.1."""
    spec = REGISTRY[name]
    hints = annotations_of(spec.func)
    for parameter in spec.parameters:
        if parameter.name == "ctx":
            continue
        annotation = hints[parameter.name]
        assert annotation in SCALARS or _is_scalar_list(annotation), (
            f"{name}.{parameter.name} is {annotation!r}; a queued document goes "
            "stale between enqueue and run"
        )


def _is_scalar_list(annotation: Any) -> bool:
    from typing import get_args, get_origin

    return get_origin(annotation) is list and set(get_args(annotation)) <= set(SCALARS)


def test_a_dict_parameter_is_refused():
    """AC-FOUND-10.1's "A dict or model parameter fails a contract test"."""
    with pytest.raises(TaskDefinitionError, match="scalars only"):

        @task("jobs.mark_stale")
        async def bad(payload: dict[str, str]) -> None:
            """Idempotency key: none."""


def test_a_model_parameter_is_refused():
    from pydantic import BaseModel

    class Payload(BaseModel):
        job_id: str

    with pytest.raises(TaskDefinitionError, match="scalars only"):

        @task("jobs.mark_stale")
        async def bad(payload: Payload) -> None:
            """Idempotency key: none."""


def test_an_unannotated_parameter_is_refused():
    """Otherwise the rule is unenforceable on exactly the parameter someone was
    in a hurry about."""
    with pytest.raises(TaskDefinitionError, match="no annotation"):

        @task("jobs.mark_stale")
        async def bad(job_id) -> None:
            """Idempotency key: none."""


def test_a_list_of_ids_is_allowed():
    """§10's own inventory has `matching.score_new_jobs(job_ids)`, chunked at
    200 - so a list of scalars has to be permitted or the spec contradicts
    itself."""

    @task("jobs.mark_stale")
    async def fine(job_ids: list[str], limit: int) -> None:
        """Idempotency key: connector + run id."""

    assert "jobs.mark_stale" in REGISTRY
    del REGISTRY["jobs.mark_stale"]


# -- AC-FOUND-10.2: the stated key -------------------------------------------


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_task_states_its_idempotency_key(name: str):
    """AC-FOUND-10.2."""
    spec = REGISTRY[name]
    doc = inspect.getdoc(spec.func) or ""
    assert any(line.strip().startswith(KEY_PREFIX) for line in doc.split("\n"))
    assert spec.idempotency_key.strip(), f"{name} states an empty key"


def test_a_task_without_a_key_is_refused():
    with pytest.raises(TaskDefinitionError, match=KEY_PREFIX):

        @task("jobs.mark_stale")
        async def bad(job_id: str) -> None:
            """Marks the job stale."""


def test_a_task_with_a_blank_key_is_refused():
    """ "Idempotency key:" followed by nothing is worse than no line: it looks
    like the question was answered."""
    with pytest.raises(TaskDefinitionError, match=KEY_PREFIX):

        @task("jobs.mark_stale")
        async def bad(job_id: str) -> None:
            """Idempotency key:"""


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_the_stated_key_is_the_one_the_specification_gives(name: str):
    """§10's table names the natural key for every task. A task that states a
    different one in its docstring is either wrong or the table is, and both are
    worth stopping for."""
    declared = DECLARED[name].natural_key.strip("`")
    stated = REGISTRY[name].idempotency_key.lower()
    head = declared.lower().split(" +")[0].split(" per ")[0].strip()
    assert head in stated, f"{name} states {stated!r}, §10 says {declared!r}"


# -- the other rules §10 states ----------------------------------------------


def test_a_synchronous_task_is_refused():
    with pytest.raises(TaskDefinitionError, match="async"):

        @task("jobs.mark_stale")  # type: ignore[arg-type]
        def bad(job_id: str) -> None:
            """Idempotency key: connector + run id."""


def test_registering_the_same_name_twice_is_refused():
    with pytest.raises(TaskDefinitionError, match="twice"):

        @task("ops.heartbeat", cron="* * * * *")
        async def bad(ctx: dict[str, str] | None = None) -> None:
            """Idempotency key: the minute."""


def test_an_undeclared_name_is_refused():
    with pytest.raises(TaskDefinitionError, match="inventory"):

        @task("ops.send_marketing_email")
        async def bad(user_id: str) -> None:
            """Idempotency key: user_id."""


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_timeout_is_shorter_than_the_visibility_window(name: str):
    """§10: "A task must set a timeout shorter than the queue's visibility
    window." Otherwise the queue hands the job to a second worker while the
    first still holds it, and every idempotency key in the system is load-bearing
    at once."""
    assert REGISTRY[name].timeout < QUEUE_VISIBILITY


def test_a_timeout_past_the_visibility_window_is_refused():
    with pytest.raises(TaskDefinitionError, match="visibility"):

        @task("ops.backup", cron="0 2 * * *", timeout=timedelta(hours=1))
        async def bad(ctx: dict[str, str] | None = None) -> None:
            """Idempotency key: date."""


def test_a_cron_task_registered_without_a_schedule_is_refused():
    """§10's table says when it runs. A cron task with no schedule is a task
    that never runs, which is the failure nobody notices."""
    with pytest.raises(TaskDefinitionError, match="without a schedule"):

        @task("reminders.dispatch")
        async def bad(ctx: dict[str, str] | None = None) -> None:
            """Idempotency key: dedup_key."""


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_every_cron_task_takes_a_lock(name: str):
    """`AC-FOUND-10.6` - "Cron tasks must tolerate overlapping runs".

    Defaulted from the schedule in `core.tasks`, not asked for, because the
    author who forgets to ask is the author who just wrote a cron.
    """
    spec = REGISTRY[name]
    if spec.cron is None:
        return
    assert spec.lock, f"{name} runs on a schedule but takes no lock"
