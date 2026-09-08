"""T-DATA-01.2 - the timestamp hooks and the UTC rule.

`AC-DATA-01.2`: "A write with a naive datetime raises; a write with a missing
`user_id` on a `UserOwnedDoc` raises."

Shared with `T-FOUND-03.2` (`AC-FOUND-03.2`), whose persistence half this is:
"Every datetime persisted by any module round-trips as UTC-aware; a naive
datetime raises on write."
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.core import clock
from app.core.documents import DocumentFields, OwnedFields
from app.shared.timeutils import NaiveDatetimeError


class Thing(DocumentFields):
    name: str = "thing"


class OwnedThing(OwnedFields):
    name: str = "owned"


def test_a_naive_created_at_raises():
    """AC-DATA-01.2 / AC-FOUND-03.2."""
    with pytest.raises(ValidationError) as caught:
        Thing(created_at=datetime(2026, 9, 6, 12, 0, 0))
    assert "naive" in str(caught.value).lower()


def test_a_naive_updated_at_raises():
    with pytest.raises(ValidationError):
        Thing(updated_at=datetime(2026, 9, 6, 12, 0, 0))


def test_a_naive_deleted_at_raises():
    with pytest.raises(ValidationError):
        OwnedThing(user_id="01JUSER", deleted_at=datetime(2026, 9, 6, 12, 0, 0))


def test_an_aware_datetime_is_normalised_to_utc():
    """§1 - stored time is UTC, whatever zone it arrived in."""
    kolkata = timezone(timedelta(hours=5, minutes=30))
    thing = Thing(created_at=datetime(2026, 9, 6, 17, 30, 0, tzinfo=kolkata))
    assert thing.created_at == datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    assert clock.is_utc(thing.created_at)


def test_the_insert_hook_stamps_both_timestamps():
    """§1 - "set by a Beanie pre-save hook, never by a caller"."""
    at = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    thing = Thing(created_at=datetime(2000, 1, 1, tzinfo=UTC))
    with clock.freeze(at):
        thing.stamp_created()
    assert thing.created_at == at
    assert thing.updated_at == at


def test_the_update_hook_moves_only_updated_at():
    created = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    later = datetime(2026, 9, 7, 9, 0, 0, tzinfo=UTC)

    thing = Thing()
    with clock.freeze(created):
        thing.stamp_created()
    with clock.freeze(later):
        thing.stamp_updated()

    assert thing.created_at == created, "created_at never moves"
    assert thing.updated_at == later


def test_a_caller_cannot_win_the_timestamp():
    """The hook overwrites whatever the caller supplied, which is the point:
    two documents written in one request must agree about when "now" was."""
    at = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    thing = Thing(created_at=datetime(1999, 1, 1, tzinfo=UTC))
    with clock.freeze(at):
        thing.stamp_created()
    assert thing.created_at == at


def test_the_naive_error_is_the_shared_one():
    """One implementation of the rule, in `shared/timeutils.py`, so `core` and
    the documents cannot disagree about what "naive" means."""
    with pytest.raises(NaiveDatetimeError):
        from app.shared.timeutils import ensure_utc

        ensure_utc(datetime(2026, 9, 6, 12, 0, 0))
