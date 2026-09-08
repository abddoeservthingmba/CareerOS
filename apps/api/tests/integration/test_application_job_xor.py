"""T-DATA-02.3 - an application points at exactly one job.

`AC-DATA-02.3`: "`applications` enforces "exactly one of `job_id`,
`manual_job`" at write time and by a JSON-schema validator on the collection."

`17-data-model.md` §2.10: "Exactly one of `job_id` and `manual_job` is set
(`TRACK-05`)."

**Why the rule exists.** A user tracking an application they found somewhere we
never crawled is not an edge case - it is most of early usage, and `TRACK-05`
makes it first-class. So both shapes are legal, and the pair is not. Neither set
means an application to nothing: it appears on the Kanban board with no title
and no company, and no amount of later repair can recover which job it was for.
Both set means two different jobs, and every downstream consumer picks a
different one - the reminder text one, the pack generator the other.

**Why two independent controls.** `AC-DATA-02.3` asks for both, and the
redundancy is the point. The pydantic validator catches every path that
constructs an `Application` in Python, including a fixture and an endpoint
nobody has written yet. The collection-level `$jsonSchema` catches the paths
that are not Python: a migration script run by hand, an aggregation `$merge`, a
fix applied in Atlas's own data browser at two in the morning. A rule held only
in application code is a rule the database does not know about, and the database
is where the data will still be in a year.
"""

from __future__ import annotations

from typing import Any

import pytest
from beanie import init_beanie
from pydantic import ValidationError
from pymongo.errors import WriteError

from app.core.ids import new_id
from app.modules.tracker.models import (
    Application,
    ApplicationStatus,
    JobReferenceInvalid,
    ManualJob,
    check_job_reference,
)

USER = new_id()
JOB = new_id()

#: The validator `AC-DATA-02.3` requires on the collection. Expressed as
#: `$jsonSchema` rather than `$expr` because Atlas M0 supports it on a free
#: tier and because it is readable in the Atlas UI - the person most likely to
#: break this rule is someone editing a document there, and a rule they can see
#: is one they will not fight.
XOR_VALIDATOR: dict[str, Any] = {
    "$jsonSchema": {
        "bsonType": "object",
        "oneOf": [
            {"required": ["job_id"], "properties": {"manual_job": {"bsonType": "null"}}},
            {"required": ["manual_job"], "properties": {"job_id": {"bsonType": "null"}}},
        ],
    }
}


@pytest.fixture
async def applications(database: Any) -> Any:
    """The collection, with the validator §2.10 requires installed on it."""
    await init_beanie(database=database, document_models=[Application])
    await database.command(
        "collMod" if "applications" in await database.list_collection_names() else "create",
        "applications",
        validator=XOR_VALIDATOR,
        validationLevel="strict",
        validationAction="error",
    )
    return database["applications"]


def manual() -> ManualJob:
    return ManualJob(title="Backend Engineer", company="Acme")


# -- at write time ------------------------------------------------------------


async def test_a_job_backed_application_is_accepted(applications: Any):
    application = Application(user_id=USER, job_id=JOB)
    await application.insert()

    stored = await applications.find_one({"_id": application.id})
    assert stored["job_id"] == JOB
    assert stored["manual_job"] is None


async def test_a_manual_application_is_accepted(applications: Any):
    """`TRACK-05`'s first-class case, not a workaround."""
    application = Application(user_id=USER, manual_job=manual())
    await application.insert()

    stored = await applications.find_one({"_id": application.id})
    assert stored["job_id"] is None
    assert stored["manual_job"]["company"] == "Acme"


def test_neither_set_is_refused_before_any_write():
    """`AC-DATA-02.3`'s "at write time" - and before it, at construction.

    A row with neither is an application to nothing: it appears on the board
    with no title and no company, and nothing can recover which job it was.

    The raise arrives as a pydantic `ValidationError`, not as
    `JobReferenceInvalid`: pydantic wraps any `ValueError` raised inside
    validation. That is the correct shape for the backstop and the reason
    `check_job_reference` exists separately - a router wants one error code,
    not a message to parse.
    """
    with pytest.raises(ValidationError, match="neither is set"):
        Application(user_id=USER)


