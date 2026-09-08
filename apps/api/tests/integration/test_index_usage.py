"""T-FOUND-07.4 - every paginated query uses an index.

`AC-FOUND-07.4`: "Every paginated query's `explain()` shows an index scan, not a
collection scan, at 100k documents."

At 100k documents a collection scan still *works*. It returns the right rows,
in the right order, in a few hundred milliseconds on a laptop, and every test
above this one passes. It stops working somewhere between there and the first
real user's tenth page, at which point the fix is an index nobody can add
without a maintenance window. That is why the criterion names a document count:
the failure is invisible at fixture scale, and the only way to see it is to
ask the planner what it intends to do.

`explain()` is the assertion because it reports intent rather than outcome. A
query that happens to be fast on a warm cache is not a query that uses an index,
and timing it would pass for the wrong reason on a fast day.

**This file builds its own 100k-document database.** The shared `database`
fixture drops every collection between tests, which would rebuild the corpus per
test; here it is built once per module and dropped at the end. It is the slowest
test in the suite by a wide margin, and it is worth it once.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio

from app.shared.pagination import (
    Cursor,
    SortKey,
    SortSpec,
    keyset_filter,
)

#: `AC-FOUND-07.4` names the number. It is not a tuning knob: at 10k a
#: collection scan is fast enough to hide, which is the whole problem.
DOCUMENT_COUNT = 100_000
BATCH = 5_000

#: Its own database, because the shared `database` fixture empties collections
#: between tests and this corpus costs a minute to build.
INDEX_DATABASE = "jobpilot_index_test"

#: Every test here shares the module-scoped corpus, so every test has to share
#: the event loop it was built on. `AsyncMongoClient` binds to the loop it was
#: created on and refuses to be used from another - so a function-scoped loop
#: with a module-scoped client is a `RuntimeError`, not a slow test.
pytestmark = pytest.mark.asyncio(loop_scope="module")

OWNER = "01J000000000000000000OWNER"
OTHER = "01J000000000000000000OTHER"

#: The matches feed's order, which is the one that matters: scored descending,
#: nulls last, tie-broken by `_id`.
BY_SCORE = SortSpec((SortKey("score", -1, nullable=True, nulls="last"),))
BY_CREATED = SortSpec((SortKey("created_at", -1),))
BY_ID = SortSpec()

#: Every sort a paginated R1 list uses, and the index each one needs. The
#: leading `user_id` is not optional: every user-facing query is scoped by owner
#: (`AC-FOUND-05.2`), so an index that does not lead with it cannot serve one.
SORTS: dict[str, tuple[SortSpec, list[tuple[str, int]]]] = {
    "by_score": (BY_SCORE, [("user_id", 1), ("score", -1), ("_id", -1)]),
    "by_created": (BY_CREATED, [("user_id", 1), ("created_at", -1), ("_id", -1)]),
    "by_id": (BY_ID, [("user_id", 1), ("_id", -1)]),
}


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def corpus(mongodb_uri: str) -> AsyncIterator[Any]:
    """100k documents and the declared indexes, built once."""
    from pymongo import AsyncMongoClient

    client: AsyncMongoClient[Any] = AsyncMongoClient(
        mongodb_uri,
        serverSelectionTimeoutMS=30000,
        uuidRepresentation="standard",
        tz_aware=True,
    )
    database = client[INDEX_DATABASE]
    collection = database["paginated"]
    await collection.drop()

    from datetime import UTC, datetime, timedelta

    epoch = datetime(2026, 1, 1, tzinfo=UTC)
    batch: list[dict[str, Any]] = []
    for index in range(DOCUMENT_COUNT):
        batch.append(
            {
                "_id": f"01J{index:023d}",
                # Two owners, so a scan that ignored `user_id` would still find
                # rows and a test that used one owner would not notice.
                "user_id": OWNER if index % 2 == 0 else OTHER,
                "score": None if index % 23 == 0 else float(index % 1000),
                "created_at": epoch + timedelta(seconds=index),
                "deleted_at": None,
            }
        )
        if len(batch) == BATCH:
            await collection.insert_many(batch, ordered=False)
            batch = []
    if batch:
        await collection.insert_many(batch, ordered=False)

    for name, (_, index_keys) in SORTS.items():
        await collection.create_index(index_keys, name=f"pagination_{name}")

    try:
        yield collection
    finally:
        if os.environ.get("KEEP_INDEX_CORPUS") != "1":
            await database.drop_collection("paginated")
        await client.close()


def winning_stages(explanation: dict[str, Any]) -> list[str]:
    """Every stage name in the winning plan, outermost first.

    Walked rather than read off the top: the interesting stage is usually two or
    three levels down under a `SORT` or a `LIMIT`, and asserting on the outermost
    one alone passes whatever the planner chose underneath.
    """
    stages: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "stage" in node:
                stages.append(str(node["stage"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    plan = explanation.get("queryPlanner", {}).get("winningPlan", {})
    walk(plan)
    return stages


async def explain_page(
    collection: Any, sort: SortSpec, criteria: dict[str, Any], limit: int = 25
) -> dict[str, Any]:
    """What the planner intends for one page of a paginated query."""
    explanation: dict[str, Any] = await collection.database.command(
        {
            "explain": {
                "find": collection.name,
                "filter": criteria,
                "sort": dict(sort.mongo_sort()),
                "limit": limit + 1,
            },
            "verbosity": "executionStats",
        }
    )
    return explanation


@pytest.mark.parametrize("name", sorted(SORTS))
async def test_the_first_page_uses_an_index(corpus: Any, name: str):
    """AC-FOUND-07.4, page 1."""
    sort, _ = SORTS[name]
    explanation = await explain_page(corpus, sort, {"user_id": OWNER})
    stages = winning_stages(explanation)

    assert "COLLSCAN" not in stages, f"{name} scans the collection: {stages}"
    assert "IXSCAN" in stages, f"{name} does not reach an index: {stages}"


@pytest.mark.parametrize("name", sorted(SORTS))
async def test_a_deep_page_uses_an_index(corpus: Any, name: str):
    """AC-FOUND-07.4, at a cursor rather than at the start.

    The keyset filter is where an index is most easily lost: a `$or` over
    prefixes can be planned as a union of index scans, or as one collection scan
    if the branches do not line up with the index.
    """
    sort, _ = SORTS[name]
    row = await corpus.find({"user_id": OWNER}).sort(sort.mongo_sort()).skip(500).limit(1).to_list()
    assert row, "the corpus is smaller than expected"

    position = Cursor(
        values=tuple(row[0].get(key.field) for key in sort.all_keys),
        id=row[0]["_id"],
        user_id=OWNER,
        sort=sort.signature(),
    )
    criteria = {"user_id": OWNER, **keyset_filter(sort, position)}
    stages = winning_stages(await explain_page(corpus, sort, criteria))

    assert "COLLSCAN" not in stages, f"{name} scans the collection at depth: {stages}"
    assert "IXSCAN" in stages, f"{name} does not reach an index at depth: {stages}"


@pytest.mark.parametrize("name", sorted(SORTS))
async def test_a_deep_page_examines_a_bounded_number_of_documents(corpus: Any, name: str):
    """The property an index scan is *for*.

    A query can use an index and still walk 50,000 entries. What keyset
    pagination promises is that page 500 costs the same as page 1, and the only
    evidence for that is how many documents the server touched.
    """
    sort, _ = SORTS[name]
    query = corpus.find({"user_id": OWNER}).sort(sort.mongo_sort())
    row = await query.skip(2000).limit(1).to_list()
    position = Cursor(
        values=tuple(row[0].get(key.field) for key in sort.all_keys),
        id=row[0]["_id"],
        user_id=OWNER,
        sort=sort.signature(),
    )
    criteria = {"user_id": OWNER, **keyset_filter(sort, position)}
    explanation = await explain_page(corpus, sort, criteria, limit=25)
    examined = explanation["executionStats"]["totalDocsExamined"]

    # 26 fetched, times the number of `$or` branches, with room for the
    # planner's own probing. Nowhere near the 2000 an offset scan would touch,
    # which is the distinction this asserts.
    assert examined <= 26 * (len(sort.all_keys) + 2), (
        f"{name} examined {examined} documents for a 25-row page"
    )


async def test_an_unindexed_query_is_visibly_a_collection_scan(corpus: Any):
    """The negative control.

    Without it, every assertion above could be passing because `explain()` never
    says `COLLSCAN` in this Mongo version, and nobody would know.

    The *filter* has to be unindexed, not just the sort. A query filtered on
    `user_id` reaches one of the declared indexes for the filter and then sorts
    in memory - `['SORT', 'FETCH', 'IXSCAN']`, no collection scan - which is
    exactly what this test found on its first run. That is worth recording,
    because it is also the shape a *real* regression would take: a paginated
    query that keeps its index for the filter and quietly loses it for the sort
    still reports `IXSCAN`, so the checks above are asserting something weaker
    than their names suggest. `test_a_deep_page_examines_a_bounded_number_of_documents`
    is what covers that gap - an in-memory sort of 50,000 rows shows up there
    as documents examined, whatever the stage list says.
    """
    unindexed = SortSpec((SortKey("deleted_at", -1, nullable=True, nulls="last"),))
    stages = winning_stages(await explain_page(corpus, unindexed, {"deleted_at": None}))
    assert "COLLSCAN" in stages, (
        "a query with no usable index did not report a collection scan, so the "
        f"checks above prove nothing: {stages}"
    )


async def test_the_corpus_is_the_size_the_criterion_names(corpus: Any):
    """`AC-FOUND-07.4` says 100k. At 10k a collection scan is fast enough to
    hide, and every assertion here would pass against a corpus that proves
    nothing."""
    assert await corpus.count_documents({}) == DOCUMENT_COUNT


async def test_every_declared_sort_has_an_index_leading_with_the_owner(corpus: Any):
    """Every user-facing query is scoped by owner (`AC-FOUND-05.2`), so an index
    that does not lead with `user_id` cannot serve one - it would have to scan
    every user's rows and discard them."""
    # `list_indexes()` is itself a coroutine in PyMongo's async driver: it
    # returns the cursor, which is then drained. Chaining `.to_list()` onto the
    # un-awaited coroutine silently produces nothing.
    existing = await (await corpus.list_indexes()).to_list()
    by_name = {index["name"]: list(index["key"].items()) for index in existing}

    for name, (_, index_keys) in SORTS.items():
        assert by_name.get(f"pagination_{name}") == index_keys
        assert index_keys[0][0] == "user_id"


