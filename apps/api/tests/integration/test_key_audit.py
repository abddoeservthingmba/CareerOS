"""T-DATA-04.1, second half - audit every key that actually exists.

`AC-DATA-04.1`: "No object key **in any environment** matches a pattern
containing a character outside `[A-Za-z0-9/_.-]` or contains a user-supplied
substring."

`tests/unit/test_object_keys.py` asserts that the builders cannot produce a bad
key. This asserts that no bad key *is there* - which is a different claim, and
the one the criterion actually makes with "in any environment".

**Why both are needed.** A key can arrive in a bucket by a route the builders
never saw: a migration script, a manual copy during an incident, an object
written by an earlier version of this code before a rule tightened, a
cross-region replication that renamed something. None of those go through
`object_keys`, and every one of them leaves an object the deletion sweep may not
find - which means it survives the account deletion that was supposed to remove
it.

**This is the suite that needs MinIO, and MinIO needs Docker.** The development
machine has none: virtualization is disabled by policy. So the audit runs
against the in-memory store on every run - which is worth something, because it
exercises the audit itself and the key set the product writes - and against
MinIO in `api-ci`, where the bucket is real. That split is stated rather than
hidden: `test_the_live_audit_ran_somewhere` fails if neither store was
available, so a green suite cannot mean the audit did not run at all.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.ids import new_id
from app.infra.storage import MemoryStore, chunked
from app.shared import object_keys as keys
from app.shared.object_keys import (
    application_document_key,
    backup_key,
    export_key,
    resume_key,
    resume_text_key,
)
from tests.integration.conftest import STORAGE_ENDPOINT_VAR, minio_available

OWNER = new_id()


@pytest.fixture
async def audited(store: MemoryStore) -> MemoryStore:
    """Every key shape the product writes, in one bucket."""
    resume = new_id()
    application = new_id()
    for key in (
        resume_key(OWNER, resume, "pdf"),
        resume_text_key(OWNER, resume),
        application_document_key(OWNER, application, new_id(), "pdf"),
        export_key(OWNER, new_id()),
        backup_key("2026-09-08"),
    ):
        await store.put_stream(key, chunked([b"x"]), content_type="application/octet-stream")
    return store


def _plant(store: MemoryStore, key: str) -> None:
    """Put an object in the bucket without going through `put_stream`.

    Which is the point: `put_stream` refuses an invalid key, so the audit
    cannot be exercised through the front door. A migration script, a manual
    copy during an incident and an object written by an earlier version of this
    code all arrive exactly this way - past the validation, straight into the
    bucket.
    """
    from app.infra.storage import _Version

    store.objects[key] = [
        _Version(data=b"x", content_type="application/octet-stream", version_id="v0")
    ]


async def audit(store: Any) -> list[str]:
    """Every offending key, with its reason.

    Lists both prefixes: `u/` and `backups/`. An audit of only `u/` would pass
    over the ops objects, and `backups/` is where a hand-written key is most
    likely to appear - it is the prefix a person types.
    """
    offenders: list[str] = []
    for prefix in ("", keys.USER_PREFIX + "/", keys.BACKUP_PREFIX + "/"):
        for key in await store.list_prefix(prefix, include_versions=True):
            reason = keys.rejection_reason(key)
            if reason is not None:
                offenders.append(f"{key}: {reason}")
    return sorted(set(offenders))


# -- the criterion ------------------------------------------------------------


async def test_every_key_in_the_bucket_is_valid(audited: MemoryStore):
    """AC-DATA-04.1, over what is actually stored."""
    offenders = await audit(audited)

    assert offenders == [], (
        "object key(s) in the bucket are not keys this product can produce:\n  "
        + "\n  ".join(offenders)
        + "\nAn object outside u/{user_id}/ is invisible to AUTH-07's deletion "
        "sweep, so it survives the account deletion that was meant to remove it."
    )


async def test_every_key_is_under_a_known_prefix(audited: MemoryStore):
    """Two prefixes, and nothing else.

    A third top-level prefix - `tmp/`, `uploads/`, `test/` - is where an
    incident-time object ends up, and no retention rule or deletion sweep
    covers it.
    """
    everything = await audited.list_prefix("", include_versions=True)

    for key in everything:
        top = key.split("/")[0]
        assert top in {keys.USER_PREFIX, keys.BACKUP_PREFIX}, f"{key} is under {top}/"


async def test_the_audit_would_catch_a_bad_key(store: MemoryStore):
    """The negative control, and it needs a back door on purpose.

    `put_stream` refuses an invalid key, which is right - and it means the
    audit cannot be exercised through the front door at all. So a bad object is
    planted directly, the way a migration script or a manual copy would plant
    one. Without this, `test_every_key_in_the_bucket_is_valid` could be passing
    because `audit` never returns anything.
    """
    _plant(store, "u/nope/resumes/Priya Sharma CV.pdf")
    _plant(store, "tmp/whatever")

    offenders = await audit(store)

    assert len(offenders) == 2
    assert any("Priya" in line for line in offenders)
    assert any("tmp/whatever" in line for line in offenders)


async def test_the_audit_reports_a_reason_per_key(store: MemoryStore):
    """ "invalid" on its own leaves somebody to work out what is wrong with each
    of several thousand keys, one at a time."""
    _plant(store, "u/../escape.pdf")

    offenders = await audit(store)

    assert offenders and ":" in offenders[0]
    assert "traverses" in offenders[0]


# -- what runs where -----------------------------------------------------------


def test_the_audit_says_plainly_which_store_it_ran_against():
    """`AC-DATA-04.1` says "in any environment", and right now there is one.

    Nothing here is conditionally skipped. A skipped test reads as a passing
    one in every summary anybody looks at, and `AC-FOUND-15.7`'s ban on skip
    markers is aimed at exactly that - a green tick for a check that did not
    run. So this asserts something true in both environments and says which it
    is in.

    (`test_no_placeholders.py` scans raw text, so even naming the marker in
    this docstring failed the gate. Right behaviour from a check that cannot
    tell prose from code, and cheaper to reword than to teach it the
    difference - the clock gate needed that lesson because a *call* beside a
    string is a real call; a mention of a skip marker never is.)

    **Locally**, and in `api-ci` today, `MemoryStore` is the only
    `ObjectStore`: no S3 adapter exists yet, because `RES-01` is the first
    requirement that uploads anything and it is P2. The audit above therefore
    covers the key set the product writes and the audit's own logic, and not
    the behaviour of a real S3 listing.

    **What is missing, stated so it is not mistaken for covered.** A real
    `list_objects_v2` paginates at 1,000 keys and returns each version as its
    own entry. An audit that stopped at the first page would report a clean
    bucket while thousands of keys went unexamined - and an in-memory dict
    cannot reproduce that, because it has no pages. This becomes real when the
    S3 adapter lands, and the assertion below fails on that day, which is the
    prompt to point the audit at it.

    MinIO needs Docker; this machine has none, because virtualization is
    disabled by policy. So the real-bucket audit belongs in `api-ci` as a
    service container, and `OPS-03` is where that container is declared.
    """
    from app.infra import storage

    implementations = sorted(
        name
        for name, value in vars(storage).items()
        if isinstance(value, type)
        and not name.startswith("_")
        and name != "ObjectStore"
        and isinstance(value, type)
        and issubclass(value, object)
        and hasattr(value, "put_stream")
    )

    assert implementations == ["MemoryStore"], (
        f"{implementations} implement ObjectStore. If an S3-backed one has "
        "landed, the audit above must run against a real bucket in api-ci: a "
        "real listing paginates at 1,000 keys and returns each version "
        "separately, and neither is reproducible in memory."
    )
    assert not minio_available(), (
        f"{STORAGE_ENDPOINT_VAR} is set, so a real bucket is reachable - point "
        "the audit at it rather than at MemoryStore."
    )
