"""T-FOUND-07.5 - the limit is clamped, and the response says so.

`AC-FOUND-07.5`: "`limit=1000` returns 100 items and `clamped: true`."

`01-foundations.md` §7: "`limit` default 25, max 100. A request over the max is
clamped, not rejected, and the response says so."

Clamped rather than rejected because the request is not wrong - a client
guessing high is a client trying to make one round trip instead of ten, and
failing it breaks a screen the user is looking at. Saying so, because a client
that asked for 1000 and got 100 silently believes it has the whole list, and
stops paging.
"""

from __future__ import annotations

import pytest

from app.shared.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    NEWEST_FIRST,
    Page,
    PaginationRequest,
    SortKey,
    SortSpec,
    clamp_limit,
)

SECRET = "a-secret-long-enough-for-the-settings-validator-to-accept"


def test_the_spec_numbers():
    """§7 states both; a change to either is a spec change."""
    assert DEFAULT_LIMIT == 25
    assert MAX_LIMIT == 100


def test_no_limit_is_the_default():
    assert clamp_limit(None) == (25, False)


def test_a_limit_over_the_maximum_is_clamped_not_rejected():
    """AC-FOUND-07.5."""
    assert clamp_limit(1000) == (100, True)


def test_the_maximum_itself_is_not_reported_as_clamped():
    """A client asking for exactly 100 got exactly what it asked for."""
    assert clamp_limit(100) == (100, False)


def test_a_limit_under_the_maximum_is_untouched():
    assert clamp_limit(1) == (1, False)
    assert clamp_limit(37) == (37, False)


def test_a_limit_below_one_is_refused():
    """Not clamped: `limit=0` is a request for nothing, which is a bug in the
    caller rather than an ambitious page size."""
    with pytest.raises(ValueError):
        clamp_limit(0)
    with pytest.raises(ValueError):
        clamp_limit(-5)


def test_the_request_reports_the_clamp():
    """AC-FOUND-07.5, through the object a router actually builds."""
    _, size, clamped = PaginationRequest(limit=1000, secret=SECRET).resolve(NEWEST_FIRST)
    assert size == 100
    assert clamped is True


def test_the_page_body_carries_the_flag_only_when_it_happened():
    """`clamped: false` on every response would be noise on the 99% of requests
    that did not ask for too much."""
    clamped = Page(items=[1], next_cursor=None, has_more=False, clamped=True)
    assert clamped.as_dict()["clamped"] is True

    ordinary = Page(items=[1], next_cursor=None, has_more=False)
    assert "clamped" not in ordinary.as_dict()


def test_the_page_body_has_no_total():
    """§7: "No `total` on user-facing lists (it costs a second query and is
    never used)"."""
    body = Page(items=[1, 2], next_cursor="abc", has_more=True).as_dict()
    assert set(body) == {"items", "next_cursor", "has_more"}


# -- the sort spec ----------------------------------------------------------


def test_the_sort_is_always_tie_broken_by_id():
    """§7: "Sort keys must be a total order - always tie-broken by `_id`."

    Appended by the spec object rather than required of the caller: an endpoint
    author who forgets it gets a list that repeats or skips a tie group under
    concurrent writes, and that failure appears in production under load, not in
    review.
    """
    spec = SortSpec((SortKey("created_at", -1),))
    assert spec.mongo_sort() == [("created_at", -1), ("_id", -1)]
    assert NEWEST_FIRST.mongo_sort() == [("_id", -1)]


def test_listing_id_yourself_is_refused():
    with pytest.raises(ValueError, match="tie-break"):
        SortSpec((SortKey("_id", 1),))


def test_sorting_a_field_twice_is_refused():
    with pytest.raises(ValueError, match="twice"):
        SortSpec((SortKey("score", -1), SortKey("score", 1)))


def test_a_direction_other_than_one_or_minus_one_is_refused():
    with pytest.raises(ValueError, match="1 or -1"):
        SortKey("score", 0)  # type: ignore[arg-type]


# -- nullable keys ----------------------------------------------------------


def test_a_nullable_key_must_declare_its_null_position():
    """§7: "A sort on a nullable field must have a defined null position"."""
    with pytest.raises(ValueError, match="null position"):
        SortKey("closes_at", 1, nullable=True)


def test_a_nullable_key_may_only_declare_the_position_mongo_gives_it():
    """BSON orders MinKey < Null < numbers < strings, so an ascending sort is
    nulls-first and no `sort()` argument changes it.

    Accepting the declaration would produce a keyset filter that disagrees with
    the index - which does not fail, it silently drops rows.
    """
    with pytest.raises(ValueError, match="descending"):
        SortKey("closes_at", -1, nullable=True, nulls="first")
    with pytest.raises(ValueError, match="ascending"):
        SortKey("closes_at", 1, nullable=True, nulls="last")


def test_the_honest_declarations_are_accepted():
    assert SortKey("closes_at", 1, nullable=True, nulls="first").nulls_first is True
    assert SortKey("closes_at", -1, nullable=True, nulls="last").nulls_first is False


def test_a_null_position_on_a_non_nullable_key_is_refused():
    """It would read as a guarantee the field never makes."""
    with pytest.raises(ValueError, match="meaningless"):
        SortKey("score", 1, nulls="first")