# ============================================================================
# T-DATA-03.2 - `AC-DATA-03.2`'s five named queries.
#
# "The feed query, the search query, the candidate-set query, the dispatch scan,
# and the Kanban query each show `IXSCAN` (not `COLLSCAN`) in `explain()`
# against a seeded 100k-job, 50-user database."
#
# Shares this file because it shares the expensive thing: a corpus at a scale
# where a collection scan is visible. It does *not* share the corpus above,
# which is a synthetic collection built for `FOUND-07`'s pagination sorts. These
# five run against the **real documents and their real declared indexes**, which
# is the only way the check means what it says - an explain against a
# hand-created index proves the index works, not that the product declared it.
#
# The five are named individually in the criterion because each is a different
# shape of query and each loses its index for a different reason:
#
# * the **feed** sorts descending on a score with a tie-break, so it needs the
#   sort keys in the index in that order;
# * the **search** is a text query, which cannot combine with a sort on another
#   field without losing the index;
# * the **candidate set** is four equality predicates, and a missing one turns
#   the index prefix into a partial match;
# * the **dispatch scan** deliberately crosses users (ADR-012), so it is the one
#   a well-meaning "add user_id to every index" change would break;
# * the **Kanban** query sorts on a third field after two equalities, which is
#   the classic ESR shape and the classic place to get the order wrong.
# ============================================================================

