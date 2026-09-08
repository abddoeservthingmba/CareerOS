"""T-DATA-05.5 - purging a user leaves shared data alone.

`AC-DATA-05.5`: "Purging a user does not remove or modify any `jobs` document."

`17-data-model.md` §5: "Deleting a user's data must not orphan another user's
data. `jobs` are shared and are never deleted by a user action."

**Why this needs its own criterion.** The natural implementation of an account
purge is "delete every row with this `user_id`, everywhere", and `jobs` has no
`user_id` - so a naive `delete_many({"user_id": ...})` matches nothing there and
the bug never appears. It appears later, when somebody notices that `jobs` is
not being cleaned up by the purge and adds a "fix": deleting the jobs the user
had scored, or had applications for, or had hidden.

Every one of those looks like completeness and is a data loss for everybody
else. A job the departing user applied to is a job forty other users are looking
at, and `match_scores` rows across those users point at its id.

**And the second failure this covers: modifying rather than deleting.** A purge
that "anonymised" a job - stripped the description, cleared the company - would
pass a test that only checked the document still existed. So the assertion is on
the *content*, compared before and after.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.ids import new_id
from app.documents import all_documents, collection_name
from app.infra.mongo import init_documents
from app.infra.storage import MemoryStore, chunked
from app.purge import purge_user, purgeable_collections, shared_collections
from app.shared.object_keys import resume_key

LEAVING = new_id()
STAYING = new_id()
JOB = new_id()


@pytest.fixture
async def world(database: Any) -> tuple[Any, MemoryStore, dict[str, Any]]:
    """Two users, one shared job, and objects for both."""
    await init_documents(database, all_documents())

    job = {
        "_id": JOB,
        "dedup_key": "dedup-shared",
        "title": "Senior Backend Engineer",
        "company": {"name": "Acme", "normalized": "acme"},
        "location": {"raw": "Bengaluru, India", "country": "IN", "remote_mode": "hybrid"},
        "description_text": "A long description that must survive.",
        "status": "active",
        "revision": 1,
    }
    await database["jobs"].insert_one(job)
    await database["skill_aliases"].insert_one({"_id": "reactjs", "canonical": "react"})
    await database["feature_flags"].insert_one({"_id": "llm_rationale_enabled", "value": False})

    for user in (LEAVING, STAYING):
        await database["match_scores"].insert_many(
            [{"_id": new_id(), "user_id": user, "job_id": JOB, "score": 82, "band": "strong"}]
        )
        await database["applications"].insert_one(
            {"_id": new_id(), "user_id": user, "job_id": JOB, "status": "applied"}
        )
        await database["resumes"].insert_one({"_id": new_id(), "user_id": user, "label": "Main"})

    store = MemoryStore()
    for user in (LEAVING, STAYING):
        await store.put_stream(
            resume_key(user, new_id(), "pdf"), chunked([b"%PDF-x"]), content_type="application/pdf"
        )

    return database, store, job


# -- the criterion ------------------------------------------------------------


async def test_the_shared_job_survives_the_purge(world):
    """AC-DATA-05.5, first clause: not removed."""
    database, store, _ = world

    await purge_user(database, LEAVING, store)

    assert await database["jobs"].count_documents({"_id": JOB}) == 1


async def test_the_shared_job_is_not_modified(world):
    """`AC-DATA-05.5`'s second clause, and the failure a presence check misses.

    A purge that "anonymised" the job - cleared the description, blanked the
    company - would leave the document there and destroy it for every other
    user. So the whole document is compared, not its existence.
    """
    database, store, original = world
    before = await database["jobs"].find_one({"_id": JOB})

    await purge_user(database, LEAVING, store)

    after = await database["jobs"].find_one({"_id": JOB})
    assert after == before
    assert after["description_text"] == original["description_text"]


async def test_the_other_users_rows_survive(world):
    """§5: "Deleting a user's data must not orphan another user's data."

    The realistic bug is a filter one character wrong - `{"user_id": {"$ne":
    None}}`, or a missing filter on one collection out of twenty - and the
    person it affects has no idea why their board emptied.
    """
    database, store, _ = world

    await purge_user(database, LEAVING, store)

    for collection in ("match_scores", "applications", "resumes"):
        assert await database[collection].count_documents({"user_id": STAYING}) == 1, (
            f"{collection}: the staying user's row was deleted"
        )
        assert await database[collection].count_documents({"user_id": LEAVING}) == 0


async def test_the_other_users_objects_survive(world):
    """The same rule in the object store, where the mistake is a prefix one
    character short - and ULIDs share long prefixes."""
    database, store, _ = world
    from app.infra.storage import prefix_for

    await purge_user(database, LEAVING, store)

    assert await store.list_prefix(prefix_for(STAYING), include_versions=True)
    assert await store.list_prefix(prefix_for(LEAVING), include_versions=True) == []


async def test_the_global_tables_survive(world):
    """`skill_aliases` and `feature_flags` have no user data.

    Sweeping them would change how every user's skills canonicalize and
    silently revert every flag to its environment default - the second being a
    kill switch turning itself back on during an account deletion.
    """
    database, store, _ = world

    await purge_user(database, LEAVING, store)

    assert await database["skill_aliases"].count_documents({}) == 1
    assert await database["feature_flags"].count_documents({}) == 1


# -- the skip list is derived, not maintained ----------------------------------


def test_the_skipped_collections_are_the_ones_with_no_owner():
    """`shared_collections()` is derived from the documents, not listed.

    A collection is purgeable by user exactly when its documents carry a
    `user_id`. That covers both reasons for skipping - genuinely shared data
    (`jobs`, `skill_aliases`, `feature_flags`) and infrastructure with no owner
    (`raw_listings`, `connector_runs`, `failed_tasks`) - without anybody having
    to keep the two categories straight.

    The first draft derived this from `retention.RETAINED_INDEFINITELY`, which
    named only the first three. `test_no_purgeable_collection_lacks_a_user_id`
    caught the other three, and the fix was to stop maintaining a list at all.
    """
    skipped = shared_collections()

    assert "jobs" in skipped, "AC-DATA-05.5: a job is never deleted by a user action"
    assert {"skill_aliases", "feature_flags"} <= skipped
    assert {"raw_listings", "connector_runs", "failed_tasks"} <= skipped
    assert "resumes" not in skipped and "match_scores" not in skipped


def test_no_shared_collection_is_purgeable():
    """The two lists cannot overlap. If they did, whichever the purge consulted
    first would decide - and it consults the purgeable list."""
    assert not set(purgeable_collections()) & shared_collections()


def test_every_other_collection_is_purgeable():
    """The completeness half.

    A collection in neither list is a collection the purge silently skips, and
    the deleted user's rows stay in it. Derived from the registry rather than
    listed, so `DATA-02` adding a collection puts it in the purge without
    anyone editing `purge.py`.
    """
    everything = {collection_name(document) for document in all_documents()}

    assert set(purgeable_collections()) == everything - shared_collections()


def test_the_users_collection_is_purged_by_its_id():
    """The exception, and the one that matters most.

    `users._id` *is* the `user_id`, so `users` has no `user_id` field and the
    derivation in `shared_collections()` would skip it - leaving the user row
    itself behind after a purge that reported success. "Every trace of the user
    except the user" is the outcome nobody would believe, so it is named,
    branched on in one place, and asserted here.
    """
    from app.purge import USERS_COLLECTION

    assert USERS_COLLECTION in purgeable_collections()
    assert USERS_COLLECTION not in shared_collections()


def test_no_purgeable_collection_lacks_a_user_id():
    """A collection with no `user_id` field cannot be purged by user, so
    including it in the purgeable list is a delete that matches nothing - which
    looks like it worked."""
    by_name = {collection_name(document): document for document in all_documents()}

    from app.purge import USERS_COLLECTION

    for collection in purgeable_collections():
        if collection == USERS_COLLECTION:
            continue  # keyed on `_id`; see the test above
        fields = by_name[collection].model_fields
        assert "user_id" in fields, (
            f"{collection} is purgeable but has no user_id field, so "
            "delete_many({'user_id': ...}) matches nothing and reports success"
        )
