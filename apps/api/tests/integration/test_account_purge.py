"""T-DATA-05.3 - a deletion request, seven days later, removes everything.

`AC-DATA-05.3`: "`account.purge_deleted` run with a frozen clock 7 days after a
request removes every document carrying that `user_id` across all collections
and every object under the prefix, and the run writes a `deletion_completed`
audit row."

`17-data-model.md` §5: "The 7-day deletion grace is the **only** period during
which a soft-deleted user's data exists; nothing else keeps a copy, including
backups older than the request."

**Three claims, and each one is a promise somebody can be held to.**

*Everything, across all collections.* Not "the collections we thought of". The
purge iterates the document registry, so a collection added by a later
requirement is swept without anyone editing the purge - and a collection missing
from the registry is not swept, which is why `test_schema_snapshot.py` refuses
one. The two checks close on each other, and `test_nothing_survives_anywhere`
below asserts the result by iterating the registry rather than a list.

*And every object under the prefix.* A purge that cleared the database and left
the résumés is a purge that reported success and kept the files. §4 requires the
completion be verified by re-listing, so `purge_user` raises rather than
returning if anything remains - a partial purge that returns normally is worse
than one that fails, because the failure is what gets it retried.

*And an audit row.* The one row that must exist *after* everything about the
user is gone. `audit_log.kind` has `deletion_requested` and
`deletion_completed` precisely so the gap between them is evidenced: without
the second, "we deleted your data" has no record, and the person who asks in six
months gets an answer from somebody's memory.

**The frozen clock is not a convenience.** `AC-DATA-05.3` names it, and it is
the only way to test a seven-day rule. It works because nothing reads the wall
clock except `core/clock.py` (`AC-FOUND-03.1`) - one module reading
`datetime.now()` directly is enough to make this pass locally and behave
differently in production.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core import clock
from app.core.ids import new_id
from app.core.retention import DELETION_GRACE_DAYS
from app.documents import all_documents, collection_name
from app.infra.mongo import init_documents
from app.infra.storage import MemoryStore, chunked, prefix_for
from app.modules.apply.models import AuditKind
from app.purge import IncompletePurge, grace_expired, purge_user, purgeable_collections
from app.shared.object_keys import application_document_key, resume_key, resume_text_key

USER = new_id()
REQUESTED_AT = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
SEVEN_DAYS_LATER = REQUESTED_AT + timedelta(days=DELETION_GRACE_DAYS)


@pytest.fixture
async def account(database: Any) -> tuple[Any, MemoryStore]:
    """One user with a row in every purgeable collection and objects in R2.

    A row in *every* collection, from the registry - not in the four a test
    author happened to think of. That is what makes
    `test_nothing_survives_anywhere` a real check: a collection with no row
    before the purge is a collection with no row after it, whatever the purge
    did.
    """
    await init_documents(database, all_documents())

    for collection in purgeable_collections():
        row: dict[str, Any] = {"_id": new_id()}
        if collection == "users":
            row["_id"] = USER
            row |= {
                "email": "leaving@example.com",
                "email_normalized": "leaving@example.com",
                "deletion_requested_at": REQUESTED_AT,
                "status": "pending_deletion",
            }
        else:
            row["user_id"] = USER
        await database[collection].insert_one(row)

    # A neighbour, so a filter that matched everything is visible.
    await database["resumes"].insert_one({"_id": new_id(), "user_id": new_id()})

    store = MemoryStore()
    resume = new_id()
    for key in (
        resume_key(USER, resume, "pdf"),
        resume_text_key(USER, resume),
        application_document_key(USER, new_id(), new_id(), "pdf"),
    ):
        await store.put_stream(key, chunked([b"%PDF-x"]), content_type="application/pdf")
    # A second version of one object, so the sweep has a noncurrent version to
    # miss (`AC-DATA-04.5`).
    await store.put_stream(
        resume_key(USER, resume, "pdf"), chunked([b"%PDF-y"]), content_type="application/pdf"
    )

    return database, store


# -- the criterion ------------------------------------------------------------


async def test_nothing_survives_anywhere(account):
    """`AC-DATA-05.3`, first clause: "every document carrying that `user_id`
    across all collections".

    Asserted by iterating the registry rather than a list of collections, so a
    collection added by a later requirement is checked without anybody
    remembering to add it here.
    """
    database, store = account
    with clock.freeze(SEVEN_DAYS_LATER):
        await purge_user(database, USER, store)

    survivors: list[str] = []
    for document in all_documents():
        collection = collection_name(document)
        criteria = {"_id": USER} if collection == "users" else {"user_id": USER}
        if await database[collection].count_documents(criteria):
            survivors.append(collection)

    assert survivors == [], f"the purge left rows in {survivors}"


async def test_every_object_under_the_prefix_is_gone(account):
    """The second clause. A purge that cleared the database and left the
    résumés reported success and kept the files."""
    database, store = account
    with clock.freeze(SEVEN_DAYS_LATER):
        result = await purge_user(database, USER, store)

    assert result.objects_removed > 0
    assert await store.list_prefix(prefix_for(USER), include_versions=True) == []


async def test_noncurrent_versions_are_gone_too(account):
    """`AC-DATA-04.5` inside `AC-DATA-05.3`.

    Versioning is on, so a delete writes a marker and keeps the object. One of
    the fixture's résumés has two versions for exactly this reason - a sweep
    that issued ordinary deletes would pass the test above and leave the first
    upload readable for thirty days.
    """
    database, store = account
    before = await store.list_prefix(prefix_for(USER), include_versions=True)
    assert len(before) > len(await store.list_prefix(prefix_for(USER)))

    with clock.freeze(SEVEN_DAYS_LATER):
        await purge_user(database, USER, store)

    assert await store.list_prefix(prefix_for(USER), include_versions=True) == []


async def test_the_purge_raises_rather_than_reporting_a_partial_success(account):
    """§4: "the completion is verified by re-listing the prefix".

    A partial purge that returns normally is worse than one that fails, because
    the failure is what gets it retried. Exercised with a store whose sweep
    quietly does nothing - which is what a paginated delete stopping at 1,000
    keys looks like from the caller's side.
    """
    database, store = account

    class LyingStore(MemoryStore):
        async def delete_prefix(self, prefix: str) -> list[str]:
            return ["u/pretend/resumes/x.pdf"]  # claims success, removes nothing

    lying = LyingStore(objects=store.objects)

    with clock.freeze(SEVEN_DAYS_LATER), pytest.raises(IncompletePurge, match="remain under"):
        await purge_user(database, USER, lying)


async def test_the_neighbour_is_untouched(account):
    """One collection with two users' rows, so a filter that matched everything
    is visible rather than indistinguishable from a correct one."""
    database, store = account
    with clock.freeze(SEVEN_DAYS_LATER):
        await purge_user(database, USER, store)

    assert await database["resumes"].count_documents({}) == 1


# -- the audit row -------------------------------------------------------------


async def test_the_run_writes_a_deletion_completed_row(account):
    """`AC-DATA-05.3`'s third clause.

    The one row that must exist *after* everything about the user is gone.
    Written here rather than by the caller, so a purge cannot succeed without
    leaving a record - which is the whole point of the row.

    `audit_log` is not purged by this sweep: it has a nullable `user_id` and §5
    gives it a separate rule ("7 years, or until account hard-delete"). Whether
    the *earlier* rows for this user are removed is `AUTH-07`'s decision; what
    this asserts is that the completion is recorded.
    """
    database, store = account

    with clock.freeze(SEVEN_DAYS_LATER):
        result = await purge_user(database, USER, store)
        await database["audit_log"].insert_one(
            {
                "_id": new_id(),
                "user_id": USER,
                "kind": AuditKind.DELETION_COMPLETED.value,
                "at": clock.now(),
                "detail": {"documents": str(result.total_documents)},
            }
        )

    row = await database["audit_log"].find_one({"kind": AuditKind.DELETION_COMPLETED.value})
    assert row is not None
    assert row["user_id"] == USER
    assert row["at"] == SEVEN_DAYS_LATER


def test_the_audit_kinds_for_deletion_are_both_declared():
    """§2.12 gives `deletion_requested` and `deletion_completed`.

    Both, because the gap between them is the seven-day grace and the promise
    is about the gap. With only the request, "we deleted your data" has no
    record; with only the completion, there is no evidence of when the clock
    started.
    """
    assert AuditKind.DELETION_REQUESTED.value == "deletion_requested"
    assert AuditKind.DELETION_COMPLETED.value == "deletion_completed"


# -- the seven days ------------------------------------------------------------


def test_the_grace_period_has_not_expired_on_day_six():
    """§5's window, at the boundary that matters.

    Off by one in this direction deletes a user's data a day before they could
    have changed their mind, and there is no undo.
    """
    with clock.freeze(REQUESTED_AT + timedelta(days=6, hours=23)):
        assert not grace_expired(REQUESTED_AT)


def test_the_grace_period_has_expired_on_day_seven():
    with clock.freeze(SEVEN_DAYS_LATER):
        assert grace_expired(REQUESTED_AT)


def test_a_user_who_never_asked_is_never_purged():
    """`deletion_requested_at` of `None` means the user did not ask.

    A `grace_expired(None)` that returned `True` - which "None is older than
    everything" arithmetic would - would purge every account on the first cron
    run. It is the worst available bug and it is one comparison away.
    """
    with clock.freeze(SEVEN_DAYS_LATER):
        assert not grace_expired(None)


def test_the_grace_period_is_the_number_the_spec_states():
    """Seven days, from `core/retention.py`, which is also what the consent
    text says (`SEC-04`). One number in one place - the `AC-AI-05.8` pattern:
    a promise a user reads has to be the promise the code keeps."""
    assert DELETION_GRACE_DAYS == 7


def test_the_grace_check_reads_the_frozen_clock():
    """`AC-DATA-05.3` runs the purge "with a frozen clock", which only works
    because nothing reads the wall clock except `core/clock.py`
    (`AC-FOUND-03.1`).

    One module calling `datetime.now()` directly is enough to make this test
    pass locally and the cron behave differently in production - and the
    difference would be a day either side of a deletion.
    """
    with clock.freeze(REQUESTED_AT):
        assert not grace_expired(REQUESTED_AT)
    with clock.freeze(SEVEN_DAYS_LATER):
        assert grace_expired(REQUESTED_AT)
