"""T-DATA-05.4 - every collection has a stated lifetime.

`AC-DATA-05.4`: "A test enumerates every collection in §2 and fails if a
collection is missing from both this retention table and an explicit 'retained
indefinitely' allowlist."

`17-data-model.md` §5's first constraint is the one this enforces: **"A
retention rule with no mechanism is a defect. Every row above names one."**

**Why "retained indefinitely" has to be an allowlist rather than a default.**
Keeping data forever is what happens when nobody decides. It requires no code,
no cron and no conversation, and it is indistinguishable from a decision until
somebody asks how long you keep résumés and the answer turns out to be
"always". An allowlist inverts that: forever is a line somebody wrote, next to
a reason.

**And why a mechanism has to be named, not just a lifetime.** "90 days" with no
mechanism is a sentence in a document. §5 makes it a defect because that is the
usual state of retention policy - written down, agreed, and not implemented -
and because the gap is invisible: nothing fails when a rule is not enforced.
The data just accumulates.

This file compares three things that must agree: §5's table in the
specification, `core/retention.py`'s transcription of it, and the actual
collection list from `app/documents.py`. Any two agreeing while the third
differs is the failure mode a single-source check would miss.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core import retention
from app.core.retention import (
    BACKUP_RETENTION_DAYS,
    DELETION_GRACE_DAYS,
    RETAINED_INDEFINITELY,
    RULES,
    Mechanism,
)
from app.core.tasks import DECLARED
from app.documents import ABSENT_UNTIL_R2, all_documents, collection_name
from app.infra import indexes as index_check

SPEC = Path("docs") / "spec" / "17-data-model.md"


def table_rows(repo: Path) -> list[tuple[str, str, str]]:
    """§5's table as `(data, lifetime, mechanism)`.

    Parsed, not transcribed. A table in a specification and a tuple in a module
    are two copies of one fact; the only thing that keeps them equal is
    something that compares them.
    """
    text = (repo / SPEC).read_text(encoding="utf-8")
    section = text.split("## 5. Retention", 1)[1].split("**Constraints.**", 1)[0]

    out: list[tuple[str, str, str]] = []
    for line in section.split("\n"):
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 5 or cells[1] in ("Data", "---"):
            continue
        out.append((cells[1], cells[2], cells[3]))
    return out


# -- the criterion ------------------------------------------------------------


def test_every_collection_has_a_rule_or_is_allowlisted():
    """AC-DATA-05.4.

    The R1 collections from the registry, compared against the union of §5's
    table and the allowlist. A collection in neither is data with no stated
    lifetime - which in practice means forever, decided by nobody.
    """
    collections = {collection_name(document) for document in all_documents()}

    uncovered = sorted(collections - retention.covered())

    assert uncovered == [], (
        f"{uncovered} have no retention rule and are not on the "
        "'retained indefinitely' allowlist. §5: 'A retention rule with no "
        "mechanism is a defect.' Add a row with its mechanism, or an allowlist "
        "entry saying why forever is correct."
    )


def test_the_allowlist_says_why_for_every_entry():
    """An allowlist entry with no reason is the default wearing a decision's
    clothes.

    Length-checked as well as presence-checked: "shared data" is not a reason,
    it is a restatement. Each entry has to say what would break if the rows
    were deleted.
    """
    for collection, reason in RETAINED_INDEFINITELY.items():
        assert len(reason) > 80, f"{collection}'s allowlist reason is too short to be one"
        assert collection in {collection_name(d) for d in all_documents()}, (
            f"{collection} is allowlisted but is not a collection"
        )


def test_nothing_is_both_ruled_and_allowlisted_without_a_reason():
    """`jobs` is in both, deliberately, and it is the only one.

    Its expired listings have a 90-day rule and its active ones are kept while
    the source shows them. Any *other* collection in both would mean two
    answers to "how long do you keep this", and the one somebody reads would be
    whichever they found first.
    """
    ruled = {rule.collection for rule in RULES}

    both = sorted(ruled & set(RETAINED_INDEFINITELY))

    assert both == ["jobs"], (
        f"{both} have both a retention rule and an allowlist entry. Only `jobs` "
        "legitimately does - §5 gives it one rule for expired listings and "
        "keeps active ones while their source shows them."
    )


def test_every_rule_names_a_mechanism():
    """§5's first constraint, structurally.

    `Mechanism` has three members and no "documented policy" - which is the
    fourth member somebody would add, and is exactly what §5 calls a defect.
    """
    for rule in RULES:
        assert isinstance(rule.mechanism, Mechanism)
        assert rule.enforcer, f"{rule.collection} names no enforcer"

    assert {member.value for member in Mechanism} == {"ttl_index", "cron", "account_purge"}


# -- the mechanisms exist ------------------------------------------------------


def test_every_ttl_rule_matches_the_declared_index():
    """`AC-DATA-05.1`: "Each TTL index above exists with the stated
    `expireAfterSeconds`."

    Compared against the index declaration, so §5's window and the index cannot
    diverge. They diverge silently: a retention promise of 30 days enforced by a
    90-day TTL looks identical from both sides until somebody checks.
    """
    by_collection = {collection_name(d): d for d in all_documents()}

    for rule in retention.ttl_rules():
        document = by_collection[rule.collection]
        specs = {spec.name: spec for spec in index_check.declared_for(document)}
        assert rule.enforcer in specs, (
            f"{rule.collection}'s TTL rule names index {rule.enforcer!r}, which is not declared"
        )
        spec = specs[rule.enforcer]
        assert spec.expire_after_seconds is not None, (
            f"{rule.enforcer} is not a TTL index, so {rule.collection}'s "
            "retention rule has no mechanism"
        )
        if rule.expire_after_seconds is not None:
            assert spec.expire_after_seconds == rule.expire_after_seconds, (
                f"{rule.collection}: §5 says {rule.days} days "
                f"({rule.expire_after_seconds}s) and the index says "
                f"{spec.expire_after_seconds}s"
            )


def test_every_cron_rule_names_a_declared_task():
    """The half ADR-013 had to add.

    §5 named five nightly crons and §10's inventory declared one of them, so
    four retention rules had no mechanism that could exist -
    `core/tasks.py` refuses at import any task absent from the inventory. This
    is the assertion that keeps them in step.
    """
    missing = sorted(
        {rule.enforcer for rule in retention.cron_rules() if rule.enforcer not in DECLARED}
    )

    assert missing == [], (
        f"retention rule(s) name task(s) {missing} that §10's inventory does not "
        "declare, so `core.tasks.task` would refuse them at import. Add the row "
        "to §10 - which is what ADR-013 did for the first four."
    )


def test_every_retention_task_is_a_cron():
    """A retention sweep triggered by an event is a sweep that runs when
    something else happens, which is not a retention window."""
    for rule in retention.cron_rules():
        assert DECLARED[rule.enforcer].cron is not None, (
            f"{rule.enforcer} enforces a retention window but has no cron trigger"
        )


def test_the_retention_sweeps_run_after_the_backup():
    """ADR-013's schedule, and the reason for it.

    `ops.backup` is 02:00 and `account.purge_deleted` is 03:00; the four sweeps
    are 04:00. So a purge is always recoverable from that night's backup, and a
    deleted user's rows are gone before the retention sweeps have to consider
    them.
    """

    def minute_hour(name: str) -> tuple[int, int]:
        expression = DECLARED[name].cron
        assert expression, f"{name} has no cron"
        fields = expression.split()
        return int(fields[0]), int(fields[1])

    assert minute_hour("ops.backup")[1] == 2
    assert minute_hour("account.purge_deleted")[1] == 3
    for name in (
        "jobs.purge_expired",
        "connector_runs.purge",
        "notifications.purge",
        "ops.purge_failed_tasks",
    ):
        assert minute_hour(name)[1] == 4, f"{name} does not run after the backup and the purge"


# -- the specification and the transcription agree ----------------------------


def test_every_row_in_the_spec_table_is_transcribed(repo: Path):
    """§5's table, compared row by row against `core/retention.py`.

    Matched on the collection name in the row's first cell. §5's rows are prose
    ("`jobs`, expired", "`reminders`, sent or cancelled"), so the comparison is
    by the backticked collection rather than by the whole cell - which is what
    lets one collection carry two rows.
    """
    parsed = table_rows(repo)
    assert len(parsed) >= 12, f"§5's table parsed to {len(parsed)} rows"

    named: set[str] = set()
    for data, _, _ in parsed:
        named |= set(re.findall(r"`([a-z_]+)`", data))

    transcribed = {rule.collection for rule in RULES}
    # `users` and the user-owned collections are one row in §5 ("Everything
    # user-owned, after a deletion request") and many rows here, because a
    # coverage test has to name each collection.
    missing = sorted(named - transcribed - set(RETAINED_INDEFINITELY))

    assert missing == [], f"§5 names {missing} and core/retention.py does not transcribe it"


def test_the_grace_period_and_backup_window_match_the_spec(repo: Path):
    """§5: a 7-day grace, and 14-day backups.

    Both appear in the consent text (`SEC-04` item 4 requires the backup window
    be disclosed), so three places have to agree: the spec, this module, and the
    copy in `core/consent.py`. That is the `AC-AI-05.8` pattern - a promise a
    user reads has to be the promise the code keeps.
    """
    text = (repo / SPEC).read_text(encoding="utf-8")
    section = text.split("## 5. Retention", 1)[1].split("## 6.", 1)[0]

    assert DELETION_GRACE_DAYS == 7
    assert BACKUP_RETENTION_DAYS == 14
    assert "7-day" in section
    assert "14 days" in section or "14 d" in section

    # The free tier, which is what D5 selects. The tier is asserted against
    # `Settings` by `test_consent_matches_tier.py`; what matters here is that
    # the *numbers* in the copy are the ones this module holds.
    from app.core.consent import Tier, consent_items

    items = {item.key: item for item in consent_items(Tier.FREE)}
    assert f"{BACKUP_RETENTION_DAYS} days" in items["retention"].body
    assert f"{DELETION_GRACE_DAYS} days" in items["retention"].body


def test_the_r2_collections_have_no_rule_yet():
    """The three R2 collections are `absent` (`01-foundations.md` §15), so a
    retention rule for one would be a rule for data that does not exist -
    which is the fifth state §15 forbids."""
    ruled = {rule.collection for rule in RULES} | set(RETAINED_INDEFINITELY)

    for collection in ABSENT_UNTIL_R2:
        assert collection not in ruled, (
            f"{collection} is an R2 collection with an R1 retention rule"
        )


def test_the_coverage_check_would_catch_a_gap():
    """The negative control.

    `test_every_collection_has_a_rule_or_is_allowlisted` compares two sets; if
    `covered()` returned every possible name it would pass over anything. This
    proves a name outside both the table and the allowlist is reported.
    """
    assert "sessions" not in retention.covered()
    assert retention.rules_for("sessions") == ()


@pytest.mark.parametrize("rule", RULES, ids=[f"{r.collection}:{r.enforcer}" for r in RULES])
def test_every_rule_explains_itself(rule: retention.Rule):
    """A window with no reason gets shortened by whoever next needs the space,
    or lengthened by whoever next gets nervous. The reason is what makes it a
    decision that can be revisited rather than a number to be argued about."""
    assert len(rule.why) > 40, f"{rule.collection}'s reason is too short to be one"
