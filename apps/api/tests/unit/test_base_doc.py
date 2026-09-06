"""T-DATA-01.1 - the shared document base (`17-data-model.md` §1).

`AC-DATA-01.1`: "Every Beanie document class inherits the shared `BaseDoc`
providing `_id`, `created_at`, `updated_at`, and, where applicable,
`UserOwnedDoc` adding `user_id` and `deleted_at`."
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from beanie import Document
from pydantic import ValidationError

from app.core import clock
from app.core.documents import (
    BaseDoc,
    DocumentFields,
    MissingOwner,
    OwnedFields,
    UserOwnedDoc,
    compound_index_starts_with_user_id,
    is_user_owned,
)
from app.shared.ulid import is_ulid


# The plain-model half of the base, so these run without a database. The
# Beanie half is asserted by tests/integration/test_soft_delete_default.py.
class Thing(DocumentFields):
    name: str = "thing"


class OwnedThing(OwnedFields):
    name: str = "owned"


def test_base_doc_provides_identity_and_time():
    """AC-DATA-01.1, first half."""
    thing = Thing()
    assert is_ulid(thing.id), "_id is a 26-character ULID string, never an ObjectId"
    assert clock.is_utc(thing.created_at)
    assert clock.is_utc(thing.updated_at)


def test_user_owned_adds_owner_and_soft_delete():
    """AC-DATA-01.1, second half."""
    owned = OwnedThing(user_id="01JUSER")
    assert owned.user_id == "01JUSER"
    assert owned.deleted_at is None
    assert owned.is_deleted is False


def test_the_id_is_a_ulid_not_an_object_id():
    """`AC-FOUND-03.3` - no 24-hex ObjectId may reach a response, which starts
    with never minting one."""
    for _ in range(20):
        assert is_ulid(Thing().id)
    assert not is_ulid("507f1f77bcf86cd799439011")


def test_ids_are_unique_and_ordered():
    at = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    with clock.freeze(at):
        ids = [Thing().id for _ in range(200)]
    assert len(set(ids)) == 200
    assert ids == sorted(ids)


def test_a_user_owned_document_needs_an_owner():
    """A row with no owner is a row the deletion sweep can never find."""
    with pytest.raises(ValidationError) as caught:
        OwnedThing(user_id="")
    assert "user_id" in str(caught.value)

    with pytest.raises(ValidationError):
        OwnedThing(user_id="   ")

    with pytest.raises(ValidationError):
        OwnedThing()  # type: ignore[call-arg]


def test_missing_owner_is_the_reason_given():
    with pytest.raises(MissingOwner):
        OwnedThing._owner_required("")


def test_mark_deleted_is_a_soft_delete():
    """§1 - "Soft delete is `deleted_at: datetime | None`"."""
    at = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)
    owned = OwnedThing(user_id="01JUSER")
    with clock.freeze(at):
        owned.mark_deleted()
    assert owned.deleted_at == at
    assert owned.is_deleted is True


def test_is_user_owned_distinguishes_the_two_bases():
    """Declaring a Beanie document needs no database; only instantiating one
    does, which is why the rest of this file uses the plain models."""

    class Plain(BaseDoc):
        class Settings:
            name = "plain"

    class Owned(UserOwnedDoc):
        class Settings:
            name = "owned"

    assert is_user_owned(Owned)
    assert not is_user_owned(Plain)


def test_every_document_in_the_app_inherits_the_base():
    """AC-DATA-01.1 - "Every Beanie document class".

    Vacuous until the first module declares one; binding from that day, because
    it walks the subclasses rather than a list someone maintains.
    """
    for subclass in Document.__subclasses__():
        module = subclass.__module__
        if not module.startswith("app.modules"):
            continue
        assert issubclass(subclass, BaseDoc), f"{module}.{subclass.__name__} must inherit BaseDoc"


def test_compound_index_ordering_rule():
    """§1 - "Every user-owned document has `user_id` as its **first** field in
    every compound index"."""
    assert compound_index_starts_with_user_id([("user_id", 1), ("created_at", -1)])
    assert not compound_index_starts_with_user_id([("created_at", -1), ("user_id", 1)])
    # A single-field index has no ordering to get wrong.
    assert compound_index_starts_with_user_id("email_normalized")
    assert compound_index_starts_with_user_id([("dedup_key", 1)])
