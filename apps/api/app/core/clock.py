"""The only source of the current time - `FOUND-03`, HR-10.

`01-foundations.md` §3: "Every stored datetime is timezone-aware UTC. Code never
calls `datetime.now()` directly - it calls `core.clock.now()`, which tests
freeze. Local time is derived from `user.tz` at exactly two places: reminder
scheduling (`11-notifications.md` §2) and client rendering."

`AC-FOUND-03.1` asserts by repository search that nothing else reads the clock,
which is what makes `freeze()` sufficient for every time-dependent test in the
product.

Note on location: `01-foundations.md` §3's Outputs line writes this module as
`app/shared/clock.py`, but its own Constraints say `core.clock.now()`,
`AC-FOUND-03.1` says "outside `core/clock.py`", and the tree in §1 lists `clock`
under `core/`. Three references to one, so it lives in `core/`.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

_frozen_at: datetime | None = None
_offset = timedelta(0)


class NaiveDatetimeError(ValueError):
    """A datetime without a timezone reached code that stores or compares it.

    Raised rather than assumed-UTC: a naive value is an unanswered question
    about which zone it came from, and guessing is how a reminder fires at 3am.
    """


def now() -> datetime:
    """The current instant, timezone-aware, in UTC. Always."""
    if _frozen_at is not None:
        return _frozen_at
    return datetime.now(UTC) + _offset


def ensure_utc(value: datetime) -> datetime:
    """Return `value` as UTC, or raise if it carries no timezone."""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise NaiveDatetimeError(
            f"{value!r} is naive; every stored datetime is timezone-aware UTC (HR-10)"
        )
    return value.astimezone(UTC)


def is_utc(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() == timedelta(0)


@contextlib.contextmanager
def freeze(at: datetime) -> Iterator[datetime]:
    """Pin `now()` to `at` for the duration of the block."""
    global _frozen_at
    previous = _frozen_at
    _frozen_at = ensure_utc(at)
    try:
        yield _frozen_at
    finally:
        _frozen_at = previous


@contextlib.contextmanager
def shift(by: timedelta) -> Iterator[None]:
    """Move `now()` by `by` - for tests that advance a clock rather than pin it."""
    global _offset, _frozen_at
    previous_offset, previous_frozen = _offset, _frozen_at
    if _frozen_at is not None:
        _frozen_at = _frozen_at + by
    else:
        _offset = _offset + by
    try:
        yield
    finally:
        _offset, _frozen_at = previous_offset, previous_frozen
