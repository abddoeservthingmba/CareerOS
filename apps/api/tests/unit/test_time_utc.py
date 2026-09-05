"""T-FOUND-03.2 - time is UTC everywhere (`01-foundations.md` §3, HR-10).

Shared with `T-NOTIF-01.7`, which asserts every stored `reminders.due_at` is
UTC-aware.

`AC-FOUND-03.2` has two halves. The primitive half - a naive datetime raises,
and an aware one round-trips as UTC - is asserted here. The persistence half,
the Beanie pre-save hook, arrives with `DATA-01` and is asserted by
`tests/unit/test_doc_hooks.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.core import clock


def test_now_is_utc_aware():
    value = clock.now()
    assert value.tzinfo is not None
    assert clock.is_utc(value)


def test_a_naive_datetime_raises():
    """AC-FOUND-03.2 - "a naive datetime raises on write"."""
    with pytest.raises(clock.NaiveDatetimeError):
        clock.ensure_utc(datetime(2026, 9, 6, 12, 0, 0))


def test_an_aware_datetime_round_trips_as_utc():
    kolkata = timezone(timedelta(hours=5, minutes=30))
    local = datetime(2026, 9, 6, 17, 30, 0, tzinfo=kolkata)
    stored = clock.ensure_utc(local)

    assert clock.is_utc(stored)
    assert stored == datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    # The instant is preserved; only the representation changes.
    assert stored.timestamp() == local.timestamp()


def test_freeze_pins_the_clock():
    at = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    with clock.freeze(at):
        assert clock.now() == at
        assert clock.now() == at
    assert clock.now() != at


def test_freeze_accepts_only_aware_instants():
    with pytest.raises(clock.NaiveDatetimeError), clock.freeze(datetime(2026, 9, 6, 12, 0, 0)):
        pass


def test_freeze_restores_the_previous_state_even_on_failure():
    at = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    with pytest.raises(RuntimeError):  # noqa: SIM117 - the nesting is the point
        with clock.freeze(at):
            raise RuntimeError("boom")
    assert abs((clock.now() - datetime.now(UTC)).total_seconds()) < 5


def test_shift_advances_a_frozen_clock():
    """`AC-AUTH-07.3` and `AC-JOB-08.1` need a clock that moves, not only one
    that stops."""
    at = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    with clock.freeze(at):
        with clock.shift(timedelta(days=7)):
            assert clock.now() == at + timedelta(days=7)
        assert clock.now() == at


def test_a_localised_instant_is_the_same_instant():
    """HR-10 - local time exists only at the rendering boundary."""
    at = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    kolkata = timezone(timedelta(hours=5, minutes=30))
    rendered = at.astimezone(kolkata)
    assert rendered.hour == 17 and rendered.minute == 30
    assert clock.ensure_utc(rendered) == at
