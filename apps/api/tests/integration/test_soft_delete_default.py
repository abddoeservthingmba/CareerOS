"""T-DATA-01.5 - soft delete is filtered by default.

`AC-DATA-01.5`: "Every repository read filters `deleted_at: None` by default;
reading deleted documents requires an explicit `include_deleted=True` argument."

Runs against a real MongoDB. An in-memory stand-in would assert that my filter
dict has the right keys, which is not the same claim as "the query returns the
right rows".
"""

from __future__ import annotations

import pytest
from beanie import init_beanie

from app.core.documents import UserOwnedDoc
from app.core.repository import BaseRepository, MissingUserScope

USER = "01JUSERAAAAAAAAAAAAAAAAAAA"
OTHER = "01JUSERBBBBBBBBBBBBBBBBBBB"


class Note(UserOwnedDoc):
    text: str

    class Settings:
        name = "notes"


class NoteRepository(BaseRepository[Note]):
    document = Note


@pytest.fixture
async def notes(database) -> NoteRepository:
    await init_beanie(database=database, document_models=[Note])
    repository = NoteRepository()
    await repository.insert(Note(user_id=USER, text="live"))
    await repository.insert(Note(user_id=USER, text="also live"))
    doomed = Note(user_id=USER, text="deleted")
    await repository.insert(doomed)
    await repository.soft_delete(doomed.id, user_id=USER)
    await repository.insert(Note(user_id=OTHER, text="someone else's"))
    return repository


async def test_reads_exclude_deleted_by_default(notes: NoteRepository):
    """AC-DATA-01.5."""
    found = await notes.find(user_id=USER)
    assert {n.text for n in found} == {"live", "also live"}


async def test_include_deleted_is_explicit(notes: NoteRepository):
    found = await notes.find(user_id=USER, include_deleted=True)
    assert {n.text for n in found} == {"live", "also live", "deleted"}


async def test_get_excludes_a_deleted_document(notes: NoteRepository):
    deleted = await notes.find(user_id=USER, include_deleted=True)
    target = next(n for n in deleted if n.text == "deleted")

    assert await notes.get(target.id, user_id=USER) is None
    assert await notes.get(target.id, user_id=USER, include_deleted=True) is not None


async def test_count_excludes_deleted(notes: NoteRepository):
    assert await notes.count(user_id=USER) == 2
    assert await notes.count(user_id=USER, include_deleted=True) == 3


async def test_a_read_is_scoped_to_its_owner(notes: NoteRepository):
    """`AUTH-10` - every query on a user-owned collection carries `user_id`."""
    assert {n.text for n in await notes.find(user_id=OTHER)} == {"someone else's"}


async def test_another_users_document_is_not_reachable(notes: NoteRepository):
    """`02-auth-and-account.md` §6 - "not yours" and "does not exist" are the
    same answer, which is what makes the 404 rule possible."""
    theirs = (await notes.find(user_id=OTHER))[0]
    assert await notes.get(theirs.id, user_id=USER) is None


async def test_a_read_without_a_user_id_is_refused(notes: NoteRepository):
    """AC-DATA-01.4 - a forgotten `user_id` raises rather than returning
    everyone's rows."""
    with pytest.raises(MissingUserScope):
        await notes.find()
    with pytest.raises(MissingUserScope):
        await notes.get("01JWHATEVER")


async def test_soft_delete_does_not_remove_the_row(notes: NoteRepository, database):
    """§1 - deletion is `deleted_at`, not a removal; the hard delete is
    `AUTH-07`'s purge, on a 7-day clock."""
    assert await database.notes.count_documents({}) == 4


async def test_soft_deleting_someone_elses_document_does_nothing(notes: NoteRepository):
    theirs = (await notes.find(user_id=OTHER))[0]
    assert await notes.soft_delete(theirs.id, user_id=USER) is False
    assert await notes.get(theirs.id, user_id=OTHER) is not None


async def test_timestamps_round_trip_through_mongo(notes: NoteRepository):
    """AC-FOUND-03.2 - "Every datetime persisted by any module round-trips as
    UTC-aware"."""
    from app.core import clock

    stored = (await notes.find(user_id=USER))[0]
    reloaded = await Note.get(stored.id)
    assert reloaded is not None
    assert clock.is_utc(reloaded.created_at)
    assert clock.is_utc(reloaded.updated_at)


async def test_the_id_stored_in_mongo_is_the_ulid_string(notes: NoteRepository, database):
    """`AC-FOUND-03.3` - no ObjectId anywhere, including at rest."""
    from app.shared.ulid import is_ulid

    raw = await database.notes.find_one({})
    assert isinstance(raw["_id"], str)
    assert is_ulid(raw["_id"])
