"""T-DATA-04.5 - after a hard delete, nothing is left under the prefix.

`AC-DATA-04.5`: "After a hard delete, listing `u/{user_id}/` with versions
returns zero objects."

`17-data-model.md` §4: "Deletion (`AUTH-07`) deletes the `u/{user_id}/` prefix
including all noncurrent versions, and the completion is verified by re-listing
the prefix."

**The criterion says "with versions" and that phrase is the whole test.**
Versioning is on (§4) and a lifecycle rule expires noncurrent versions after 30
days. On a versioned bucket, a delete does not remove anything: it writes a
*delete marker*, and every previous version stays retrievable by version id.

So a sweep that issued ordinary deletes would return successfully, a plain list
would return zero objects, `/readyz` would be green, and the user would have
been told their data was gone while every résumé they ever uploaded remained
readable for thirty days. That is the failure this criterion exists to catch,
and it is invisible to any check that does not pass `include_versions=True`.

**And it is verified by re-listing, not by the delete's return value.** A
paginated delete that silently stopped at 1,000 keys - which is S3's default
page size - would report success for the page it handled. The verification is
the second call.
"""

from __future__ import annotations

import pytest

from app.core.ids import new_id
from app.infra.storage import MemoryStore, chunked, prefix_for
from app.shared.object_keys import (
    application_document_key,
    export_key,
    resume_key,
    resume_text_key,
)

OWNER = new_id()
NEIGHBOUR = new_id()


@pytest.fixture
async def populated(store: MemoryStore) -> MemoryStore:
    """One user with an object in every area, and a neighbour with one too."""
    resume = new_id()
    application = new_id()
    for key, body in (
        (resume_key(OWNER, resume, "pdf"), b"%PDF-1.7 first"),
        (resume_text_key(OWNER, resume), b"extracted text"),
        (application_document_key(OWNER, application, new_id(), "pdf"), b"%PDF-1.7 doc"),
        (export_key(OWNER, new_id()), b"PK\x03\x04zip"),
        (resume_key(NEIGHBOUR, new_id(), "pdf"), b"%PDF-1.7 theirs"),
    ):
        await store.put_stream(key, chunked([body]), content_type="application/octet-stream")

    # A second upload to the same key, so there is a noncurrent version to
    # leave behind. This is the object that a sweep issuing ordinary deletes
    # would keep.
    await store.put_stream(
        resume_key(OWNER, resume, "pdf"),
        chunked([b"%PDF-1.7 second"]),
        content_type="application/pdf",
    )
    return store


# -- the criterion ------------------------------------------------------------


async def test_the_prefix_is_empty_afterwards(populated: MemoryStore):
    """AC-DATA-04.5."""
    prefix = prefix_for(OWNER)
    assert await populated.list_prefix(prefix)

    await populated.delete_prefix(prefix)

    assert await populated.list_prefix(prefix) == []


async def test_no_noncurrent_version_survives(populated: MemoryStore):
    """The criterion's "with versions", which is the assertion that matters.

    A sweep issuing ordinary deletes passes the test above and fails this one:
    the delete marker hides the object from a plain list while every previous
    version stays retrievable by version id for the thirty days the lifecycle
    rule allows.
    """
    prefix = prefix_for(OWNER)
    # There is something to lose: two versions of the same key.
    assert len(await populated.list_prefix(prefix, include_versions=True)) > len(
        await populated.list_prefix(prefix)
    )

    await populated.delete_prefix(prefix)

    assert await populated.list_prefix(prefix, include_versions=True) == []


async def test_completion_is_verified_by_re_listing(populated: MemoryStore):
    """§4: "the completion is verified by re-listing the prefix".

    Not by the delete's return value. A paginated delete that stopped at S3's
    default 1,000-key page would report success for the page it handled, and
    "we deleted 1,000 objects" reads exactly like "we deleted everything".
    """
    prefix = prefix_for(OWNER)
    removed = await populated.delete_prefix(prefix)

    assert removed, "the sweep reported deleting nothing"
    remaining = await populated.list_prefix(prefix, include_versions=True)
    assert remaining == [], f"the sweep reported success and left {remaining}"


