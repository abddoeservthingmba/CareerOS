"""T-DATA-03.1 / T-DATA-03.3 - the declared indexes and the live ones agree.

`AC-DATA-03.1`: "Every index above is declared in code and present at
`/readyz`."
`AC-DATA-03.3`: "No index exists in the live database that is not declared in
code (drift in the other direction is also a failure)."

Three separate things are checked here and it is worth being clear about which
is which, because two of them can pass while the third is badly wrong:

1. **§3's table is declared in code.** The table is parsed out of
   `17-data-model.md` and compared against `Settings.indexes`, so an index the
   specification promises and nobody wrote fails - and so does one that was
   written and then removed from the table.
2. **The declarations are actually created, and nothing else is.** Beanie is
   initialised against a real database and the live index set is compared both
   ways. This is the only check that catches a declaration Mongo rejects: a
   malformed `partialFilterExpression`, two indexes on one key pattern, a text
   index where one already exists.
3. **`/readyz` reports on it.** A correct comparison nothing consults is not a
   readiness check.

**Why the extra-index direction matters as much.** A missing index is slow; an
undeclared one is invisible. Every index costs write throughput and memory, and
Atlas M0 has 512 MB total. The realistic way one appears is somebody adding it
by hand during an incident - exactly when nobody is going to write it down -
and afterwards it does not appear in any diff, so the only thing that will ever
mention it again is this test.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pymongo import ASCENDING, IndexModel

from app.core.documents import (
    SYSTEM_SCAN_INDEXES,
    compound_index_starts_with_user_id,
    is_user_owned,
)
from app.documents import all_documents, collection_name
from app.infra import indexes as index_check
from app.infra.mongo import init_documents

SPEC = Path("docs") / "spec" / "17-data-model.md"

#: §3's table abbreviates two paths. Both are stated here rather than silently
#: accepted, because an index on a field that does not exist is one the planner
#: never chooses and it looks identical to a correct one in `listIndexes`.
TABLE_ALIASES = {
    # §2.6 puts it at `location.remote_mode`; §3's row says `remote_mode`.
    "remote_mode": "location.remote_mode",
}


@pytest.fixture
async def initialised(database: Any) -> Any:
    """Beanie bound to the real documents, with indexes created.

    `init_beanie` creates every declared index, which is what makes this the
    check that catches a declaration Mongo *rejects* - the failure arrives here
    rather than at the first deploy.
    """
    await init_documents(database, all_documents())
    return database


# -- §3's table is declared in code -------------------------------------------


def table_rows(repo: Path) -> list[tuple[str, tuple[str, ...], str]]:
    """§3's table as `(collection, key fields, kind)`.

    Parsed rather than transcribed. A copied table is a second source of truth
    for the index set, and the two would drift in whichever direction nobody
    was looking.
    """
    text = (repo / SPEC).read_text(encoding="utf-8")
    section = text.split("## 3. Indexes", 1)[1].split("\n## 4.", 1)[0]

    out: list[tuple[str, tuple[str, ...], str]] = []
    for line in section.split("\n"):
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 6 or not cells[1].startswith("`"):
            continue
        collection = cells[1].strip("`")
        if not re.fullmatch(r"[a-z_]+", collection):
            continue
        # `strip("`")` removes the outer pair; a row like ``_id` (the alias
        # itself)`` has one *inside* the cell, so the field name has to be
        # stripped again per part. Without this, `skill_aliases` reported a
        # missing index called `` _id` `` - which looks like a real finding.
        fields = tuple(
            TABLE_ALIASES.get(name, name)
            for name in (
                part.strip().split(" ")[0].strip("`") for part in cells[2].strip("`").split(",")
            )
        )
        # A text index has no meaningful field order - Mongo keeps the fields
        # in a `weights` document and discards the declared order - so both
        # sides are sorted. `IndexSpec` canonicalises the same way; without it
        # here, `jobs`' search index reads as simultaneously missing from the
        # code and absent from the table.
        if "text" in cells[3]:
            fields = tuple(sorted(fields))
        out.append((collection, fields, cells[3]))
    return out


def test_the_table_parser_finds_every_row(repo: Path):
    """The parser is load-bearing for the checks below, so its output is
    checked first. A parser that found three rows would make them all pass."""
    rows = table_rows(repo)

    assert len(rows) >= 40, f"§3's table parsed to {len(rows)} rows"
    assert ("users", ("email_normalized",), "unique") in rows
    assert ("reminders", ("dedup_key",), "unique") in rows


def test_every_index_in_the_table_is_declared_in_code(repo: Path):
    """`AC-DATA-03.1`, first clause.

    Compared by key *fields* rather than by direction, because §3 writes
    direction as prose ("`user_id, created_at desc`") and the authoritative
    direction is the one in the code. What the table is authoritative about is
    which fields, in which order.
    """
    declared: dict[str, set[tuple[str, ...]]] = {}
    for document in all_documents():
        collection = collection_name(document)
        declared[collection] = {
            tuple(field for field, _ in spec.keys) for spec in index_check.declared_for(document)
        }

    missing: list[str] = []
    for collection, fields, kind in table_rows(repo):
        if fields == ("_id",):
            continue  # Mongo creates it; §3 lists it for completeness.
        if fields not in declared.get(collection, set()):
            missing.append(f"{collection} ({', '.join(fields)}) [{kind}]")

    assert missing == [], "§3's table names index(es) that no document declares:\n  " + "\n  ".join(
        missing
    )


def test_no_index_is_declared_that_the_table_does_not_name(repo: Path):
    """The other direction, against the specification rather than the database.

    An index in code and not in §3 is an index nobody budgeted for
    (`AC-DATA-03.4`'s 120 MB) and nobody can say what query it serves.
    """
    in_table: dict[str, set[tuple[str, ...]]] = {}
    for collection, fields, _ in table_rows(repo):
        in_table.setdefault(collection, set()).add(fields)

    extra: list[str] = []
    for document in all_documents():
        collection = collection_name(document)
        for spec in index_check.declared_for(document):
            fields = tuple(field for field, _ in spec.keys)
            if fields not in in_table.get(collection, set()):
                extra.append(f"{collection} {spec}")

    assert extra == [], (
        "index(es) declared in code that §3's table does not name:\n  "
        + "\n  ".join(extra)
        + "\nAdd the row to the specification in the same commit, or remove the "
        "index (`CLAUDE.md`: never invent a requirement)."
    )


def test_the_two_indexes_the_spec_lists_twice_are_declared_once(repo: Path):
    """§3 lists `ai_usage (at)` twice - "plain | daily aggregation" and "TTL
    400 d | 13-month retention".

    Mongo cannot hold two indexes on one key pattern, and it does not need to:
    a TTL index *is* an ordinary single-field index that additionally expires.
    Declaring both would be an `IndexOptionsConflict` at boot. Asserted here so
    the single declaration reads as a decision rather than an omission.
    """
    rows = [row for row in table_rows(repo) if row[0] == "ai_usage" and row[1] == ("at",)]
    assert len(rows) == 2, "§3 no longer lists ai_usage (at) twice; simplify this"

    from app.ai.usage import AiUsage

    specs = [
        spec
        for spec in index_check.declared_for(AiUsage)
        if tuple(f for f, _ in spec.keys) == ("at",)
    ]
    assert len(specs) == 1
    assert specs[0].expire_after_seconds is not None, "the one declaration must be the TTL one"


# -- the compound-index rule, and ADR-012's exceptions ------------------------


def test_every_compound_index_on_a_user_owned_collection_leads_with_user_id():
    """§1 / §3, as ADR-012 amended it.

    The rule keeps its absolute form; the exceptions are enumerated. A
    forgotten `user_id` and a deliberate cross-user index therefore still look
    different, which is the entire value of the rule.
    """
    offenders: list[str] = []
    for document in all_documents():
        if not is_user_owned(document):
            continue
        collection = collection_name(document)
        for index in document.Settings.indexes:
            if not compound_index_starts_with_user_id(index, collection):
                offenders.append(f"{collection}: {index_check.from_declaration(index)}")

    assert offenders == [], (
        "compound index(es) on a user-owned collection not leading with user_id:\n  "
        + "\n  ".join(offenders)
        + "\nIf it serves a scheduled job or an entity narrower than a user, add "
        "it to SYSTEM_SCAN_INDEXES with its reason (ADR-012). Otherwise the "
        "leading user_id is missing."
    )


def test_the_exception_list_is_narrow():
    """ADR-012's own guard.

    Two entries, each on a user-owned collection, each actually declared. An
    entry for an index nobody declares is room for whatever is added next, and
    an entry for a collection that is not user-owned is a note about a rule
    that never applied to it.
    """
    assert len(SYSTEM_SCAN_INDEXES) == 3

    owned = {
        collection_name(document): document
        for document in all_documents()
        if is_user_owned(document)
    }
    for (collection, fields), reason in SYSTEM_SCAN_INDEXES.items():
        assert collection in owned, (
            f"{collection} is not a user-owned collection, so §1's rule never "
            "applied to it and the exception is meaningless"
        )
        declared = {
            tuple(field for field, _ in spec.keys)
            for spec in index_check.declared_for(owned[collection])
        }
        assert fields in declared, f"{collection} does not declare ({', '.join(fields)})"
        assert len(reason) > 60, f"{collection}'s exception needs a real reason, not a label"


def test_every_exception_is_recorded_in_the_spec(repo: Path):
    """ADR-012 amended §3's constraint sentence to name both exceptions.

    So a third one cannot be added to the code without the specification
    growing too - which is the difference between an amendment and a drift.
    """
    text = (repo / SPEC).read_text(encoding="utf-8")
    constraint = next(
        line for line in text.split("\n") if line.startswith("**Constraints.** Declared in each")
    )

    assert "ADR-012" in constraint
    for collection, _ in SYSTEM_SCAN_INDEXES:
        assert collection in constraint, f"§3's constraint does not name {collection}"


# -- against a real database ---------------------------------------------------


async def test_every_declared_index_exists_after_init(initialised: Any):
    """`AC-DATA-03.1`'s "present" clause, and the only check that catches a
    declaration Mongo *rejects*.

    A malformed `partialFilterExpression`, a second index on one key pattern, a
    second text index on a collection - each is accepted by pydantic, accepted
    by mypy, and refused by the server. Without this, the refusal arrives at the
    first deploy.
    """
    drifts = await index_check.compare(initialised, all_documents())
    missing = [line for drift in drifts for line in drift.describe() if "absent" in line]

    assert missing == [], "\n  ".join(missing)


async def test_no_undeclared_index_exists(initialised: Any):
    """AC-DATA-03.3."""
    drifts = await index_check.compare(initialised, all_documents())
    undeclared = [line for drift in drifts for line in drift.describe() if "not declared" in line]

    assert undeclared == [], "\n  ".join(undeclared)


async def test_a_hand_created_index_is_reported_as_drift(initialised: Any):
    """`AC-DATA-03.3`, exercised rather than asserted in the abstract.

    This is the realistic failure: someone adds an index by hand during an
    incident. If the check could not see it, the whole extra-index half of the
    criterion would be a comment.
    """
    await initialised["applications"].create_indexes(
        [IndexModel([("notes_md", ASCENDING)], name="hand_made")]
    )

    drifts = await index_check.compare(initialised, all_documents())
    reported = [line for drift in drifts for line in drift.describe()]

    assert any("notes_md" in line and "not declared" in line for line in reported), reported
    assert any("created by hand" in line for line in reported), (
        "the message should say why an undeclared index is a problem"
    )


async def test_a_dropped_index_is_reported_as_missing(initialised: Any):
    """The other direction, exercised. A `dropIndex` during a migration that
    was never re-run is how an index goes missing in practice."""
    await initialised["match_scores"].drop_index("user_score")

    drifts = await index_check.compare(initialised, all_documents())
    reported = [line for drift in drifts for line in drift.describe()]

    assert any("user_score" in line or "score" in line for line in reported), reported
    assert any("absent" in line for line in reported)


async def test_an_index_that_lost_its_ttl_is_reported(initialised: Any):
    """A TTL that is silently gone is a retention rule that stopped running,
    and `DATA-05` is a compliance promise, not a housekeeping preference.

    Comparing key patterns alone would call this index identical, which is why
    `IndexSpec.signature` carries `expireAfterSeconds`.
    """
    await initialised["raw_listings"].drop_index("fetched_at_ttl")
    await initialised["raw_listings"].create_indexes(
        [IndexModel([("fetched_at", ASCENDING)], name="fetched_at_ttl")]
    )

    drifts = await index_check.compare(initialised, all_documents())
    reported = [line for drift in drifts for line in drift.describe()]

    assert any("fetched_at" in line for line in reported), reported


async def test_the_implicit_id_index_is_never_reported(initialised: Any):
    """Mongo creates `_id_` on every collection and nothing declares it.
    Reporting it would make every collection permanently drifted, and a check
    that always fails is a check that gets switched off."""
    drifts = await index_check.compare(initialised, all_documents())

    for drift in drifts:
        for spec in drift.undeclared:
            assert spec.name != index_check.IMPLICIT_INDEX


# -- /readyz consults it -------------------------------------------------------


def test_readyz_names_indexes_among_the_checks_it_runs(settings_factory):
    """`AC-DATA-01.3` / `AC-OPS-01.3`.

    A correct comparison nothing consults is not a readiness check, and
    `not_yet_checked` existing at all is what keeps a 200 from meaning more
    than it verified.
    """
    from app.main import PENDING_CHECKS, READINESS_CHECKS, create_app

    assert "indexes" in READINESS_CHECKS
    assert "indexes" not in PENDING_CHECKS

    with TestClient(create_app(settings_factory())) as client:
        body = client.get("/readyz").json()

    assert "indexes" in body["checks"]
    assert "indexes" not in body["not_yet_checked"]


def test_readyz_is_ready_when_the_indexes_are_right(settings_factory):
    """The positive case. Without it, a `/readyz` that reported 503 for
    everything would pass the drift tests below and never serve traffic."""
    from app.main import create_app

    with TestClient(create_app(settings_factory())) as client:
        response = client.get("/readyz")

    assert response.status_code == 200, response.json()
    assert response.json()["checks"]["indexes"] == "ok"


def test_readyz_returns_503_and_says_which_index(settings_factory, monkeypatch):
    """`AC-DATA-01.3`: "returns 503 **listing** any declared index that is
    absent".

    The list is the requirement, not the status code. A bare 503 sends whoever
    is on call to look at the database, the network and the deploy before they
    find out an index is missing.

    **The drift is injected rather than created**, and that is not a shortcut.
    The app's own lifespan calls `init_beanie`, which *creates* every declared
    index - so an index dropped before startup is recreated by startup and one
    dropped after is only reachable through the test client's portal. Neither
    produces the state this test is about. What is being checked here is the
    wiring: that `/readyz` consults the comparison, 503s on a failure and puts
    the reasons in the body. Whether the comparison is *correct* is asserted
    directly, against a real database, by the tests above.
    """
    from app.main import create_app

    monkeypatch.setattr(
        index_check,
        "verify",
        _fake_verify(False, ["notifications: declared but absent: (user_id:1, created_at:-1)"]),
    )

    with TestClient(create_app(settings_factory())) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not ready"
    assert "created_at" in body["checks"]["indexes"]
    assert "notifications" in body["checks"]["indexes"]


def _fake_verify(ok: bool, reasons: list[str]):
    async def verify(database, documents):  # noqa: ANN001, ANN202 - a stub for one call
        return ok, reasons

    return verify


async def test_verify_reports_an_unreachable_database_rather_than_raising(settings_factory):
    """ "could not read indexes" and "an index is missing" are different facts.

    Reporting a missing index when the database is unreachable sends someone
    looking for one for as long as it takes them to notice Mongo is down -
    which is exactly the wrong first hypothesis. And `verify` must not raise:
    a `/readyz` that 500s tells a load balancer the container is *broken*
    rather than not-yet-ready, and those are handled differently.

    Asserted against `verify` rather than through the app, because with an
    unreachable Mongo the container does not boot at all - `init_beanie` in the
    lifespan fails first, which is the correct behaviour and means `/readyz` is
    never reached.
    """
    from pymongo import AsyncMongoClient

    client: AsyncMongoClient[Any] = AsyncMongoClient(
        "mongodb://127.0.0.1:1/unreachable", serverSelectionTimeoutMS=200
    )
    try:
        ok, reasons = await index_check.verify(client["nope"], all_documents())
    finally:
        await client.close()

    assert ok is False
    assert reasons and reasons[0].startswith("could not read indexes")


def test_readyz_says_not_checked_rather_than_failed_when_mongo_is_down(settings_factory):
    """The wording, at the endpoint.

    `/readyz` reports `"not checked: mongo unreachable"` rather than a failure,
    so the reason someone reads first is the true one. Asserted against the
    source of the handler because the state it describes - a booted container
    with an unreachable database - is one the lifespan now prevents.
    """
    import inspect

    from app import main

    source = inspect.getsource(main.create_app)

    assert 'checks["indexes"] = "not checked: mongo unreachable"' in source
    assert 'if checks["mongo"] == "ok":' in source
