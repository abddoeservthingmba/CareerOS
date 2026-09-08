"""T-DATA-05.1 - every TTL index exists with the stated window.

`AC-DATA-05.1`: "Each TTL index above exists with the stated
`expireAfterSeconds`."

**Why the window has to be compared and not just the index.** A TTL index with
the wrong `expireAfterSeconds` is the worst kind of retention bug: it works. Rows
expire, the collection stays small, nothing errors, and `/readyz` is green. The
only symptom of a 30-day promise enforced by a 90-day TTL is that data the
product said was gone is still there - which nobody notices until somebody asks,
and by then the answer has been wrong for months.

**And why a TTL rather than a cron wherever possible.** §5 uses both, and they
are not equivalent. A TTL index cannot fall behind, cannot be paused during an
incident, and cannot be dropped from a schedule; the rule lives with the
collection and Mongo's reaper runs about once a minute. A cron can do all three.
So §5 uses a cron only where the rule needs a *decision* - `jobs`
expired-but-referenced keeps the document and clears two fields - and this file
asserts that each of the four TTL rules really is one.

**The reaper is eventual, and that matters at the boundary.** Mongo's background
task runs roughly every 60 seconds, so a document past its TTL can still be
read for up to a minute. That is fine for `raw_listings` and `ai_usage`, whose
windows are 30 and 400 days. It is *not* fine for `refresh_tokens` and
`email_tokens`, where a minute of extra life on an expired credential is a
minute of unauthorised access - so both are also checked at use, and this file
records why rather than leaving the TTL looking sufficient.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.retention import Mechanism, ttl_rules
from app.documents import all_documents, collection_name
from app.infra import indexes as index_check
from app.infra.mongo import init_documents

RULES = ttl_rules()


@pytest.fixture
async def initialised(database: Any) -> Any:
    await init_documents(database, all_documents())
    return database


# -- the criterion ------------------------------------------------------------


@pytest.mark.parametrize("rule", RULES, ids=[f"{r.collection}:{r.enforcer}" for r in RULES])
async def test_the_ttl_index_exists_in_the_database(initialised: Any, rule):
    """`AC-DATA-05.1`, against a live database rather than a declaration.

    A declaration Mongo rejected - a TTL on a compound key, which is not
    allowed - passes every static check and leaves the collection with no
    retention at all.
    """
    live = {spec.name: spec for spec in await index_check.live_for(initialised, rule.collection)}

    assert rule.enforcer in live, (
        f"{rule.collection}'s retention rule names TTL index {rule.enforcer!r}, "
        f"which does not exist. Present: {sorted(live)}"
    )


@pytest.mark.parametrize("rule", RULES, ids=[f"{r.collection}:{r.enforcer}" for r in RULES])
async def test_the_window_is_the_one_the_spec_states(initialised: Any, rule):
    """The half that fails silently.

    A wrong window works: rows expire, the collection stays small, nothing
    errors. The only symptom is that data the product said was gone is still
    there.
    """
    live = {spec.name: spec for spec in await index_check.live_for(initialised, rule.collection)}
    spec = live[rule.enforcer]

    assert spec.expire_after_seconds is not None, (
        f"{rule.enforcer} exists but is not a TTL index, so {rule.collection} "
        "has no retention mechanism at all"
    )
    if rule.expire_after_seconds is not None:
        assert spec.expire_after_seconds == rule.expire_after_seconds, (
            f"{rule.collection}: §5 states {rule.days} days "
            f"({rule.expire_after_seconds}s) and the live index expires after "
            f"{spec.expire_after_seconds}s"
        )


async def test_the_two_per_token_ttls_expire_at_the_stored_time(initialised: Any):
    """`refresh_tokens` and `email_tokens` have `expireAfterSeconds: 0`.

    Which is not "expire immediately" - it means "expire at the time in the
    indexed field". That is the only way to express a per-row lifetime, and it
    is easy to misread as a bug and "fix" to a fixed window, which would expire
    every token at a uniform age regardless of what it was issued for.
    """
    for collection in ("refresh_tokens", "email_tokens"):
        live = {spec.name: spec for spec in await index_check.live_for(initialised, collection)}
        assert live["expires_at_ttl"].expire_after_seconds == 0, (
            f"{collection}'s TTL is not 0, so it expires tokens at a uniform age "
            "rather than at each token's own expires_at"
        )


async def test_the_fixed_window_ttls_are_not_zero(initialised: Any):
    """The mirror mistake. `raw_listings` and `ai_usage` index a *creation*
    time, so a zero window would delete every row within a minute of writing
    it - and `ai_usage` is the accounting table, so the first symptom would be
    a cost dashboard that reads zero."""
    for collection, name in (("raw_listings", "fetched_at_ttl"), ("ai_usage", "at_ttl")):
        live = {spec.name: spec for spec in await index_check.live_for(initialised, collection)}
        window = live[name].expire_after_seconds
        assert window is not None and window > 0


# -- the mechanism choice is deliberate ----------------------------------------


def test_every_ttl_rule_is_a_single_field_index():
    """Mongo does not support a TTL on a compound index, and it does not
    complain about the declaration - it just never expires anything.

    So a rule whose enforcer is compound is a rule with no mechanism, and it
    would pass a check that only looked for the index by name.
    """
    by_collection = {collection_name(d): d for d in all_documents()}

    for rule in RULES:
        specs = {
            spec.name: spec for spec in index_check.declared_for(by_collection[rule.collection])
        }
        assert len(specs[rule.enforcer].keys) == 1, (
            f"{rule.enforcer} is compound; Mongo will not expire anything and will not say so"
        )


def test_the_four_ttl_rules_are_the_ones_the_spec_names():
    """§5 names exactly four TTL rows: `raw_listings`, `refresh_tokens`,
    `email_tokens`, `ai_usage`.

    A fifth would mean a cron rule was converted to a TTL, which is usually
    right - a TTL cannot fall behind - and is a decision worth seeing in a
    diff, because it also means the rule lost the ability to make a decision.
    """
    assert {rule.collection for rule in RULES} == {
        "raw_listings",
        "refresh_tokens",
        "email_tokens",
        "ai_usage",
    }
    for rule in RULES:
        assert rule.mechanism is Mechanism.TTL_INDEX


def test_the_jobs_rule_is_a_cron_and_says_why():
    """The one rule that cannot be a TTL, and the reason is in the rule.

    `AC-DATA-05.2` keeps an expired job that an application references and
    clears its description fields. No TTL can express "delete unless something
    else points at you", so this is the rule that justifies the cron mechanism
    existing at all.
    """
    from app.core.retention import rules_for

    (rule,) = rules_for("jobs")

    assert rule.mechanism is Mechanism.CRON
    assert "reference" in rule.why or "application" in rule.why


def test_the_reaper_is_eventual_and_the_credentials_do_not_rely_on_it():
    """Mongo's TTL task runs about every 60 seconds.

    Fine for a 30-day window. Not fine for a token: a minute of extra life on
    an expired credential is a minute of unauthorised access. So `expires_at`
    is checked at use as well as indexed, and this asserts the field is there
    to check - a TTL-only design would look complete and leave a one-minute
    window on every logout.
    """
    from app.modules.auth.models import EmailToken, RefreshToken

    for document in (RefreshToken, EmailToken):
        assert "expires_at" in document.model_fields
        assert document.model_fields["expires_at"].is_required(), (
            f"{document.__name__}.expires_at is optional, so a row could exist "
            "that neither the TTL nor a use-time check would expire"
        )