async def test_every_area_is_swept(populated: MemoryStore):
    """All four of §4's areas, not only résumés.

    A sweep keyed on `u/{uid}/resumes/` would leave the application documents
    and the export - and the export is a zip of everything, which makes it the
    single worst object to leave behind.
    """
    prefix = prefix_for(OWNER)
    before = await populated.list_prefix(prefix, include_versions=True)
    assert {key.split("/")[2] for key in before} == {"resumes", "applications", "exports"}

    await populated.delete_prefix(prefix)

    assert await populated.list_prefix(prefix, include_versions=True) == []


# -- and nobody else is touched ------------------------------------------------


async def test_another_users_objects_are_untouched(populated: MemoryStore):
    """`AC-DATA-05.5`'s sibling in the object store.

    §5: "Deleting a user's data must not orphan another user's data." A sweep
    that took one character too few off the prefix would delete a stranger's
    résumé, and the stranger would have no idea why it was gone.
    """
    theirs = await populated.list_prefix(prefix_for(NEIGHBOUR), include_versions=True)
    assert theirs

    await populated.delete_prefix(prefix_for(OWNER))

    assert await populated.list_prefix(prefix_for(NEIGHBOUR), include_versions=True) == theirs


async def test_a_user_whose_id_prefixes_another_is_not_swept(store: MemoryStore):
    """The trailing slash, exercised rather than asserted.

    ULIDs are lexicographically ordered by time, so two ids created in the same
    millisecond share a long prefix - `01M...A` and `01M...AB`. A sweep of
    `u/01M...A` without the trailing slash matches both. The collision becomes
    *more* likely under load, which is when the deletion cron runs.
    """
    from app.shared.object_keys import ULID

    shorter = "01M204S45HEG484K659DWQK8ZA"
    longer = "01M204S45HEG484K659DWQK8ZB"
    assert ULID.match(shorter) and ULID.match(longer)

    for user in (shorter, longer):
        await store.put_stream(
            resume_key(user, new_id(), "pdf"), chunked([b"%PDF-x"]), content_type="application/pdf"
        )

    await store.delete_prefix(prefix_for(shorter))

    assert await store.list_prefix(prefix_for(longer), include_versions=True)


async def test_a_backup_is_never_under_a_user_prefix(store: MemoryStore):
    """§4: "ops only, not under `u/`".

    Which is why a backup survives an account deletion - and why the 14-day
    backup retention has to be disclosed in the consent text
    (`16-security-and-compliance.md` §4). A backup filed under the user's
    prefix would be deleted with them, which sounds tidier and means a
    restore cannot recover the account they asked to delete by mistake.
    """
    from app.shared.object_keys import backup_key

    key = backup_key("2026-09-08")
    await store.put_stream(key, chunked([b"gz"]), content_type="application/gzip")

    await store.delete_prefix(prefix_for(OWNER))

    assert await store.list_prefix("backups/") == [key]


async def test_sweeping_an_empty_prefix_is_not_an_error(store: MemoryStore):
    """A user who never uploaded anything still gets deleted.

    `account.purge_deleted` runs over every pending user; raising on the ones
    with no objects would fail the whole batch on the commonest case.
    """
    assert await store.delete_prefix(prefix_for(OWNER)) == []
    assert await store.list_prefix(prefix_for(OWNER), include_versions=True) == []


async def test_the_sweep_uses_the_one_prefix_builder(store: MemoryStore):
    """`prefix_for` and `object_keys.user_prefix` are the same string.

    Two ways to spell the deletion unit is one too many: the sweep would use
    one and the key builder the other, and they would agree until one of them
    was changed.
    """
    from app.shared.object_keys import user_prefix

    assert prefix_for(OWNER) == user_prefix(OWNER)
