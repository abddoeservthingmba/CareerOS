"""Global document conventions - `DATA-01`.

`17-data-model.md` §1: "Every document in every collection obeys the same rules
for identity, time, ownership, and deletion, so a query written for one
collection is correct in shape for all of them."

The four rules, and what each prevents:

* **`_id` is a 26-character ULID string.** No `ObjectId` anywhere, so nothing
  can leak one into a response (`AC-FOUND-03.3`), and a document can be
  referenced before it is written.
* **`created_at` / `updated_at` are set by a hook, never by a caller.** A caller
  that sets its own timestamp sets it from its own clock, and then two documents
  written in one request disagree about when "now" was.
* **`user_id` is the first field of every compound index on a user-owned
  collection**, and a write without one raises. `AUTH-10`'s ownership model is
  only as good as the queries beneath it.
* **Soft delete is `deleted_at`**, filtered by default on every read
  (`AC-DATA-01.5`). A read that forgets the filter shows a user data they
  deleted.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Self

from beanie import Document, Insert, Replace, SaveChanges, Update, before_event
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core import clock
from app.core.ids import new_id
from app.shared.timeutils import NaiveDatetimeError, ensure_utc


class MissingOwner(ValueError):
    """A user-owned document was written with no `user_id`.

    `17-data-model.md` §1: "A query on a user-owned collection without a
    `user_id` predicate is a defect." The same holds for a write: a row with no
    owner is a row the deletion sweep (`AUTH-07`) will never find.
    """


class DocumentFields(BaseModel):
    """The fields and rules, as a plain Pydantic model.

    Split from `BaseDoc` because a Beanie `Document` cannot be instantiated
    before `init_beanie` has run, and the rules here - a ULID `_id`, UTC-aware
    timestamps, an owner that must be present - are worth testing without a
    database in the loop. `BaseDoc` is this plus Beanie.
    """

    id: str = Field(default_factory=new_id, alias="_id")
    created_at: datetime = Field(default_factory=clock.now)
    updated_at: datetime = Field(default_factory=clock.now)

    model_config = ConfigDict(populate_by_name=True, validate_assignment=True)

    @field_validator("created_at", "updated_at")
    @classmethod
    def _must_be_utc(cls, value: datetime) -> datetime:
        """`AC-DATA-01.2` - a write with a naive datetime raises (HR-10)."""
        return ensure_utc(value)

    def stamp_created(self) -> None:
        moment = clock.now()
        self.created_at = moment
        self.updated_at = moment

    def stamp_updated(self) -> None:
        self.updated_at = clock.now()


class OwnedFields(DocumentFields):
    """`DocumentFields` plus ownership and soft deletion."""

    user_id: str
    deleted_at: datetime | None = None

    @field_validator("user_id")
    @classmethod
    def _owner_required(cls, value: str) -> str:
        if not value or not value.strip():
            raise MissingOwner(
                "a user-owned document needs a user_id; without one the deletion "
                "sweep (AUTH-07) can never find it"
            )
        return value

    @field_validator("deleted_at")
    @classmethod
    def _deleted_at_is_utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def mark_deleted(self) -> Self:
        self.deleted_at = clock.now()
        return self


class BaseDoc(Document, DocumentFields):
    """`AC-DATA-01.1` - identity and time, on every document in the product."""

    # Declared here, not merely inherited. `Document` contributes its own
    # `id: PydanticObjectId` and wins the MRO against `DocumentFields`, so
    # without this line Mongo stores an ObjectId and `17-data-model.md` §1's
    # "No `ObjectId` anywhere" is false at rest - which is exactly what
    # `tests/integration/test_soft_delete_default.py` caught.
    id: str = Field(default_factory=new_id, alias="_id")  # type: ignore[assignment]

    @before_event(Insert)
    def _stamp_created(self) -> None:
        self.stamp_created()

    @before_event(Replace, Update, SaveChanges)
    def _stamp_updated(self) -> None:
        self.stamp_updated()

    class Settings:
        validate_on_save = True


class UserOwnedDoc(BaseDoc, OwnedFields):
    """`AC-DATA-01.1` - everything a user owns, and can therefore delete."""

    class Settings:
        validate_on_save = True


def is_user_owned(document: type[Document]) -> bool:
    return issubclass(document, UserOwnedDoc)


def declared_indexes(document: type[Document]) -> list[Any]:
    """The indexes a document declares, for `/readyz` to verify (`AC-DATA-01.3`)."""
    settings = getattr(document, "Settings", None)
    return list(getattr(settings, "indexes", []) or [])


def compound_index_starts_with_user_id(index: Any) -> bool:
    """`17-data-model.md` §1 / §3 - "Every compound index on a user-owned
    collection starts with `user_id`"."""
    keys = getattr(index, "document", None)
    if keys is not None:  # a pymongo IndexModel
        fields = list(keys.get("key", {}))
    elif isinstance(index, list | tuple):
        fields = [f[0] if isinstance(f, list | tuple) else f for f in index]
    elif isinstance(index, str):
        fields = [index]
    else:
        return True  # a shape this check does not model; §3's table covers it
    if len(fields) < 2:
        return True
    return bool(fields[0] == "user_id")


__all__ = [
    "BaseDoc",
    "DocumentFields",
    "OwnedFields",
    "MissingOwner",
    "NaiveDatetimeError",
    "UserOwnedDoc",
    "compound_index_starts_with_user_id",
    "declared_indexes",
    "is_user_owned",
]
