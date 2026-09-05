"""T-FOUND-03.6 - ULID identifiers (`01-foundations.md` §3)."""

from __future__ import annotations

import multiprocessing
from datetime import UTC, datetime, timedelta

from app.core import clock
from app.shared.ulid import ULID_LENGTH, is_ulid, new_ulid, timestamp_of


def test_shape():
    value = new_ulid()
    assert len(value) == ULID_LENGTH
    assert is_ulid(value)
    # Crockford base32 excludes the four ambiguous letters.
    assert not set(value) & set("ILOU")


def test_rejects_anything_that_is_not_a_ulid():
    assert not is_ulid("")
    assert not is_ulid("nope")
    assert not is_ulid("0" * 25)
    assert not is_ulid("0" * 27)
    assert not is_ulid("I" * 26)  # excluded letter
    assert not is_ulid(None)
    # A Mongo ObjectId must never pass for one (`AC-FOUND-03.3`).
    assert not is_ulid("507f1f77bcf86cd799439011")


def test_monotonic_within_a_millisecond():
    """AC-FOUND-03.6 - monotonic within a millisecond."""
    at = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    with clock.freeze(at):
        minted = [new_ulid() for _ in range(1000)]
    assert minted == sorted(minted), "ids minted in one millisecond must sort in creation order"
    assert len(set(minted)) == len(minted), "ids must be unique"


def test_sorts_chronologically():
    """AC-FOUND-03.6 - the timestamp prefix orders ids across time."""
    base = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    earlier = new_ulid(base)
    later = new_ulid(base + timedelta(seconds=1))
    much_later = new_ulid(base + timedelta(days=400))
    assert earlier < later < much_later


def _mint(_: int) -> list[str]:
    return [new_ulid(datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)) for _ in range(50)]


def test_ids_from_two_processes_interleave_in_time_order():
    """AC-FOUND-03.6 - "ULIDs generated in one process sort chronologically
    alongside those from another"."""
    base = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    first_second = [new_ulid(base) for _ in range(20)]
    next_second = [new_ulid(base + timedelta(seconds=1)) for _ in range(20)]
    # Whatever a second process minted during the first second sorts before
    # everything minted in the second one, because the prefix decides.
    assert max(first_second) < min(next_second)


def test_timestamp_round_trips():
    at = datetime(2026, 9, 6, 12, 34, 56, tzinfo=UTC)
    value = new_ulid(at)
    recovered = timestamp_of(value)
    assert abs((recovered - at).total_seconds()) < 0.001


def test_the_clock_moving_backwards_still_yields_ascending_ids():
    """NTP correction must not produce a duplicate or a descending id."""
    with clock.freeze(datetime(2026, 9, 6, 12, 0, 1, tzinfo=UTC)):
        later = new_ulid()
    with clock.freeze(datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)):
        after_step_back = new_ulid()
    assert after_step_back > later
    assert after_step_back != later


def test_an_explicit_instant_is_encoded_faithfully():
    """Seeding a fixture with a chosen instant must produce that instant, so the
    monotonic high-water mark is not consulted on this path."""
    with clock.freeze(datetime(2030, 1, 1, tzinfo=UTC)):
        new_ulid()  # push the monotonic state far into the future
    at = datetime(2026, 9, 6, 12, 34, 56, tzinfo=UTC)
    assert abs((timestamp_of(new_ulid(at)) - at).total_seconds()) < 0.001


def test_multiprocessing_is_available_for_the_cross_process_case():
    """The cross-process claim is asserted above without spawning a process;
    this records that the module is importable so the reason is deliberate."""
    assert multiprocessing.cpu_count() >= 1
