"""Retention - `DATA-05`.

`17-data-model.md` §5: "Every class of data has one stated lifetime, enforced by
a mechanism, not by intention."

And its first constraint, which is what makes this module rather than a
convention: **"A retention rule with no mechanism is a defect. Every row above
names one."**

So §5's table is transcribed here as data, each row naming the mechanism that
enforces it, and `tests/spec/test_retention_coverage.py` compares this against
both the specification's table and the actual collection list. Three things can
then be checked by machine rather than by memory:

* every collection has a rule, or is on an explicit "retained indefinitely"
  allowlist (`AC-DATA-05.4`);
* every TTL rule matches the `expireAfterSeconds` actually declared on the
  index (`AC-DATA-05.1`);
* every cron rule names a task that exists in §10's inventory (ADR-013 added
  the four that were missing).

**Why the table is here and not only in the tests.** A retention window is a
promise made to a user in the consent text (`SEC-04`) and to a regulator in a
data-protection answer. It has to be readable from the code that enforces it,
by whoever is asked "how long do you keep this" - and the answer has to be one
number, not a number in a spec and a different one in an index.

**The two mechanisms are not interchangeable.** A TTL index cannot fall behind
and cannot be forgotten; Mongo's reaper runs about once a minute and the rule
lives with the collection. A cron can fail, can be paused during an incident,
and can be silently dropped from a schedule. So TTL is used wherever the rule is
"delete rows older than X" with no conditions, and a cron only where the rule
needs a *decision* - `jobs` expired-but-referenced keeps the document and clears
two fields, which no TTL can express.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Mechanism(StrEnum):
    """How a rule is enforced. §5's third column, as a type.

    Three members and no fourth: "manual review", "documented policy" and
    "the deletion endpoint" are all things §5's first constraint calls a defect.
    """

    #: A TTL index. Cannot fall behind, cannot be forgotten.
    TTL_INDEX = "ttl_index"
    #: A nightly cron. Needed where the rule involves a decision a TTL cannot
    #: express, and weaker for it - a cron can fail or be paused.
    CRON = "cron"
    #: No automatic deletion. Only for rows whose lifetime is bounded by
    #: something else - an account purge - and each one says what.
    ACCOUNT_PURGE = "account_purge"


@dataclass(frozen=True, slots=True)
class Rule:
    """One row of §5's table."""

    collection: str
    #: The stated lifetime in days. `None` where there is no fixed window -
    #: `audit_log`'s seven years is bounded by the account purge first, and
    #: `jobs, active` has no window at all until the source stops showing it.
    days: int | None
    mechanism: Mechanism
    #: The index or task that enforces it. Compared against the real one.
    enforcer: str
    why: str

    @property
    def expire_after_seconds(self) -> int | None:
        return None if self.days is None else self.days * 86_400