#: `AC-DATA-03.2`'s numbers.
JOBS_FOR_EXPLAIN = 100_000
USERS_FOR_EXPLAIN = 50
EXPLAIN_DATABASE = "jobpilot_explain"


def explain_users() -> list[str]:
    return [f"01J{number:023d}" for number in range(USERS_FOR_EXPLAIN)]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def seeded(mongodb_uri: str) -> AsyncIterator[Any]:
    """100k jobs and 50 users, in the real collections with the real indexes."""
    from pymongo import AsyncMongoClient

    from app.documents import all_documents
    from app.infra.mongo import init_documents

    client: AsyncMongoClient[Any] = AsyncMongoClient(
        mongodb_uri,
        serverSelectionTimeoutMS=30000,
        uuidRepresentation="standard",
        tz_aware=True,
    )
    database = client[EXPLAIN_DATABASE]
    try:
        await client.drop_database(EXPLAIN_DATABASE)
        await init_documents(database, all_documents())
        await _seed(database)
        yield database
    finally:
        if os.environ.get("KEEP_INDEX_CORPUS") != "1":
            await client.drop_database(EXPLAIN_DATABASE)
        await client.close()


async def _seed(database: Any) -> None:
    from datetime import UTC, datetime, timedelta

    epoch = datetime(2026, 1, 1, tzinfo=UTC)
    users = explain_users()
    countries = ["IN", "GB", "US", "DE"]
    modes = ["onsite", "hybrid", "remote"]
    families = ["backend_engineer", "frontend_engineer", "data_engineer", "sre"]

    batch: list[dict[str, Any]] = []
    for number in range(JOBS_FOR_EXPLAIN):
        batch.append(
            {
                "_id": f"01JOB{number:021d}",
                "dedup_key": f"dedup-{number:08d}",
                "simhash": f"{number * 2654435761 % (2**64):020d}",
                "primary_source": "adzuna",
                "source_refs": [{"source": "adzuna", "external_id": str(number)}],
                "title": f"Senior Backend Engineer {number % 977}",
                "title_family": families[number % len(families)],
                "company": {
                    "name": f"Company {number % 4001}",
                    "normalized": f"company-{number % 4001}",
                },
                "location": {
                    "raw": "Bengaluru, India",
                    "country": countries[number % len(countries)],
                    "remote_mode": modes[number % len(modes)],
                },
                "description_text": (
                    f"engineer {number} distributed systems payments observability "
                    f"python fastapi postgres kubernetes team {number % 313}"
                ),
                # Not all active: a filter on `status` that matched everything
                # would be a filter the planner could ignore.
                "status": "active" if number % 7 else "expired",
                "last_seen_at": epoch + timedelta(minutes=number % 10_000),
                "posted_at": epoch + timedelta(minutes=number),
                "revision": 1,
            }
        )
        if len(batch) == BATCH:
            await database["jobs"].insert_many(batch, ordered=False)
            batch = []
    if batch:
        await database["jobs"].insert_many(batch, ordered=False)

    # 50 users x 400 scored jobs. Enough that the feed query has a real
    # candidate set per user and a scan would be visible.
    scores: list[dict[str, Any]] = []
    for index, user in enumerate(users):
        for offset in range(400):
            number = (index * 400 + offset) % JOBS_FOR_EXPLAIN
            score = (number * 37) % 101
            scores.append(
                {
                    "_id": f"01MS{index:03d}{offset:018d}",
                    "user_id": user,
                    "job_id": f"01JOB{number:021d}",
                    "score": score,
                    "band": "strong" if score >= 80 else "good" if score >= 65 else "weak",
                    "computed_at": epoch + timedelta(seconds=number),
                    "deleted_at": None,
                }
            )
    await database["match_scores"].insert_many(scores, ordered=False)

    await database["reminders"].insert_many(
        [
            {
                "_id": f"01RM{number:022d}",
                "user_id": users[number % USERS_FOR_EXPLAIN],
                "application_id": f"01AP{number:022d}",
                "type": "follow_up",
                "due_at": epoch + timedelta(minutes=number),
                "status": "scheduled" if number % 3 else "sent",
                "dedup_key": f"follow_up:01AP{number:022d}:{number}",
                "deleted_at": None,
            }
            for number in range(20_000)
        ],
        ordered=False,
    )

    await database["applications"].insert_many(
        [
            {
                "_id": f"01AP{number:022d}",
                "user_id": users[number % USERS_FOR_EXPLAIN],
                "job_id": f"01JOB{number:021d}",
                "status": ["applied", "screening", "interview", "offer"][number % 4],
                "last_activity_at": epoch + timedelta(minutes=number),
                "next_action_at": epoch + timedelta(days=number % 30),
                "deleted_at": None,
            }
            for number in range(10_000)
        ],
        ordered=False,
    )


