"""Beanie documents for the admin module - persistence only.

`17-data-model.md` §2.12: `feature_flags`.

**The flag name is the `_id`.** So a flag is a primary-key read, there cannot be
two rows claiming different values for one flag, and the collection is
self-documenting - the ids are the flag names.

**A DB row overrides the environment** (`ADMIN-03` §3), and that ordering is the
point of the collection existing at all: `FLAG_INGESTION_ENABLED=false` in an
environment variable requires a deploy to change, and the moment a kill switch
is needed is the moment a deploy is the slowest thing available. `updated_by`
and `updated_at` are stored because a flag flipped in an incident is a fact the
post-mortem needs, and nobody remembers who did it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator
from pymongo import IndexModel

from app.core.documents import BaseDoc
from app.shared.timeutils import ensure_utc


class FeatureFlag(BaseDoc):
    """`feature_flags` - DB overrides for flags (§2.12).

    Not user-owned: a flag is global. A per-user override would be a different
    feature (an entitlement) and would need its own collection - putting it here
    would mean the kill switch had a scope, which defeats it.
    """

    #: The flag name, e.g. `llm_rationale_enabled`. Overridden so the name is
    #: the key; the inherited ULID factory would produce rows nothing could
    #: look up by name.
    id: str = Field(alias="_id")
    value: bool = False
    updated_at: datetime | None = None  # type: ignore[assignment]
    #: The operator's user id. Nullable because a seed row has no author.
    updated_by: str | None = None

    @field_validator("updated_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    @property
    def name(self) -> str:
        """A name for `_id` that says what it holds. `flag.id` at a call site
        reads as a row identifier, which is not what it is."""
        return self.id

    class Settings:
        name = "feature_flags"
        validate_on_save = True
        # The flag name is the `_id`, so the only lookup this collection has is
        # a primary-key read. §3 lists no index for it.
        indexes: list[IndexModel] = []


DOCUMENTS = (FeatureFlag,)
