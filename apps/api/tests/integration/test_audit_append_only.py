"""T-DATA-02.4 - the audit log cannot be rewritten.

`AC-DATA-02.4`: "`audit_log` rejects updates and deletes: the repository exposes
only `append` and `find`, and the Atlas role used by the app has no
`update`/`remove` privilege on that collection."

**Why an audit log that can be edited is worse than none.** Its whole value is
that it answers "did this happen" when the answer is contested - a pack the user
says they never approved, a consent they say they never gave, a deletion request
they say we ignored. A log the application can rewrite answers only "here is
what the application currently says", which is the same thing the rest of the
database says and worth nothing as evidence.

**Two controls, at two levels, because each covers what the other cannot.**

The repository exposing only `append` and `find` is the control that applies to
code written from now on: there is no method to call, so there is nothing to
review for. It does not constrain a migration script, an aggregation `$merge`,
or a fix applied by hand.

The Atlas role is the control that covers those. It is also the one this suite
*cannot* verify - the credential the tests run under is the same one the app
uses, so a test that successfully deleted a row would prove the privilege was
wrong, and a test that failed to delete could not distinguish a correct role
from a network error. So this file asserts the code-level control fully, asserts
that the privilege requirement is *written down where it is provisioned*, and
says plainly that the privilege itself is verified by a human against Atlas.
That is the same honesty `05-ai-layer.md` §5.2 applies to its own manual
control: "the code cannot verify it, so the gate item is a signed statement,
not a test".
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest
from beanie import init_beanie

from app.core.ids import new_id
from app.core.repository import BaseRepository
from app.modules.apply.models import AuditEntry, AuditKind
from app.modules.apply.repository import AuditRepository

USER = new_id()

#: The methods `AC-DATA-02.4` permits. Anything else on the repository is a way
#: to change history.
ALLOWED_METHODS = frozenset({"append", "find", "document"})

#: The write verbs a mutating method would have to use. Checked by name in the
#: repository's source, so a helper added later that reaches past `append` is
#: caught even though it is not on the allowlist above.
MUTATING_CALLS = ("update_one", "update_many", "delete_one", "delete_many", "replace_one")


@pytest.fixture
async def audit(database: Any) -> AuditRepository:
    await init_beanie(database=database, document_models=[AuditEntry])
    return AuditRepository()


def entry(kind: AuditKind = AuditKind.PACK_APPROVED) -> AuditEntry:
    return AuditEntry(user_id=USER, kind=kind, ref_id=new_id(), content_hash="sha256-abc")


# -- the repository exposes only append and find ------------------------------


def test_the_repository_exposes_no_mutating_method():
    """`AC-DATA-02.4`, first clause.

    By introspection rather than by reading the class, because the risk is a
    method arriving later - and the person adding it will not think of it as a
    way to edit history. They will think of it as `mark_reviewed`.
    """
    public = {
        name
        for name in dir(AuditRepository)
        if not name.startswith("_") and callable(getattr(AuditRepository, name, None))
    }

    extra = sorted(public - ALLOWED_METHODS)
    assert extra == [], (
        f"AuditRepository exposes {extra}. `audit_log` gets `append` and `find` "
        "only: a log the application can change answers 'here is what we "
        "currently say', which is worth nothing as evidence."
    )


def test_the_repository_never_calls_a_write_verb():
    """The narrower check, for a method that is *named* innocently.

    `ALLOWED_METHODS` catches a new public method. This catches an allowed
    method that grew a write - `append` acquiring an upsert, say, which would
    read as a de-duplication improvement.
    """
    source = inspect.getsource(AuditRepository)

    found = [verb for verb in MUTATING_CALLS if verb in source]
    assert found == [], f"AuditRepository calls {found}"


def test_the_repository_does_not_inherit_the_write_helpers():
    """The mechanism behind the check above, stated so it is not undone.

    `BaseRepository` provides `insert`, `get`, `find`, `count`, `soft_delete`
    and `admin_scope_filter`, and every other collection wants all of them.
    Inheriting here would add `soft_delete` to the one collection that must not
    have a deletion path - silently, as a consequence of a base class, with
    nobody having decided it. "Make it consistent with the other repositories"
    is a reasonable-sounding change that defeats `AC-DATA-02.4` entirely.
    """
    assert not issubclass(AuditRepository, BaseRepository)
    assert not hasattr(AuditRepository, "soft_delete")


def test_the_document_does_not_inherit_soft_delete():
    """`AuditEntry` is a `BaseDoc`, not a `UserOwnedDoc`.

    Deliberate: `deleted_at` has no meaning on an append-only log, and
    inheriting it would suggest a row could be retired - which is a deletion
    with a friendlier name.
    """
    assert "deleted_at" not in AuditEntry.model_fields
    assert not hasattr(AuditEntry, "mark_deleted")


def test_the_document_keeps_a_nullable_user_id():
    """An `admin_action` row has an actor but not necessarily a subject.

    A required `user_id` would force an operator's own id into the subject
    field, which makes "everything that happened to this user" return an
    operator's activity.
    """
    assert "user_id" in AuditEntry.model_fields
    assert not AuditEntry.model_fields["user_id"].is_required()


# -- appending works, and reading back works ----------------------------------


async def test_appending_stores_the_row(audit: AuditRepository):
    stored = await audit.append(entry())

    found = await audit.find(user_id=USER, kind=AuditKind.PACK_APPROVED)
    assert [row.id for row in found] == [stored.id]
    assert found[0].content_hash == "sha256-abc"


async def test_appending_twice_keeps_both(audit: AuditRepository):
    """An audit log is not idempotent and must not be.

    Two approvals of two packs are two events, and collapsing them on a natural
    key would lose the second - which is the one someone is asking about.
    """
    await audit.append(entry())
    await audit.append(entry())

    found = await audit.find(user_id=USER, kind=AuditKind.PACK_APPROVED)
    assert len(found) == 2


async def test_every_kind_the_spec_names_can_be_stored(audit: AuditRepository):
    """§2.12's ten members, each written and read back.

    A member that failed to round-trip would be an event the product thinks it
    is recording and is not - and the failure would surface only when someone
    went looking for that specific event.
    """
    for kind in AuditKind:
        await audit.append(entry(kind))

    for kind in AuditKind:
        assert await audit.find(user_id=USER, kind=kind), f"{kind} did not round-trip"


async def test_a_row_carries_its_timestamp_and_request_id(audit: AuditRepository):
    """Without `request_id`, an audit row cannot be joined to the log lines from
    the request that produced it, which is the first thing anyone wants when
    the row itself is disputed."""
    row = AuditEntry(
        user_id=USER,
        kind=AuditKind.CONSENT_ACCEPTED,
        request_id="0f8fad5b-d9cb-469f-a165-70867728950e",
        ip_prefix="203.0.113.0/24",
    )
    await audit.append(row)

    stored = (await audit.find(user_id=USER, kind=AuditKind.CONSENT_ACCEPTED))[0]
    assert stored.created_at.tzinfo is not None
    assert stored.request_id == "0f8fad5b-d9cb-469f-a165-70867728950e"
    # `01-foundations.md` §14: a network, never a host.
    assert stored.ip_prefix == "203.0.113.0/24"


# -- the Atlas privilege, which is a manual control ---------------------------


def test_the_atlas_role_requirement_is_written_down(repo: Path):
    """`AC-DATA-02.4`, second clause - as much of it as code can check.

    The privilege itself cannot be verified from here: the tests run under the
    same credential the app uses, so a successful delete would prove the role
    is *wrong*, and a failed one cannot be told apart from a network error. So
    what is asserted is that the requirement is recorded where the role is
    provisioned, with the collection named - because a requirement nobody wrote
    down is a requirement the next person to create a database user will not
    apply.
    """
    runbook = repo / "docs" / "runbooks" / "atlas-roles.md"

    assert runbook.is_file(), (
        f"{runbook.relative_to(repo).as_posix()} is missing. AC-DATA-02.4's "
        "second control is a manual one; the code cannot verify it, so what has "
        "to exist is the instruction for whoever provisions the role."
    )
    text = runbook.read_text(encoding="utf-8")
    assert "audit_log" in text
    assert "update" in text
    assert "remove" in text


def test_the_runbook_says_the_control_is_manual(repo: Path):
    """So nobody reads a green suite as evidence the privilege is right.

    The same honesty `05-ai-layer.md` §5.2 applies to its own manual control.
    A runbook that read as if it were tested would leave the actual privilege
    unverified and believed.
    """
    text = (repo / "docs" / "runbooks" / "atlas-roles.md").read_text(encoding="utf-8")

    assert "cannot be verified by a test" in text