async def explain_query(
    database: Any,
    collection: str,
    criteria: dict[str, Any],
    sort: dict[str, int] | None = None,
    limit: int = 25,
) -> list[str]:
    """The winning plan's stages for one query."""
    command: dict[str, Any] = {"find": collection, "filter": criteria, "limit": limit}
    if sort:
        command["sort"] = sort
    explanation: dict[str, Any] = await database.command(
        {"explain": command, "verbosity": "executionStats"}
    )
    return winning_stages(explanation)


def assert_indexed(stages: list[str], label: str) -> None:
    assert "COLLSCAN" not in stages, f"the {label} query scans the collection: {stages}"
    assert "IXSCAN" in stages, f"the {label} query does not reach an index: {stages}"


async def test_the_feed_query_uses_an_index(seeded: Any):
    """`AC-DATA-03.2`, the feed. Served by `match_scores (user_id, score desc,
    job_id)`."""
    stages = await explain_query(
        seeded,
        "match_scores",
        {"user_id": explain_users()[0], "deleted_at": None},
        {"score": -1, "job_id": 1},
    )
    assert_indexed(stages, "feed")


async def test_the_search_query_uses_an_index(seeded: Any):
    """`AC-DATA-03.2`, the search. Served by `jobs`' text index.

    No sort on another field: a `$text` query combined with one cannot use the
    text index for both, and `JOB-06` sorts by text score. That is a real
    constraint on the feature rather than a quirk of the test.
    """
    stages = await explain_query(
        seeded, "jobs", {"$text": {"$search": "kubernetes postgres"}, "status": "active"}
    )
    assert_indexed(stages, "search")


