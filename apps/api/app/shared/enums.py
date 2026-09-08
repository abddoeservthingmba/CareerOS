"""Shared enumerations - `FOUND-03`.

`01-foundations.md` §3: "Enums are Python `StrEnum` and are exported to the
OpenAPI schema; clients generate from them rather than redeclaring."

Only the enums the shared value objects themselves need live here. Everything
collection-specific is owned by `17-data-model.md` §7's registry and defined by
the module that owns the collection, so that one enum has one home.
"""

from __future__ import annotations

from enum import StrEnum


class RemoteMode(StrEnum):
    """`jobs.remote_mode` (`17-data-model.md` §2.6) and `Location.remote_mode`."""

    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"
    UNKNOWN = "unknown"


class MoneyPeriod(StrEnum):
    """The period a `Money` amount is quoted over."""

    HOUR = "hour"
    MONTH = "month"
    YEAR = "year"
