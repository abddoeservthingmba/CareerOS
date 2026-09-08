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
from app.shared.embedding import Vector
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


class StoredEmbedding(BaseModel):
    """The persisted shape of an embedding - `17-data-model.md` §2.5, §2.6, §2.9.

    Here rather than in one module because three modules store one
    (`profiles.embedding`, `jobs.embedding`, `answer_bank.embedding`) and a
    module may not import another module. Two copies of this shape would
    eventually disagree about whether `dims` is stored, which is the one field
    that must never be optional.

    `AC-DATA-02.6`: "every embedding carr[ies] `model` and `dims`; a comparison
    between vectors of differing `model` raises `EmbeddingModelMismatch`". The
    model travels *with* the vector for a reason that is easy to miss: a
    re-embedding migration leaves both generations in the collection at once,
    and cosine similarity between them is not a smaller number, it is a
    meaningless one. Without `model` on the row there is no way to tell which
    is which after the fact.
    """

    model: str
    dims: int
    #: The quantization scale. `DATA-06`: one byte per dimension, so the float
    #: range has to travel too or the vector cannot be reconstructed.
    scale: float = 0.0
    #: Base64 of the quantized bytes. Empty until computed - a document exists
    #: before its embedding does.
    vector: str = ""
    #: Hash of the text that produced it, so a recompute can be skipped when
    #: nothing changed (`AC-PROF-05.3`, `AC-JOB-07.2`).
    source_hash: str | None = None
    computed_at: datetime | None = None

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("model")
    @classmethod
    def _model_is_named(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(
                "an embedding must carry the model that produced it; a vector "
                "compared against one from another model is meaningless, not "
                "merely less accurate"
            )
        return value

    @field_validator("dims")
    @classmethod
    def _dims_are_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError(f"dims must be positive, got {value}")
        return value

    @field_validator("computed_at")
    @classmethod
    def _computed_at_is_utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    @property
    def is_computed(self) -> bool:
        return bool(self.vector)

    def to_vector(self) -> Vector:
        """The value object, for comparison. Raises if nothing is stored yet."""
        if not self.is_computed:
            raise ValueError(f"{self.model} embedding has not been computed yet")
        return Vector.from_document(self.model_dump())

    @classmethod
    def from_vector(
        cls, vector: Vector, *, source_hash: str | None = None, computed_at: datetime | None = None
    ) -> StoredEmbedding:
        return cls(
            **vector.to_document(),
            source_hash=source_hash,
            computed_at=computed_at or clock.now(),
        )


class Provenance(BaseModel):
    """`model` and `prompt_version` on anything a model produced - HR-9.

    HR-9: "every AI-generated artifact records the model and the prompt
    version". Shared for the same reason `StoredEmbedding` is: `resumes`,
    `jobs.enrichment`, `application_packs` and `match_scores` all record it, and
    a per-module copy is a per-module chance to leave one of the two fields out.

    The pair is what makes an output explainable a month later. The model alone
    does not: the same model with a rewritten prompt is a different system, and
    the prompt is the half that changes weekly.
    """

    model: str
    prompt_version: str
    at: datetime | None = None

    @field_validator("at")
    @classmethod
    def _at_is_utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None


def is_user_owned(document: type[Document]) -> bool:
    return issubclass(document, UserOwnedDoc)


def declared_indexes(document: type[Document]) -> list[Any]:
    """The indexes a document declares, for `/readyz` to verify (`AC-DATA-01.3`)."""
    settings = getattr(document, "Settings", None)
    return list(getattr(settings, "indexes", []) or [])


#: ADR-012's enumerated exceptions to "every compound index on a user-owned
#: collection starts with `user_id`".
#:
#: A **system-scan index** serves a scheduled job or an entity narrower than a
#: user. Nothing on a request path may use one; `AC-DATA-01.4`'s `@admin_scope`
#: check enforces that from the other side.
#:
#: The rule keeps its absolute form and gains this list rather than becoming a
#: "should", because its whole value is having no judgement in it: an index that
#: does not lead with `user_id` is wrong, so a forgotten `user_id` and a
#: deliberate cross-user index look different. With a "should", the next index
#: that omits `user_id` omits it by accident with a plausible reason attached.
#:
#: Adding an entry is a visible act in a reviewed file next to entries that each
#: say why - the same mechanism `AC-FOUND-04.1` uses for `ignore_imports`.
SYSTEM_SCAN_INDEXES: dict[tuple[str, tuple[str, ...]], str] = {
    ("profiles", ("preferences.locations.country", "preferences.remote_mode")): (
        "candidate-set selection reads from the profile side too: when a newly "
        "ingested job is scored, the question is 'which users want this kind of "
        "role, in this country' - across users by definition. A user's own "
        "profile is found by the unique `user_id` index, not this one."
    ),
    ("reminders", ("status", "due_at")): (
        "the dispatch scan asks 'what is due now, for everybody' - that is the "
        "whole job. Leading with user_id would make it O(users) per minute, "
        "growing with signups, forever."
    ),
    ("application_packs", ("application_id", "status")): (
        "an application belongs to exactly one user, so application_id is "
        "already narrower than user_id. Prefixing it would make the index "
        "larger, no more selective and no safer."
    ),
}


def index_fields(index: Any) -> tuple[str, ...] | None:
    """The key fields of a declared index, or `None` for a shape not modelled.

    Beanie accepts a string, a list of `(field, direction)` pairs, and a
    `pymongo.IndexModel`. All three appear in this codebase - a TTL or partial
    index has to be an `IndexModel` because only that form carries the extra
    arguments - so a checker that understood one of them would silently pass
    over the others.
    """
    keys = getattr(index, "document", None)
    if keys is not None:  # a pymongo IndexModel
        return tuple(keys.get("key", {}))
    if isinstance(index, str):
        return (index,)
    if isinstance(index, list | tuple):
        return tuple(f[0] if isinstance(f, list | tuple) else f for f in index)
    return None


def compound_index_starts_with_user_id(index: Any, collection: str | None = None) -> bool:
    """`17-data-model.md` §1 / §3, as ADR-012 amended it.

    `collection` is optional so existing callers keep working, but without it an
    exception cannot be looked up - so a system-scan index reads as a violation.
    That is the safe direction: a caller that forgets the collection gets a
    stricter answer, not a laxer one.

    **A text index is outside the rule**, and not by exception. "Leads with
    `user_id`" is not a property a text index can have: Mongo replaces the
    declared fields with its own `(_fts, _ftsx)` pair, so the key order the rule
    talks about does not survive into the index at all. Scoping a text search to
    one user is done by the query's own `user_id` predicate, which
    `AC-DATA-01.4` enforces from the repository side. Treating text indexes as
    violations would mean listing every one in the exception table, which is how
    an exception table stops meaning anything.
    """
    fields = index_fields(index)
    if fields is None:
        return True  # a shape this check does not model; §3's table covers it
    if _is_text_index(index):
        return True
    if len(fields) < 2:
        return True
    if fields[0] == "user_id":
        return True
    return collection is not None and (collection, fields) in SYSTEM_SCAN_INDEXES


def _is_text_index(index: Any) -> bool:
    document = getattr(index, "document", None)
    keys = document.get("key", {}) if document is not None else {}
    return any(direction == "text" for direction in keys.values())


__all__ = [
    "BaseDoc",
    "DocumentFields",
    "OwnedFields",
    "MissingOwner",
    "Provenance",
    "StoredEmbedding",
    "NaiveDatetimeError",
    "SYSTEM_SCAN_INDEXES",
    "UserOwnedDoc",
    "compound_index_starts_with_user_id",
    "declared_indexes",
    "index_fields",
    "is_user_owned",
]
