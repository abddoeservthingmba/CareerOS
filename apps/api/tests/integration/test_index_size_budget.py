"""T-DATA-03.4 - the R1 index set fits in Atlas M0.

`AC-DATA-03.4`: "Total index size on the R1 index set stays under 120 MB at 50k
jobs, leaving headroom in Atlas M0's 512 MB (measured, recorded in
`docs/runbooks/atlas-capacity.md`)."

**Why a budget rather than a warning.** M0 is 512 MB of storage, total, for
documents *and* indexes. There is no soft limit: at 512 MB writes fail, and the
first write that fails is somebody's résumé upload. Indexes are the half that
grows without anybody adding data - a new compound index on `jobs` costs tens of
megabytes the moment it is created - so the number that has to be watched is the
index total, and it has to be watched against a stated ceiling rather than
against "it was fine last time".

`DATA-06`'s capacity budget is the arithmetic; this is the measurement.

**Nightly, not per-PR.** §3's Tests list says so, and building 50k jobs takes
minutes. `AC-OPS-03.6` caps a full CI run at 12 minutes, so a per-PR version of
this would either blow that or be run against a corpus too small to mean
anything - and a size check at fixture scale is a check that always passes.

Marked `real_source` rather than `real_ai`: it hits no provider, but it is in
the same nightly-only class and `pytest.ini` deselects both. A third marker for
one test would be a marker nobody remembers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from app.documents import all_documents, collection_name
from app.infra.mongo import init_documents

#: `AC-DATA-03.4`'s two numbers.
BUDGET_BYTES = 120 * 1024 * 1024
JOB_COUNT = 50_000
BATCH = 5_000

#: M0's total. Quoted so the budget's *headroom* is visible in the failure
#: rather than only the budget.
M0_BYTES = 512 * 1024 * 1024

RUNBOOK = Path("docs") / "runbooks" / "atlas-capacity.md"

SIZE_DATABASE = "jobpilot_index_size"

#: The three corpus-dependent tests are nightly-only and share the
#: module-scoped 50k-job fixture, so they also share the loop it was built on -
#: `AsyncMongoClient` binds to the loop it was created on and refuses to be used
#: from another.
#:
#: Applied per test rather than to the module, because the runbook checks below
#: are cheap file reads and belong in the default suite: a missing
#: `atlas-capacity.md` is a repository defect and should not wait for a nightly
#: to be noticed.
nightly = pytest.mark.real_source
on_the_module_loop = pytest.mark.asyncio(loop_scope="module")


def a_job(number: int) -> dict[str, Any]:
    """One realistic listing.

    Realistic *in the fields the indexes cover* - `dedup_key`, `simhash`,
    `title`, `company.name`, `description_text`, `title_family`,
    `location.country`, `status`, `posted_at`. A corpus of empty documents
    would measure the index headers and nothing else, and the text index is the
    largest single cost in the set: its size is driven by the number of distinct
    terms, so a description of `"x"` repeated 50,000 times would report a text
    index of essentially zero.
    """
    from app.core.ids import new_id

    return {
        "_id": new_id(),
        "dedup_key": f"dedup-{number:08d}",
        "simhash": f"{number * 2654435761 % (2**64):020d}",
        "source_refs": [{"source": "adzuna", "external_id": str(number)}],
        "primary_source": "adzuna",
        "title": f"{'Senior' if number % 3 else 'Staff'} Backend Engineer {number % 977}",
        "title_family": "backend_engineer",
        "company": {"name": f"Company {number % 4001}", "normalized": f"company-{number % 4001}"},
        "location": {
            "raw": "Bengaluru, India",
            "country": ["IN", "GB", "US", "DE"][number % 4],
            "remote_mode": ["onsite", "hybrid", "remote"][number % 3],
        },
        "description_text": (
            f"We are looking for engineer {number} to work on distributed systems, "
            f"payments, observability and reliability using python fastapi postgres "
            f"kubernetes terraform, reporting to team {number % 313}."
        ),
        "status": "active",
        "revision": 1,
    }


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def corpus(mongodb_uri: str) -> Any:
    """50k jobs with every declared index, in their own database."""
    from pymongo import AsyncMongoClient

    client: AsyncMongoClient[Any] = AsyncMongoClient(
        mongodb_uri, serverSelectionTimeoutMS=20_000, uuidRepresentation="standard", tz_aware=True
    )
    database = client[SIZE_DATABASE]
    try:
        await client.drop_database(SIZE_DATABASE)
        await init_documents(database, all_documents())
        for start in range(0, JOB_COUNT, BATCH):
            await database["jobs"].insert_many(
                [a_job(number) for number in range(start, start + BATCH)]
            )
        yield database
    finally:
        await client.drop_database(SIZE_DATABASE)
        await client.close()


async def index_sizes(database: Any) -> dict[str, dict[str, int]]:
    """Per collection, per index, bytes. From `collStats`."""
    out: dict[str, dict[str, int]] = {}
    for document in all_documents():
        collection = collection_name(document)
        stats = await database.command("collStats", collection)
        out[collection] = dict(stats.get("indexSizes", {}))
    return out


# -- the criterion ------------------------------------------------------------


@nightly
@on_the_module_loop
async def test_the_r1_index_set_fits_the_budget(corpus: Any):
    """AC-DATA-03.4.

    The failure message reports the per-collection breakdown, because "you are
    over budget" is not actionable and the answer is almost always one index on
    `jobs`.
    """
    sizes = await index_sizes(corpus)
    total = sum(sum(per.values()) for per in sizes.values())

    breakdown = "\n  ".join(
        f"{collection}: {sum(per.values()) / 1024 / 1024:.1f} MB "
        + ", ".join(f"{name}={size / 1024 / 1024:.1f}" for name, size in sorted(per.items()))
        for collection, per in sorted(sizes.items())
        if per
    )

    assert total <= BUDGET_BYTES, (
        f"the R1 index set is {total / 1024 / 1024:.1f} MB at {JOB_COUNT:,} jobs, "
        f"over the {BUDGET_BYTES / 1024 / 1024:.0f} MB budget and "
        f"{total / M0_BYTES:.0%} of M0's {M0_BYTES / 1024 / 1024:.0f} MB total. "
        f"There is no soft limit on M0: at 512 MB writes fail, and the first one "
        f"to fail is somebody's résumé upload.\n  {breakdown}"
    )


@nightly
@on_the_module_loop
async def test_the_measurement_is_not_vacuous(corpus: Any):
    """A budget check against an empty corpus passes and means nothing.

    The realistic way this test rots is a fixture that quietly inserts nothing -
    a renamed collection, a failed batch swallowed somewhere - after which the
    budget is measured against index headers.
    """
    assert await corpus["jobs"].count_documents({}) == JOB_COUNT

    sizes = await index_sizes(corpus)
    assert sum(sizes["jobs"].values()) > 1024 * 1024, (
        "the jobs indexes measure under a megabyte at 50k documents, which means "
        "the corpus is not what it claims to be"
    )


@nightly
@on_the_module_loop
async def test_the_text_index_is_the_one_to_watch(corpus: Any):
    """Reported rather than gated.

    The text index on `jobs` is the largest single entry in the set and the one
    whose growth is least predictable, because its size tracks distinct *terms*
    rather than documents. Naming it here means a future breach has an obvious
    first suspect instead of a 45-row table to read.
    """
    sizes = await index_sizes(corpus)
    jobs = sizes["jobs"]

    assert "job_search" in jobs, "the text index is not present; the budget is not comparable"
    largest = max(jobs, key=lambda name: jobs[name])
    assert largest in {"job_search", "dedup_key", "source_ref"}, (
        f"{largest} is now the largest index on jobs, which is unexpected: {jobs}"
    )


# -- the recorded measurement -------------------------------------------------


def test_the_runbook_records_a_measurement(repo: Path):
    """`AC-DATA-03.4`'s "measured, recorded in
    `docs/runbooks/atlas-capacity.md`".

    The recorded number is what makes a later breach diagnosable: "it is 130 MB
    now" is only useful next to "it was 84 MB in September, and these were the
    six largest". Checked on every run - not only nightly - because the document
    is a repository artifact and its absence should not wait for a nightly.
    """
    assert (repo / RUNBOOK).is_file(), (
        f"{RUNBOOK.as_posix()} is missing. AC-DATA-03.4 requires the measurement "
        "to be recorded, not merely asserted."
    )
    text = (repo / RUNBOOK).read_text(encoding="utf-8")

    assert "120 MB" in text
    assert "50" in text and "jobs" in text
    assert "512 MB" in text


def test_the_runbook_states_the_budget_this_test_enforces(repo: Path):
    """One number in two places is one too many. If the runbook and the constant
    disagree, whichever a person reads is the wrong one."""
    text = (repo / RUNBOOK).read_text(encoding="utf-8")

    assert f"{BUDGET_BYTES // 1024 // 1024} MB" in text
    assert f"{JOB_COUNT:,}" in text or str(JOB_COUNT) in text


def test_the_expensive_tests_are_nightly_only():
    """§3's Tests list: "nightly, not per-PR".

    `AC-OPS-03.6` caps a full CI run at 12 minutes and the fixture takes minutes
    on its own. Asserted rather than trusted, because the way it ends up on the
    merge path is somebody removing a marker to debug it and not putting it
    back.
    """
    import inspect
    import sys

    module = sys.modules[__name__]
    expensive = [
        name
        for name, value in vars(module).items()
        if name.startswith("test_") and "corpus" in inspect.signature(value).parameters
    ]

    assert len(expensive) == 3, f"expected three corpus-dependent tests, found {expensive}"
    for name in expensive:
        marks = {mark.name for mark in getattr(vars(module)[name], "pytestmark", [])}
        assert "real_source" in marks, f"{name} would run on every pull request"
