"""Identifier minting - `FOUND-03`.

`shared/ulid.py` is pure: it encodes an instant it is given. This is the form
everything above `shared` calls, because reading the clock is `core`'s job and
`shared` may not import `core` (`01-foundations.md` §4).

    document_id = new_id()

`AC-FOUND-03.6`'s monotonicity follows from `shared.ulid`; freezing
`core.clock` freezes the ids too, which is what makes a seeded fixture
reproducible.
"""

from __future__ import annotations

from app.core import clock
from app.shared.ulid import is_ulid, new_ulid, timestamp_of

__all__ = ["is_ulid", "new_id", "timestamp_of"]


def new_id() -> str:
    """A fresh ULID for the current instant."""
    return new_ulid(clock.now())