async def test_the_candidate_set_query_uses_an_index(seeded: Any):
    """`AC-DATA-03.2`, candidate-set selection. Served by `jobs (title_family,
    location.country, location.remote_mode, status)`.

    All four equality predicates. With three the index still serves it as a
    prefix; the fourth is what keeps expired listings out of the matcher.
    """
    stages = await explain_query(
        seeded,
        "jobs",
        {
            "title_family": "backend_engineer",
            "location.country": "IN",
            "location.remote_mode": "remote",
            "status": "active",
        },
    )
    assert_indexed(stages, "candidate-set")


async def test_the_dispatch_scan_uses_an_index(seeded: Any):
    """`AC-DATA-03.2`, the dispatch scan. Served by `reminders (status,
    due_at)` - ADR-012's system-scan index.

    Deliberately not scoped to a user: "what is due now, for everybody". This
    is the query a well-meaning "add `user_id` to every index" change would
    break, and it would break it into a per-minute collection scan.
    """
    from datetime import UTC, datetime

    stages = await explain_query(
        seeded,
        "reminders",
        {"status": "scheduled", "due_at": {"$lte": datetime(2026, 1, 2, tzinfo=UTC)}},
        {"due_at": 1},
    )
    assert_indexed(stages, "dispatch scan")


async def test_the_kanban_query_uses_an_index(seeded: Any):
    """`AC-DATA-03.2`, the Kanban board. Served by `applications (user_id,
    status, last_activity_at desc)`.

    Equality, equality, sort - the ESR shape. Declaring the three in any other
    order gives an index the planner uses for the filter and not for the sort,
    which still reports `IXSCAN` while sorting the whole column in memory.
    """
    stages = await explain_query(
        seeded,
        "applications",
        {"user_id": explain_users()[0], "status": "applied", "deleted_at": None},
        {"last_activity_at": -1},
    )
    assert_indexed(stages, "Kanban")


async def test_the_seeded_database_is_the_size_the_criterion_names(seeded: Any):
    """ "a seeded 100k-job, 50-user database".

    At 10k a collection scan is fast enough to hide, and with one user every
    `user_id` predicate matches everything - so the planner's choice would not
    be the one it makes in production. Both numbers are the criterion's.
    """
    assert await seeded["jobs"].count_documents({}) == JOBS_FOR_EXPLAIN
    assert len(await seeded["match_scores"].distinct("user_id")) == USERS_FOR_EXPLAIN


async def test_an_unindexed_query_on_the_real_collections_still_scans(seeded: Any):
    """The negative control, on the real collections.

    Without it, five green assertions could all be passing because
    `winning_stages` never reports `COLLSCAN` - a walker that missed the stage
    name would make the whole section vacuous. The filter is on a field no
    declared index covers.
    """
    stages = await explain_query(seeded, "jobs", {"description_html_sanitized": "nothing"})

    assert "COLLSCAN" in stages, (
        "a query with no usable index did not report a collection scan, so the "
        f"five checks above prove nothing: {stages}"
    )
