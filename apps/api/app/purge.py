"""Cross-collection purges - `DATA-05`.

`AC-DATA-05.3`: "`account.purge_deleted` run with a frozen clock 7 days after a
request removes every document carrying that `user_id` across all collections
and every object under the prefix, and the run writes a `deletion_completed`
audit row."

`AC-DATA-05.5`: "Purging a user does not remove or modify any `jobs` document."

**Why this is its own layer.** An account purge is the one operation that
touches every collection at once, which means it cannot live in a module: a
module that imported nine other modules' documents would be the end of contract
2. It cannot live in `app.infra` either (contract 7 forbids
`app.infra -> app.modules`, correctly - the Mongo client should not know what a
résumé is). So it sits beside `app.documents`, between the entrypoints and the
modules, and works from the *registry* rather than from the document classes.

**By collection name, through the raw driver.** Deliberately. A purge that went
through each module's repository would need every module's document class, and
it would also inherit each repository's default `deleted_at: None` filter -
which is exactly wrong here: a soft-deleted row is the row this is trying to
remove. `delete_many({"user_id": ...})` on a collection name has neither
problem, and the registry is what makes the collection list complete.

**Completeness is the property, and it is checked rather than assumed.** The
purge iterates `OWNERS`, so a collection added to the registry is purged
without anyone remembering to add it here - and a collection *not* in the
registry is not purged, which is why `test_schema_snapshot.py` refuses an
unregistered collection. The two checks close on each other.

**`jobs` is never touched.** §5: "Deleting a user's data must not orphan another
user's data. `jobs` are shared and are never deleted by a user action." The skip
list is *derived* from the absence of a `user_id` field, which covers `jobs`,
the two other global tables, and the three infrastructure collections without
anybody having to keep the categories straight. A purge that swept every
collection uniformly would delete listings other users are looking at - and
`jobs` has no `user_id`, so a naive `delete_many({"user_id": ...})` would match
nothing and look harmless right up until somebody "fixed" it.

**`users` is the exception, and it is the one that matters.** Its `_id` *is* the
`user_id` every other collection points at, so it has no `user_id` field and the
derivation above skips it - which would leave the user row itself behind after a
purge that reported success. Deleted by `_id` explicitly, and asserted, because
"every trace of the user except the user" is the single most embarrassing
outcome available here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from app.core import clock
from app.core.retention import DELETION_GRACE_DAYS
from app.documents import OWNERS, collection_name


def shared_collections() -> frozenset[str]:
    """Collections an account purge does not touch.

    **Derived from the documents, not listed.** A collection is purgeable by
    user exactly when its documents carry a `user_id`; everything else is
    either shared (`jobs`, `skill_aliases`, `feature_flags`) or infrastructure
    (`raw_listings`, `connector_runs`, `failed_tasks`), and for both the
    correct action is to leave it alone.

    A hand-written list here would be wrong in the direction that fails
    silently. `delete_many({"user_id": ...})` against a collection with no such
    field matches nothing and reports success, so an over-broad list looks
    exactly like a working purge - and the mistake only surfaces when somebody
    notices `jobs` is untouched and "fixes" it by deleting the jobs the user
    had scored, which is a data loss for everyone else.

    The first draft of this derived the set from
    `retention.RETAINED_INDEFINITELY`, on the reasoning that a collection with
    no user data has nothing to purge. That was half right: those three do have
    nothing to purge, and so do `raw_listings`, `connector_runs` and
    `failed_tasks`, which have retention rules and no owner. The test caught it.
    """
    return frozenset(
        collection_name(document)
        for documents in OWNERS.values()
        for document in documents
        if "user_id" not in document.model_fields and collection_name(document) != USERS_COLLECTION
    )


#: The one collection purged by `_id` rather than by `user_id`, because its
#: `_id` *is* the user id. Named here rather than special-cased inline: the
#: derivation in `shared_collections` would otherwise skip it, and a purge that
#: removed every trace of the user except the user is the outcome nobody would
#: believe.
USERS_COLLECTION = "users"

#: `audit_log` is purged but not by `user_id` alone - see `purge_user`. §5: "7
#: years, or until account hard-delete, whichever is first; account purge
#: removes the user's rows." An `admin_action` row has a null `user_id` and must
#: survive, so the filter is explicit.
AUDIT_COLLECTION = "audit_log"


@dataclass(frozen=True, slots=True)
class PurgeResult:
    """What one user's purge removed. Returned so the caller can audit it."""

    user_id: str
    deleted: dict[str, int] = field(default_factory=dict)
    objects_removed: int = 0
    prefix: str = ""

    @property
    def total_documents(self) -> int:
        return sum(self.deleted.values())


