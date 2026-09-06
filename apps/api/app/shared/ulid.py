"""ULID identifiers - `FOUND-03`.

`01-foundations.md` §3: "ULID, stored as the 26-character canonical string in
`_id`. Mongo `ObjectId` never leaves the persistence layer and never appears in
an API response. IDs are generated in the application, not by the database, so a
document can be referenced before it is written."

Layout, per the ULID specification: 48 bits of millisecond timestamp followed by
80 bits of randomness, Crockford base32, 26 characters, lexicographically
sortable in time order.

`new_ulid` takes the instant explicitly rather than reading a clock. `shared` is
the innermost layer and may not import `core` (§4's `layers` contract), and the
clock lives in `core.clock`. `core.ids.new_id()` is the one-argument form
everything above `shared` calls.

`AC-FOUND-03.6` requires ULIDs from one process to sort chronologically
alongside those from another, monotonic within a millisecond. Monotonicity is
per-process - within one millisecond the random field is incremented rather than
redrawn - and across processes the timestamp prefix does the ordering, which is
why the two clauses are one criterion. Incrementing only the random field leaves
the encoded timestamp exact, so `timestamp_of(new_ulid(t)) == t` always.
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime

from app.shared.timeutils import ensure_utc

# Crockford base32: no I, L, O or U, so a transcribed id cannot be misread.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_DECODE = {c: i for i, c in enumerate(_ALPHABET)}

ULID_LENGTH = 26
_TIMESTAMP_CHARS = 10
_RANDOM_CHARS = 16
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


def new_ulid(at: datetime) -> str:
    """A ULID encoding `at`, monotonic within its millisecond."""
    global _last_ms, _last_random
    milliseconds = int(ensure_utc(at).timestamp() * 1000)

    with _lock:
        if milliseconds == _last_ms and _last_random < _MAX_RANDOM:
            # Same millisecond: increment rather than redraw, so ids minted back
            # to back sort in creation order. The timestamp is untouched.
            _last_random += 1
        else:
            _last_ms = milliseconds
            _last_random = int.from_bytes(os.urandom(10), "big")
        randomness = _last_random & _MAX_RANDOM

    return _encode(milliseconds, _TIMESTAMP_CHARS) + _encode(randomness, _RANDOM_CHARS)


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
