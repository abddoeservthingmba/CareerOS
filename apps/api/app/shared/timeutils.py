"""Pure timezone helpers - `FOUND-03`, HR-10.

These live in `shared` rather than `core` because `shared` is the innermost
layer and may not import `core` (`01-foundations.md` §4's `layers` contract).
`shared/ulid.py` needs to validate an instant, so the validation has to be here.

The *clock* stays in `core/clock.py`, which `AC-FOUND-03.1` names as the only
place allowed to read the current time. `core.clock` re-exports these, so
callers above `shared` have one import to reach for.

(`01-foundations.md` §3's Outputs line lists `clock` under `shared/`, while its
Constraints, `AC-FOUND-03.1` and §1's tree all put it in `core/`. Splitting the
pure helpers from the clock satisfies both: nothing in `shared` reads the time,
and nothing outside `core/clock.py` calls `datetime.now`.)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class NaiveDatetimeError(ValueError):
    """A datetime without a timezone reached code that stores or compares it.

    Raised rather than assumed-UTC: a naive value is an unanswered question
    about which zone it came from, and guessing is how a reminder fires at 3am.
    """


def ensure_utc(value: datetime) -> datetime:
    """Return `value` as UTC, or raise if it carries no timezone."""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise NaiveDatetimeError(
            f"{value!r} is naive; every stored datetime is timezone-aware UTC (HR-10)"
        )
    return value.astimezone(UTC)


def is_utc(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() == timedelta(0)
