"""T-AI-05.8 - the consent text and the configured tier cannot disagree.

`AC-AI-05.8`: "The consent text rendered by the client matches the tier actually
configured, asserted by a test that reads both the flag and the copy key."

`05-ai-layer.md` §5.4 states the failure as the one unacceptable outcome rather
than as a risk:

> What is **not** acceptable is a consent text that implies the first while
> running the second.

It is an easy thing to end up doing. The copy gets written early, by someone who
intends to be on the paid tier. The tier is an environment variable, set later
by someone else — or left at its default, or changed in a month when the bill
looks bad. Nothing connects the two, so nothing notices, and a user reads a
promise that stopped being true.

This is the connection. The copy and the tier are read from one module and
compared here, so drift is a failing build rather than a false statement in
front of a user.

**The current configuration is the free tier**, which means the copy has to say
that Google may use résumé text to improve their own products. `SEC-04` requires
that "above the fold, in plain language" — so the tests below check that the
sentence a person actually reads contains the claim, not that a linked policy
does.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.consent import (
    AI_DATA_USE,
    AI_DATA_USE_FREE_TIER,
    AI_DATA_USE_PAID_TIER,
    CONSENT_VERSION,
    Tier,
    ai_data_use_copy,
    consent_items,
    item_keys,
    tier_from_settings,
)
from app.main import create_app

# -- the criterion -----------------------------------------------------------


def test_the_copy_matches_the_configured_tier(settings_factory):
    """AC-AI-05.8.

    One assertion, reading both sides from the places that actually govern
    them: `Settings` for the tier, `core.consent` for the copy.
    """
    settings = settings_factory()
    tier = tier_from_settings(settings)

    assert ai_data_use_copy(tier) == AI_DATA_USE[tier]


def test_the_configured_tier_is_the_free_one(settings_factory):
    """The current D5 position, stated so a change to it is visible in a diff
    of this file rather than only in a `.env`."""
    assert tier_from_settings(settings_factory()) is Tier.FREE


def test_the_free_tier_copy_says_the_provider_may_train_on_it(settings_factory):
    """The sentence the free tier obliges.

    Google's own pricing page: free tier content is "used to improve our
    products". A consent screen that omitted this while running the free tier is
    precisely what §5.4 forbids.
    """
    copy = ai_data_use_copy(tier_from_settings(settings_factory()))

    assert "may use that text to improve their own products" in copy
    assert "work history" in copy


def test_the_paid_tier_copy_says_the_opposite(settings_factory):
    """And the two are not paraphrases of each other. If both said something
    vague and similar, the check above would pass for either tier."""
    paid = ai_data_use_copy(Tier.PAID)

    assert "does not use that text to train" in paid
    assert "may use that text to improve" not in paid


def test_switching_the_tier_switches_the_copy(settings_factory):
    """The mechanism, exercised. A change of one environment variable has to
    change what the user reads - that is the entire requirement."""
    free = settings_factory(AI_CONSENT_TIER="free")
    paid = settings_factory(AI_CONSENT_TIER="paid")

    assert ai_data_use_copy(tier_from_settings(free)) == AI_DATA_USE_FREE_TIER
    assert ai_data_use_copy(tier_from_settings(paid)) == AI_DATA_USE_PAID_TIER


def test_an_unknown_tier_raises_rather_than_defaulting():
    """There is deliberately no default.

    A fallback here would show one tier's promise while the other was in force,
    which is the failure mode by another route - and it would do so silently.
    """
    with pytest.raises(ValueError, match="no default"):
        ai_data_use_copy("freemium")


def test_the_settings_field_only_accepts_the_two_positions(settings_factory):
    """`Literal["free", "paid"]`. §5.4 allows exactly two, and a typo in a
    deploy's environment fails the boot rather than selecting neither."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        settings_factory(AI_CONSENT_TIER="freemium")


# -- what the client renders -------------------------------------------------


