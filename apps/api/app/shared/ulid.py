"""ULID identifiers - `FOUND-03`.

`01-foundations.md` §3: "ULID, stored as the 26-character canonical string in
`_id`. Mongo `ObjectId` never leaves the persistence layer and never appears in
an API response. IDs are generated in the application, not by the database, so a
document can be referenced before it is written."

Layout, per the ULID specification: 48 bits of millisecond timestamp followed by
80 bits of randomness, Crockford base32, 26 characters, lexicographically
sortable in time order.

`AC-FOUND-03.6` requires ULIDs from one process to sort chronologically
alongside those from another, monotonic within a millisecond. Monotonicity is
per-process - the random field is incremented rather than redrawn when two ids
are minted in the same millisecond - and across processes the timestamp
prefix does the ordering, which is why the two clauses are one criterion.
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime

from app.core import clock

# Crockford base32: no I, L, O or U, so a transcribed id cannot be misread.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_DECODE = {c: i for i, c in enumerate(_ALPHABET)}

ULID_LENGTH = 26
_TIMESTAMP_CHARS = 10
_RANDOM_BITS = 80
_MAX_RANDOM = (1 << _RANDOM_BITS) - 1

_lock = threading.Lock()
_last_ms = -1
_last_random = 0


def _encode(value: int, length: int) -> str:
    out = [""] * length
    for i in range(length - 1, -1, -1):
        out[i] = _ALPHABET[value & 0x1F]
        value >>= 5
    return "".join(out)


def new_ulid(at: datetime | None = None) -> str:
    """A fresh ULID.

    With no argument the id is minted from `core.clock.now()` and is monotonic:
    two ids minted in the same millisecond sort in creation order, and a clock
    that steps backwards (NTP, or a test that freezes an earlier instant) still
    yields ascending ids rather than colliding.

    Given an explicit `at`, the timestamp is encoded faithfully and no
    monotonic state is consulted, so `timestamp_of(new_ulid(t)) == t`. Seeding a
    fixture with a chosen instant must produce that instant; carrying the
    monotonic high-water mark into it would silently rewrite it.
    """
    if at is not None:
        milliseconds = int(clock.ensure_utc(at).timestamp() * 1000)
        randomness = int.from_bytes(os.urandom(10), "big")
        return _encode(milliseconds, _TIMESTAMP_CHARS) + _encode(randomness, 16)

    global _last_ms, _last_random
    milliseconds = int(clock.now().timestamp() * 1000)

    with _lock:
        if milliseconds > _last_ms:
            _last_ms = milliseconds
            _last_random = int.from_bytes(os.urandom(10), "big")
        elif _last_random >= _MAX_RANDOM:
            # The randomness is exhausted for this millisecond, which takes
            # 2^80 ids. Step the timestamp rather than wrap.
            _last_ms += 1
            _last_random = int.from_bytes(os.urandom(10), "big")
        else:
            # Same millisecond, or the clock went backwards: increment rather
            # than redraw, so ids keep ascending either way.
            _last_random += 1
        timestamp, randomness = _last_ms, _last_random & _MAX_RANDOM

    return _encode(timestamp, _TIMESTAMP_CHARS) + _encode(randomness, 16)


def is_ulid(value: object) -> bool:
    """True for the 26-character canonical form, and nothing else."""
    if not isinstance(value, str) or len(value) != ULID_LENGTH:
        return False
    return all(c in _DECODE for c in value)


def timestamp_of(value: str) -> datetime:
    """The instant a ULID encodes."""
    if not is_ulid(value):
        raise ValueError(f"{value!r} is not a ULID")
    milliseconds = 0
    for char in value[:_TIMESTAMP_CHARS]:
        milliseconds = (milliseconds << 5) | _DECODE[char]
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)
