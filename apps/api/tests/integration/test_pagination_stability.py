"""T-FOUND-07.1 - paging never repeats or skips.

`AC-FOUND-07.1`: "Paging fully through a 500-item collection returns each item
exactly once, with 20 items inserted and 20 deleted midway (no duplicates, no
skips of items that existed for the whole traversal)."

This is the criterion offset pagination cannot meet. `skip(400).limit(20)` counts
from the start of the collection every time, so a document deleted before your
position shifts every later page by one and the item that slides across the
boundary is never shown. On a matches feed that is a job the user was told about
and then could not find.

**Two backends, on purpose.** The keyset expansion is arithmetic on an ordering,
and its bugs - an off-by-one in the tie-break, a `$gt` where `$gte` belongs, a
null that swallows the rest of the page - are bugs in that arithmetic. The
in-memory backend runs it a few thousand times under hypothesis in under a
second, which is where those are caught. The Mongo backend then runs the same
traversal against the real thing, because the arithmetic is only correct if BSON
agrees about the order - and BSON is where null sorts before every number, which
no amount of reasoning about the filter would have told us.

"No skips of items that existed for the whole traversal" is the exact claim: an
item deleted midway may legitimately vanish, and an item inserted midway may
legitimately appear or not depending on where it lands. What may never happen is
an item that was there throughout going unseen.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.shared.pagination import (
    Page,
    PaginationRequest,
    SortKey,
    SortSpec,
    paginate,
)

SECRET = "a-secret-long-enough-for-the-settings-validator-to-accept"
OWNER = "01J000000000000000000OWNER"

#: A nullable secondary key, because that is the sort the matches feed uses and
#: the one whose keyset expansion is easy to get wrong.
BY_SCORE = SortSpec((SortKey("score", -1, nullable=True, nulls="last"),))
BY_ID = SortSpec()


# -- an in-memory Mongo, for the operators this module generates -------------


def _matches(document: dict[str, Any], criteria: dict[str, Any]) -> bool:
    """`$or`, `$gt`, `$lt`, `$ne` and equality - all `keyset_filter` emits.

    Deliberately not a general query engine. A fuller one would be a second
    implementation to keep correct, and every operator it supported that
    `keyset_filter` never emits would be untested code pretending to be tested.
    """
    for field, condition in criteria.items():
        if field == "$or":
            if not any(_matches(document, branch) for branch in condition):
                return False
            continue
        value = document.get(field)
        if isinstance(condition, dict):
            for operator, operand in condition.items():
                if operator == "$gt" and not _gt(value, operand):
                    return False
                if operator == "$lt" and not _gt(operand, value):
                    return False
                if operator == "$ne" and value == operand:
                    return False
        elif value != condition:
            return False
    return True


def _gt(left: Any, right: Any) -> bool:
    """BSON comparison for the types a sort key may hold.

    Null is not comparable to a number with `$gt`: in Mongo `{"a": {"$gt": null}}`
    matches nothing, and a keyset expansion that assumed otherwise would stop
    dead at the first null and silently lose the rest of the list.
    """
    if left is None or right is None:
        return False
    return bool(left > right)


def _order_key(value: Any) -> tuple[int, Any]:
    """BSON type ordering: MinKey < Null < numbers < strings.

    Null sorts *first* ascending, whatever the caller would prefer, which is why
    `SortKey` refuses a null position Mongo will not honour.
    """
    if value is None:
        return (0, 0)
    return (1, value)


class MemoryQuery:
    """A `Findable` over a list."""

    def __init__(self, rows: list[dict[str, Any]], criteria: dict[str, Any] | None = None):
        self._rows = rows
        self._criteria = criteria or {}
        self._sort: list[tuple[str, int]] = []
        self._limit: int | None = None

    def find(self, criteria: dict[str, Any] | None = None) -> MemoryQuery:
        return MemoryQuery(self._rows, criteria)

    def sort(self, keys: list[tuple[str, int]]) -> MemoryQuery:
        self._sort = keys
        return self

    def limit(self, count: int) -> MemoryQuery:
        self._limit = count
        return self

    async def to_list(self) -> list[dict[str, Any]]:
        selected = [row for row in self._rows if _matches(row, self._criteria)]
        for field, direction in reversed(self._sort):
            selected.sort(key=lambda row: _order_key(row.get(field)), reverse=direction == -1)
        return selected if self._limit is None else selected[: self._limit]


class MongoQuery:
    """The same shape over a real collection.

    PyMongo's async cursor already answers `sort`, `limit` and `to_list`, so the
    only thing this adds is `find` returning itself - which is what makes one
    `paginate` work against both a `Document` and a raw collection.
    """

    def __init__(self, collection: Any):
        self._collection = collection

    def find(self, criteria: dict[str, Any] | None = None) -> Any:
        return self._collection.find(criteria or {})


# -- the traversal ----------------------------------------------------------


async def walk(
    query: Any,
    sort: SortSpec,
    limit: int = 25,
    interrupt: Any = None,
) -> list[str]:
    """Page all the way through, returning the ids in the order they were seen.

    `interrupt` is called once, halfway, with the number of pages read so far -
    that is where `AC-FOUND-07.1`'s insert and delete happen.
    """
    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    fired = False

    while True:
        page: Page[dict[str, Any]] = await paginate(
            query,
            sort,
            PaginationRequest(cursor=cursor, limit=limit, user_id=OWNER, secret=SECRET),
        )
        seen.extend(str(row["_id"]) for row in page.items)
        pages += 1

        if interrupt is not None and not fired and len(seen) >= 250:
            await interrupt()
            fired = True

        if not page.has_more or page.next_cursor is None:
            return seen
        cursor = page.next_cursor
        # A page always advances by at least one row, so the traversal cannot
        # need more pages than there are rows. Anything beyond that is a filter
        # that re-serves a position instead of moving past it.
        assert pages <= len(seen) + 1, "the traversal is not terminating"


def rows(count: int, *, scored: bool = True, start: int = 0) -> list[dict[str, Any]]:
    """`_id`s that sort like ULIDs, and a score with deliberate ties and nulls.

    Ties, because a sort with no tie-break repeats or skips exactly the tie
    group and a fixture with 500 distinct scores would never notice. Nulls,
    because that is the branch of the keyset filter with no `$gt` available.
    """
    made = []
    for index in range(start, start + count):
        score: float | None = float((index % 17) * 5)
        if index % 23 == 0:
            score = None
        made.append({"_id": f"01J{index:023d}", "score": score, "user_id": OWNER})
    return made


# -- the criterion, in memory ------------------------------------------------


@pytest.mark.parametrize("sort", [BY_ID, BY_SCORE], ids=["by_id", "by_score"])
@pytest.mark.parametrize("limit", [1, 7, 25, 100])
async def test_a_quiet_traversal_returns_every_item_once(sort: SortSpec, limit: int):
    """The control. If this fails, nothing below means anything."""
    data = rows(500)
    seen = await walk(MemoryQuery(data), sort, limit)

    assert len(seen) == 500
    assert len(set(seen)) == 500, "an item was returned twice"
    assert set(seen) == {row["_id"] for row in data}


@pytest.mark.parametrize("sort", [BY_ID, BY_SCORE], ids=["by_id", "by_score"])
async def test_the_criterion_scenario(sort: SortSpec):
    """AC-FOUND-07.1, exactly as written: 500 items, 20 in and 20 out midway."""
    data = rows(500)
    survivors = {row["_id"] for row in data}

    async def interrupt() -> None:
        for row in rows(20, start=900):  # inserted midway
            data.append(row)
        for row in data[:20]:  # deleted midway, from before the position
            if row in data:
                data.remove(row)
                survivors.discard(row["_id"])

    seen = await walk(MemoryQuery(data), sort, 25, interrupt)

    assert len(seen) == len(set(seen)), "an item was returned twice"
    still_present = {row["_id"] for row in data} & survivors
    missed = still_present - set(seen)
    assert missed == set(), f"{len(missed)} items present throughout were never returned"


@settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    size=st.integers(min_value=1, max_value=120),
    limit=st.integers(min_value=1, max_value=30),
    inserts=st.integers(min_value=0, max_value=15),
    deletes=st.integers(min_value=0, max_value=15),
    ascending=st.booleans(),
)
async def test_interleaved_writes_never_lose_a_stable_item(
    size: int, limit: int, inserts: int, deletes: int, ascending: bool
):
    """AC-FOUND-07.1 generalised.

    Hypothesis rather than a fixed scenario because the failures worth finding
    are at the boundaries - a page whose last row is the last of a tie group, a
    delete that removes exactly the row the cursor points at, a null in the
    final position - and those are chosen badly by hand.
    """
    sort = SortSpec(
        (
            SortKey(
                "score",
                1 if ascending else -1,
                nullable=True,
                nulls="first" if ascending else "last",
            ),
        )
    )
    data = rows(size)
    survivors = {row["_id"] for row in data}

    async def interrupt() -> None:
        data.extend(rows(inserts, start=5000))
        for row in list(data[:deletes]):
            data.remove(row)
            survivors.discard(row["_id"])

    seen = await walk(MemoryQuery(data), sort, limit, interrupt)

    assert len(seen) == len(set(seen)), "an item was returned twice"
    assert ({row["_id"] for row in data} & survivors) - set(seen) == set()


async def test_the_cursor_points_at_a_row_that_was_deleted():
    """The nastiest case, and the reason keyset beats offset.

    The cursor holds a *position*, not a row id, so deleting the row it names
    changes nothing: the next page still asks for "everything after these sort
    values". Offset pagination would shift by one and lose an item here.
    """
    data = rows(60)
    page: Page[dict[str, Any]] = await paginate(
        MemoryQuery(data),
        BY_ID,
        PaginationRequest(limit=25, user_id=OWNER, secret=SECRET),
    )
    assert page.next_cursor

    last_seen = page.items[-1]["_id"]
    data.remove(next(row for row in data if row["_id"] == last_seen))

    second: Page[dict[str, Any]] = await paginate(
        MemoryQuery(data),
        BY_ID,
        PaginationRequest(cursor=page.next_cursor, limit=25, user_id=OWNER, secret=SECRET),
    )
    first_page_ids = {row["_id"] for row in page.items}
    assert not first_page_ids & {row["_id"] for row in second.items}
    assert len(second.items) == 25


async def test_an_empty_collection_pages_once_and_stops():
    page: Page[dict[str, Any]] = await paginate(
        MemoryQuery([]),
        BY_ID,
        PaginationRequest(user_id=OWNER, secret=SECRET),
    )
    assert page.items == []
    assert page.has_more is False
    assert page.next_cursor is None


async def test_an_exact_multiple_of_the_limit_does_not_promise_another_page():
    """`has_more` comes from fetching `limit + 1`, not from a count. 50 items at
    25 a page must end after two, not offer an empty third."""
    seen = await walk(MemoryQuery(rows(50)), BY_ID, 25)
    assert len(seen) == 50

    page: Page[dict[str, Any]] = await paginate(
        MemoryQuery(rows(25)),
        BY_ID,
        PaginationRequest(limit=25, user_id=OWNER, secret=SECRET),
    )
    assert page.has_more is False
    assert page.next_cursor is None


# -- the same traversal, against Mongo ---------------------------------------


@pytest.mark.parametrize("sort", [BY_ID, BY_SCORE], ids=["by_id", "by_score"])
async def test_mongo_agrees_about_the_order(database: Any, sort: SortSpec):
    """AC-FOUND-07.1 against the real thing.

    The in-memory backend proves the keyset arithmetic; this proves BSON orders
    values the way that arithmetic assumed. They are different claims, and only
    the second one catches "null sorts before every number".
    """
    collection = database["pagination_stability"]
    data = rows(500)
    await collection.insert_many(data)

    seen = await walk(MongoQuery(collection), sort, 25)

    assert len(seen) == 500
    assert len(set(seen)) == 500, "an item was returned twice"
    assert set(seen) == {row["_id"] for row in data}


async def test_mongo_survives_writes_midway(database: Any):
    """AC-FOUND-07.1's second half, against Mongo."""
    collection = database["pagination_stability"]
    data = rows(500)
    await collection.insert_many(data)
    survivors = {row["_id"] for row in data}

    async def interrupt() -> None:
        await collection.insert_many(rows(20, start=900))
        doomed = [row["_id"] for row in data[:20]]
        await collection.delete_many({"_id": {"$in": doomed}})
        survivors.difference_update(doomed)

    seen = await walk(MongoQuery(collection), BY_SCORE, 25, interrupt)

    assert len(seen) == len(set(seen)), "an item was returned twice"
    remaining = {row["_id"] async for row in collection.find({}, {"_id": 1})}
    assert (remaining & survivors) - set(seen) == set()


async def test_mongo_and_memory_produce_the_same_order(database: Any):
    """If they ever disagree, one of the two tests above is lying about the
    other's subject."""
    collection = database["pagination_stability"]
    data = rows(200)
    await collection.insert_many([dict(row) for row in data])

    assert await walk(MongoQuery(collection), BY_SCORE, 25) == await walk(
        MemoryQuery(data), BY_SCORE, 25
    )