def test_the_ai_item_carries_the_tier_specific_copy(settings_factory):
    """`SEC-04`'s itemized purposes. The AI item is the one that varies, and it
    has to vary in the rendered list rather than only in a constant."""
    tier = tier_from_settings(settings_factory())
    items = {item.key: item for item in consent_items(tier)}

    assert items["ai_data_use"].body == AI_DATA_USE[tier]
    assert items["ai_data_use"].heading == "What we send to an AI provider"


def test_every_item_has_body_text(settings_factory):
    """An empty purpose is a purpose nobody consented to. `BASE_ITEMS` leaves
    the AI body blank on purpose, so this also asserts it gets filled in."""
    for item in consent_items(tier_from_settings(settings_factory())):
        assert item.body.strip(), f"{item.key} has no body text"
        assert item.heading.strip()


def test_the_five_purposes_are_the_ones_sec_04_names():
    """`16-security-and-compliance.md` §4's list: what is stored, what goes to
    an AI provider, what is fetched from third parties, retention, rights."""
    assert item_keys() == (
        "what_is_stored",
        "ai_data_use",
        "third_party_fetch",
        "retention",
        "rights",
    )


def test_the_copy_is_readable_in_under_a_minute(settings_factory):
    """§4: "itemized purposes the user can read in under a minute, above the
    fold, in plain language".

    ~200 words at a slow 200 wpm is a minute. A consent screen that took longer
    is one nobody reads, and an unread consent is not consent - which makes
    length a compliance property rather than a style preference.
    """
    items = consent_items(tier_from_settings(settings_factory()))
    words = sum(len(f"{item.heading} {item.body}".split()) for item in items)

    assert words <= 260, f"the consent copy is {words} words"


def test_no_purpose_hides_behind_a_link(settings_factory):
    """§5.4: the disclosure is "above the fold - not in a linked policy".

    "See our privacy policy" is the standard way to make a disclosure
    technically present and practically invisible.
    """
    for item in consent_items(tier_from_settings(settings_factory())):
        lowered = item.body.lower()
        assert "privacy policy" not in lowered, f"{item.key} defers to a policy"
        assert "http" not in lowered, f"{item.key} defers to a link"


def test_the_retention_item_states_the_backup_window(settings_factory):
    """`SEC-04` item 4 requires "including that backups persist for 14 days
    after a deletion request". A deletion promise that omits the backups is not
    true."""
    items = {item.key: item for item in consent_items(tier_from_settings(settings_factory()))}

    assert "14 days" in items["retention"].body
    assert "7 days" in items["retention"].body


def test_the_ai_item_states_that_the_file_never_leaves(settings_factory):
    """HR-8. The distinction between sending resume *text* and sending the
    *file* is one users care about and would not otherwise know."""
    items = {item.key: item for item in consent_items(tier_from_settings(settings_factory()))}

    assert "never send the resume file" in items["ai_data_use"].body


def test_no_item_mentions_a_provider_that_is_not_configured(settings_factory):
    """The copy names Gemini because Gemini is what production uses. Naming a
    provider we do not use would be a false statement; failing to name the one
    we do would fail `SEC-04` item 2, which requires the provider be named."""
    items = {item.key: item for item in consent_items(tier_from_settings(settings_factory()))}
    body = items["ai_data_use"].body

    assert "Gemini" in body
    for absent in ("OpenAI", "Anthropic", "Claude", "GPT"):
        assert absent not in body


# -- the version -------------------------------------------------------------


def test_the_consent_version_is_recorded():
    """`17-data-model.md` §2.1: `consent` is an append-only array, and an entry
    records the version accepted. Without a version, "what did this user agree
    to in September" is unanswerable after the copy changes."""
    assert CONSENT_VERSION >= 1


def test_the_app_boots_with_the_tier_configured(settings_factory):
    """The end-to-end shape: the tier is a real setting on a real app, not a
    constant in a test."""
    app = create_app(settings_factory())
    client = TestClient(app)

    assert client.get("/healthz").status_code == 200
    assert app.state.settings.AI_CONSENT_TIER in ("free", "paid")