#: §5's table, transcribed. Keyed by collection *and* condition, because two
#: rows can govern one collection: `jobs` has one rule for active listings and
#: one for expired, and `reminders` has one for sent-or-cancelled and nothing
#: for scheduled ones.
RULES: tuple[Rule, ...] = (
    Rule(
        "raw_listings",
        30,
        Mechanism.TTL_INDEX,
        "fetched_at_ttl",
        "the largest collection by volume, and M0 has 512 MB total",
    ),
    Rule(
        "refresh_tokens",
        None,
        Mechanism.TTL_INDEX,
        "expires_at_ttl",
        "until expires_at; the window is per-token, not fixed",
    ),
    Rule(
        "email_tokens",
        None,
        Mechanism.TTL_INDEX,
        "expires_at_ttl",
        "until expires_at; the window is per-token, not fixed",
    ),
    Rule(
        "ai_usage",
        400,
        Mechanism.TTL_INDEX,
        "at_ttl",
        "13 months, so a year-on-year cost comparison has a full final month",
    ),
    Rule(
        "jobs",
        90,
        Mechanism.CRON,
        "jobs.purge_expired",
        "90 days after expired_at, unless an application references it - which "
        "no TTL can express, so this is the one deletion that needs a decision",
    ),
    Rule(
        "connector_runs",
        180,
        Mechanism.CRON,
        "connector_runs.purge",
        "ingestion statistics; useful for a season, not forever",
    ),
    Rule(
        "notifications",
        180,
        Mechanism.CRON,
        "notifications.purge",
        "read or unread; an inbox row nobody opened in six months is not going to be opened",
    ),
    Rule(
        "reminders",
        180,
        Mechanism.CRON,
        "notifications.purge",
        "sent or cancelled only - a scheduled reminder is live data, and a TTL "
        "would delete one before it fired",
    ),
    Rule(
        "failed_tasks",
        90,
        Mechanism.CRON,
        "ops.purge_failed_tasks",
        "resolved only; an unresolved dead letter is work that did not happen",
    ),
    Rule(
        "audit_log",
        None,
        Mechanism.ACCOUNT_PURGE,
        "account.purge_deleted",
        "7 years or until account hard-delete, whichever is first - so the "
        "account purge is the binding mechanism and there is no TTL",
    ),
    Rule(
        "users",
        7,
        Mechanism.CRON,
        "account.purge_deleted",
        "7-day grace after a deletion request, then hard delete including R2",
    ),
    Rule(
        "resumes",
        7,
        Mechanism.CRON,
        "account.purge_deleted",
        "user-owned; bounded by the account purge, not by an age",
    ),
    Rule(
        "profiles",
        7,
        Mechanism.CRON,
        "account.purge_deleted",
        "user-owned; bounded by the account purge, not by an age",
    ),
    Rule(
        "match_scores",
        7,
        Mechanism.CRON,
        "account.purge_deleted",
        "user-owned; bounded by the account purge, not by an age",
    ),
    Rule(
        "answer_bank",
        7,
        Mechanism.CRON,
        "account.purge_deleted",
        "user-owned; bounded by the account purge, not by an age",
    ),
    Rule(
        "application_packs",
        7,
        Mechanism.CRON,
        "account.purge_deleted",
        "user-owned; bounded by the account purge, not by an age",
    ),
    Rule(
        "applications",
        7,
        Mechanism.CRON,
        "account.purge_deleted",
        "user-owned; bounded by the account purge, not by an age",
    ),
    Rule(
        "user_job_actions",
        7,
        Mechanism.CRON,
        "account.purge_deleted",
        "user-owned; bounded by the account purge, not by an age",
    ),
)

#: `AC-DATA-05.4`'s "explicit 'retained indefinitely' allowlist".
#:
#: Two collections, and each has to say why. The criterion demands the allowlist
#: be explicit precisely because "we keep it forever" is the default outcome of
#: not deciding, and an allowlist makes it a decision somebody made.
RETAINED_INDEFINITELY: dict[str, str] = {
    "jobs": (
        "a job belongs to nobody and is shared between users. §5: 'jobs are "
        "shared and are never deleted by a user action'. The expired-job rule "
        "above bounds it; an active listing is kept while its source keeps "
        "showing it."
    ),
    "skill_aliases": (
        "a global alias table with no user data in it. Deleting an alias would "
        "change how every user's skills canonicalize, which is a taxonomy "
        "decision (`PROF-06`), not retention."
    ),
    "feature_flags": (
        "one row per flag, no user data, and the row *is* the configuration. "
        "Deleting one silently reverts a flag to its environment default."
    ),
}

#: §5: the deletion grace period, and the only period during which a
#: soft-deleted user's data exists.
DELETION_GRACE_DAYS = 7

#: §5: "Backups | 14 days | R2 lifecycle rule on `backups/`". Disclosed in the
#: consent text (`SEC-04`), which is why the number lives in code rather than
#: only in a bucket's configuration - the consent copy and the lifecycle rule
#: have to agree, and `AC-AI-05.8`'s pattern is what keeps promises honest.
BACKUP_RETENTION_DAYS = 14


def rules_for(collection: str) -> tuple[Rule, ...]:
    return tuple(rule for rule in RULES if rule.collection == collection)


def covered() -> frozenset[str]:
    """Every collection with a rule or an allowlist entry."""
    return frozenset({rule.collection for rule in RULES} | set(RETAINED_INDEFINITELY))


def ttl_rules() -> tuple[Rule, ...]:
    return tuple(rule for rule in RULES if rule.mechanism is Mechanism.TTL_INDEX)


def cron_rules() -> tuple[Rule, ...]:
    return tuple(rule for rule in RULES if rule.mechanism is Mechanism.CRON)


__all__ = [
    "BACKUP_RETENTION_DAYS",
    "DELETION_GRACE_DAYS",
    "RETAINED_INDEFINITELY",
    "RULES",
    "Mechanism",
    "Rule",
    "covered",
    "cron_rules",
    "rules_for",
    "ttl_rules",
]
