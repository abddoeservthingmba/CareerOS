"""T-DATA-05.2 - an expired job is deleted, unless somebody applied to it.

`AC-DATA-05.2`: "`jobs.purge_expired` deletes an expired unreferenced job, and
for an expired *referenced* job clears the description fields while keeping the
document and its `title`, `company`, and `source_refs`."

`17-data-model.md` §5: "90 days after `expired_at`, then deleted — **unless**
referenced by an `applications` document, in which case retained indefinitely
with `description_text` and `description_html_sanitized` cleared ... the
reference check is a lookup, not a guess."

**This is the one retention rule that needs a decision, and that is why it is a
cron.** Every other rule in §5 is "delete rows older than X", which a TTL index
enforces without ever falling behind. This one has to ask a question about a
different collection before deciding, and no TTL can. §5 chose the weaker
mechanism deliberately, because the alternative is worse than a cron that might
be paused.

**Why the referenced job is kept at all.** The user's Kanban board shows a card
per application. Deleting the job leaves a card with no title and no company -
a record of an application to something the product can no longer name, which
is exactly the thing a job tracker exists to prevent. So the document survives.

**And why its description is cleared.** The description is the bulk of the
document, nobody reads the text of a job that closed ninety days ago, and Atlas
M0 is 512 MB total (`DATA-06`). Clearing two fields keeps the card intact and
gives back almost all the space.

**"The reference check is a lookup, not a guess."** §5 says so explicitly, and
the guess it rules out is the plausible one: assuming a job with a `match_scores`
row, or with `unseen_runs` below some threshold, is probably referenced. A
lookup against `applications` is the only thing that answers the question being
asked - and ADR-014 exists because the contract that was supposed to permit that
lookup forbade it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core import clock
from app.core.ids import new_id
from app.core.retention import rules_for
from app.documents import all_documents
from app.infra.mongo import init_documents
from app.purge import clear_expired_job_descriptions

NOW = datetime(2026, 9, 8, 4, 0, tzinfo=UTC)
RULE = rules_for("jobs")[0]
CUTOFF = NOW - timedelta(days=RULE.days or 90)

UNREFERENCED = new_id()
REFERENCED = new_id()
STILL_ACTIVE = new_id()
RECENTLY_EXPIRED = new_id()

DESCRIPTION = "A long description nobody will read ninety days after it closed."


def a_job(job_id: str, *, status: str, expired_at: datetime | None) -> dict[str, Any]:
    return {
        "_id": job_id,
        "dedup_key": f"dedup-{job_id}",
        "title": "Senior Backend Engineer",
        "company": {"name": "Acme", "normalized": "acme"},
        "location": {"raw": "Bengaluru, India", "country": "IN", "remote_mode": "hybrid"},
        "source_refs": [{"source": "adzuna", "external_id": job_id}],
        "primary_source": "adzuna",
        "description_text": DESCRIPTION,
        "description_html_sanitized": f"<p>{DESCRIPTION}</p>",
        "status": status,
        "expired_at": expired_at,
        "revision": 1,
    }


@pytest.fixture
async def corpus(database: Any) -> Any:
    """Four jobs covering every branch, and one application."""
    await init_documents(database, all_documents())

    await database["jobs"].insert_many(
        [
            a_job(UNREFERENCED, status="expired", expired_at=CUTOFF - timedelta(days=1)),
            a_job(REFERENCED, status="expired", expired_at=CUTOFF - timedelta(days=1)),
            a_job(STILL_ACTIVE, status="active", expired_at=None),
            a_job(RECENTLY_EXPIRED, status="expired", expired_at=NOW - timedelta(days=10)),
        ]
    )
    await database["applications"].insert_one(
        {"_id": new_id(), "user_id": new_id(), "job_id": REFERENCED, "status": "rejected"}
    )
    return database


async def referenced_ids(database: Any, job_ids: list[str]) -> set[str]:
    """§5's lookup, not a guess.

    Against `applications` specifically. A job with `match_scores` rows is not
    referenced - a score is our opinion about a job, not a record of the user
    having done anything with it, and scores exist for every job in the
    candidate set.
    """
    return set(await database["applications"].distinct("job_id", {"job_id": {"$in": job_ids}}))


async def purge(database: Any) -> tuple[int, int]:
    """One run of `jobs.purge_expired`'s logic. Returns `(deleted, cleared)`."""
    expired = await database["jobs"].distinct(
        "_id", {"status": "expired", "expired_at": {"$lt": CUTOFF}}
    )
    keep = await referenced_ids(database, expired)
    cleared = await clear_expired_job_descriptions(database, sorted(keep))
    result = await database["jobs"].delete_many({"_id": {"$in": sorted(set(expired) - keep)}})
    return result.deleted_count, cleared


# -- the criterion ------------------------------------------------------------


async def test_an_expired_unreferenced_job_is_deleted(corpus: Any):
    """`AC-DATA-05.2`, first clause."""
    with clock.freeze(NOW):
        deleted, _ = await purge(corpus)

    assert deleted == 1
    assert await corpus["jobs"].count_documents({"_id": UNREFERENCED}) == 0


async def test_an_expired_referenced_job_is_kept(corpus: Any):
    """The user's board shows a card per application. Deleting the job leaves a
    card with no title and no company - a record of an application to something
    the product can no longer name."""
    with clock.freeze(NOW):
        await purge(corpus)

    assert await corpus["jobs"].count_documents({"_id": REFERENCED}) == 1