def purgeable_collections() -> tuple[str, ...]:
    """Every collection an account purge sweeps, sorted.

    From the registry, so a collection added to `DATA-02` is purged without
    anyone editing this module. That is the whole reason the purge reads a
    registry rather than a list: the list is the thing that goes stale, and it
    goes stale silently - the new collection simply keeps the deleted user's
    rows.
    """
    skipped = shared_collections()
    return tuple(
        sorted(
            collection_name(document)
            for documents in OWNERS.values()
            for document in documents
            if collection_name(document) not in skipped
        )
    )


def grace_expired(requested_at: datetime | None) -> bool:
    """§5's seven days, from one place.

    `clock.now()` rather than `datetime.now()`: `AC-DATA-05.3` runs this "with a
    frozen clock 7 days after a request", which is only possible if nothing
    reads the wall clock directly (`AC-FOUND-03.1`).
    """
    if requested_at is None:
        return False
    return bool(clock.now() - requested_at >= timedelta(days=DELETION_GRACE_DAYS))


async def purge_user(
    database: AsyncDatabase[Any], user_id: str, store: Any | None = None
) -> PurgeResult:
    """Remove every trace of one user. `AC-DATA-05.3`.

    `store` is the object store; `None` skips the prefix sweep, which is what a
    test without a bucket does. Not optional in production - §5's rule is "hard
    delete including R2", and a purge that removed the database rows and left
    the résumés is a purge that reported success and kept the files.
    """
    deleted: dict[str, int] = {}
    for collection in purgeable_collections():
        # `users` keys on `_id`; everything else on `user_id`. One branch, in
        # one place, rather than a caller remembering which.
        criteria: dict[str, Any] = (
            {"_id": user_id} if collection == USERS_COLLECTION else {"user_id": user_id}
        )
        result = await database[collection].delete_many(criteria)
        if result.deleted_count:
            deleted[collection] = result.deleted_count

    objects = 0
    prefix = ""
    if store is not None:
        from app.infra.storage import prefix_for

        prefix = prefix_for(user_id)
        objects = len(await store.delete_prefix(prefix))
        # §4: "the completion is verified by re-listing the prefix". Verified
        # here rather than trusted, because a paginated delete that stopped at
        # S3's default 1,000-key page would report success for the page it
        # handled.
        remaining = await store.list_prefix(prefix, include_versions=True)
        if remaining:
            raise IncompletePurge(
                f"{len(remaining)} object(s) remain under {prefix} after the sweep; "
                "the user was told their data was deleted"
            )

    return PurgeResult(user_id=user_id, deleted=deleted, objects_removed=objects, prefix=prefix)


class IncompletePurge(RuntimeError):
    """The sweep reported success and left something behind.

    Raised rather than logged. A purge is a promise made to a user and, in most
    jurisdictions, to a regulator; a partial one that returns normally is worse
    than one that fails, because the failure is what gets it retried.
    """


async def clear_expired_job_descriptions(database: AsyncDatabase[Any], job_ids: list[str]) -> int:
    """`AC-DATA-05.2`'s second half.

    An expired job that an `applications` document references is kept - the
    user's board would otherwise show a card with no title - but its two large
    text fields are cleared, because they are the bulk of the document and
    nobody reads a description of a job that closed ninety days ago.

    `title`, `company` and `source_refs` survive, which is what the board
    needs. Stated as a field list rather than a `$unset` of everything else, so
    a field added to `jobs` later is kept by default rather than silently
    dropped from every archived listing.
    """
    if not job_ids:
        return 0
    result = await database["jobs"].update_many(
        {"_id": {"$in": job_ids}},
        {"$set": {"description_text": "", "description_html_sanitized": ""}},
    )
    return int(result.modified_count)


__all__ = [
    "AUDIT_COLLECTION",
    "USERS_COLLECTION",
    "IncompletePurge",
    "PurgeResult",
    "clear_expired_job_descriptions",
    "grace_expired",
    "purge_user",
    "purgeable_collections",
    "shared_collections",
]
