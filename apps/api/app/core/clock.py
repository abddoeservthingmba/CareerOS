"""The only source of the current time - `FOUND-03`, HR-10.

`01-foundations.md` §3: "Every stored datetime is timezone-aware UTC. Code never
calls `datetime.now()` directly - it calls `core.clock.now()`, which tests
freeze. Local time is derived from `user.tz` at exactly two places: reminder
scheduling (`11-notifications.md` §2) and client rendering."

`AC-FOUND-03.1` asserts by repository search that nothing else reads the clock,
which is what makes `freeze()` sufficient for every time-dependent test in the
product.

The pure timezone helpers live in `app.shared.timeutils` and are re-exported
here, because `shared` is the innermost layer and may not import `core`
(§4's `layers` contract) while `shared/ulid.py` still has to validate an
instant. Nothing in `shared` reads the time; only this module does.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from app.shared.timeutils import NaiveDatetimeError, ensure_utc, is_utc

__all__ = ["NaiveDatetimeError", "ensure_utc", "freeze", "is_utc", "now", "shift"]

_frozen_at: datetime | None = None
_offset = timedelta(0)


def now() -> datetime:
    """The current instant, timezone-aware, in UTC. Always."""
    if _frozen_at is not None:
        return _frozen_at
    return datetime.now(UTC) + _offset


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