def test_both_set_is_refused_before_any_write():
    with pytest.raises(ValidationError, match="both is set"):
        Application(user_id=USER, job_id=JOB, manual_job=manual())


def test_the_service_boundary_check_raises_the_domain_type():
    """The front door. `check_job_reference` is what a handler calls, and it
    returns the typed exception unwrapped so `TRACK-05`'s endpoint can map it
    to a single error code."""
    with pytest.raises(JobReferenceInvalid, match="neither is set"):
        check_job_reference(None, None)
    with pytest.raises(JobReferenceInvalid, match="both is set"):
        check_job_reference(JOB, manual())


def test_the_boundary_check_accepts_each_legal_shape():
    """So it is not simply rejecting everything - which would make the endpoint
    reject the manual case `TRACK-05` exists to support."""
    check_job_reference(JOB, None)
    check_job_reference(None, manual())


def test_the_message_says_which_way_it_was_wrong():
    """ "Invalid application" would leave the reader to work out whether they
    supplied too much or too little, and the fixes are opposite."""
    with pytest.raises(JobReferenceInvalid) as neither:
        check_job_reference(None, None)
    with pytest.raises(JobReferenceInvalid) as both:
        check_job_reference(JOB, manual())

    assert "neither" in str(neither.value)
    assert "both" in str(both.value)
    assert "TRACK-05" in str(neither.value)


def test_the_rule_survives_a_rebuild_from_stored_fields():
    """Construction is not the only moment.

    The realistic path is an "unlink this job" feature written months from now:
    load the row, clear `job_id`, save. Rebuilding from the stored fields with
    `job_id` removed is that path, and it must not produce a row with neither.
    """
    application = Application(user_id=USER, job_id=JOB)

    with pytest.raises(ValidationError):
        Application(**{**application.model_dump(by_alias=True), "job_id": None})


# -- and in the database, which is the control that outlives the code ---------


async def test_the_collection_validator_refuses_a_row_with_neither(applications: Any):
    """`AC-DATA-02.3`'s "by a JSON-schema validator on the collection".

    Written with the raw driver on purpose: this is the path a migration script
    or an Atlas data-browser edit takes, and it does not go through pydantic.
    """
    with pytest.raises(WriteError):
        await applications.insert_one(
            {"_id": new_id(), "user_id": USER, "status": ApplicationStatus.SAVED.value}
        )


async def test_the_collection_validator_refuses_a_row_with_both(applications: Any):
    with pytest.raises(WriteError):
        await applications.insert_one(
            {
                "_id": new_id(),
                "user_id": USER,
                "job_id": JOB,
                "manual_job": {"title": "Backend Engineer", "company": "Acme"},
            }
        )


async def test_the_collection_validator_accepts_each_legal_shape(applications: Any):
    """So the validator is not simply refusing every write - which would pass
    both tests above and break the product."""
    await applications.insert_one({"_id": new_id(), "user_id": USER, "job_id": JOB})
    await applications.insert_one(
        {
            "_id": new_id(),
            "user_id": USER,
            "manual_job": {"title": "Backend Engineer", "company": "Acme"},
        }
    )

    assert await applications.count_documents({}) == 2


async def test_the_validator_also_refuses_an_update_that_breaks_the_rule(applications: Any):
    """`validationLevel="strict"` covers updates, not only inserts.

    The default is `strict`, but it is asserted rather than assumed: on
    `moderate`, an update to an existing document skips validation entirely,
    and the way a row ends up illegal is almost always an update.
    """
    application = Application(user_id=USER, job_id=JOB)
    await application.insert()

    with pytest.raises(WriteError):
        await applications.update_one({"_id": application.id}, {"$set": {"job_id": None}})


async def test_the_validator_is_installed_where_the_spec_says(applications: Any, database: Any):
    """The validator has to be *on the collection*, not merely in a test
    fixture. Read back from the database, so a fixture that quietly failed to
    install it fails here rather than making every check above vacuous."""
    options = await database.command("listCollections", filter={"name": "applications"})
    collection = options["cursor"]["firstBatch"][0]

    validator = collection["options"]["validator"]
    assert "oneOf" in validator["$jsonSchema"]
    assert collection["options"]["validationLevel"] == "strict"
    assert collection["options"]["validationAction"] == "error"