async def test_the_referenced_jobs_descriptions_are_cleared(corpus: Any):
    """The second clause. Two fields, which are the bulk of the document."""
    with clock.freeze(NOW):
        _, cleared = await purge(corpus)

    assert cleared == 1
    job = await corpus["jobs"].find_one({"_id": REFERENCED})
    assert job["description_text"] == ""
    assert job["description_html_sanitized"] == ""


async def test_the_referenced_job_keeps_what_the_board_needs(corpus: Any):
    """`AC-DATA-05.2` names the three fields that survive: `title`, `company`,
    `source_refs`.

    Asserted individually rather than as "the document still exists", because
    a `$unset` of everything but the description would satisfy the clause above
    and leave the card blank - which is the outcome keeping the document was
    supposed to prevent.
    """
    with clock.freeze(NOW):
        await purge(corpus)

    job = await corpus["jobs"].find_one({"_id": REFERENCED})
    assert job["title"] == "Senior Backend Engineer"
    assert job["company"]["name"] == "Acme"
    assert job["source_refs"][0]["external_id"] == REFERENCED


async def test_an_active_job_is_untouched(corpus: Any):
    """A purge that keyed on age alone rather than on `status` and `expired_at`
    would delete listings the product is currently showing."""
    with clock.freeze(NOW):
        await purge(corpus)

    job = await corpus["jobs"].find_one({"_id": STILL_ACTIVE})
    assert job is not None
    assert job["description_text"] == DESCRIPTION


async def test_a_recently_expired_job_is_untouched(corpus: Any):
    """Ninety days, not "expired".

    A listing that closed last week is one a user may still be interviewing
    against, and its description is what they read to prepare.
    """
    with clock.freeze(NOW):
        await purge(corpus)

    job = await corpus["jobs"].find_one({"_id": RECENTLY_EXPIRED})
    assert job is not None
    assert job["description_text"] == DESCRIPTION


# -- the lookup is a lookup ----------------------------------------------------


async def test_the_reference_check_asks_applications_and_not_match_scores(corpus: Any):
    """§5: "the reference check is a lookup, not a guess."

    The guess it rules out is the plausible one - treating a job with
    `match_scores` rows as referenced. A score is our opinion about a job, not
    a record of the user doing anything with it, and scores exist for every job
    in every candidate set. Keying on them would retain almost the whole
    corpus forever.
    """
    await corpus["match_scores"].insert_one(
        {"_id": new_id(), "user_id": new_id(), "job_id": UNREFERENCED, "score": 91}
    )

    with clock.freeze(NOW):
        deleted, _ = await purge(corpus)

    assert deleted == 1
    assert await corpus["jobs"].count_documents({"_id": UNREFERENCED}) == 0


async def test_a_reference_from_any_user_keeps_the_job(corpus: Any):
    """One application anywhere is enough.

    The job is shared; the retention decision is not per user. A check scoped
    to the user being purged would delete a job another user had applied to.
    """
    other = new_id()
    await corpus["applications"].insert_one(
        {"_id": new_id(), "user_id": other, "job_id": UNREFERENCED, "status": "applied"}
    )

    with clock.freeze(NOW):
        deleted, cleared = await purge(corpus)

    assert deleted == 0
    assert cleared == 2


async def test_clearing_is_idempotent(corpus: Any):
    """`AC-FOUND-10.3`: running any task twice produces the same end state.

    A cron that overlaps its previous run - which `01-foundations.md` §10 says
    to expect - must not do anything different the second time.
    """
    with clock.freeze(NOW):
        first = await purge(corpus)
        second = await purge(corpus)

    assert first == (1, 1), "the first run should delete one job and clear one"
    # `(0, 0)`, not `(0, 1)`: `update_many` reports `modified_count` of zero
    # when the fields are already empty. That zero *is* the evidence of
    # idempotence rather than a sign the second run did nothing it should have -
    # which is what the first version of this assertion got backwards.
    assert second == (0, 0)

    job = await corpus["jobs"].find_one({"_id": REFERENCED})
    assert job["description_text"] == ""
    assert job["title"] == "Senior Backend Engineer", (
        "the second run must not have taken anything else"
    )
    assert await corpus["jobs"].count_documents({}) == 3


async def test_clearing_nothing_is_not_an_error(corpus: Any):
    """The commonest case on most nights: nothing is ninety days expired."""
    assert await clear_expired_job_descriptions(corpus, []) == 0


# -- the rule matches the specification ---------------------------------------


def test_the_window_is_the_one_the_spec_states():
    """Ninety days, from `core/retention.py` rather than from a literal here -
    so §5, the rule and this test cannot each carry a different number."""
    assert RULE.days == 90
    assert RULE.enforcer == "jobs.purge_expired"


def test_the_rule_is_a_cron_because_it_needs_a_decision():
    """The mechanism choice, stated.

    Every other rule in §5 is "delete rows older than X", which a TTL enforces
    without ever falling behind. This one asks a question about another
    collection first, and no TTL can - which is the only reason to accept the
    weaker mechanism.
    """
    from app.core.retention import Mechanism

    assert RULE.mechanism is Mechanism.CRON


def test_the_task_is_declared_in_the_inventory():
    """ADR-013 added it. Before that, `AC-DATA-05.2` named a task
    `core/tasks.py` would have refused at import (`AC-FOUND-10.4`)."""
    from app.core.tasks import DECLARED

    assert "jobs.purge_expired" in DECLARED
    assert DECLARED["jobs.purge_expired"].cron == "0 4 * * *"
