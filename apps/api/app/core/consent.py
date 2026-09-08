"""Consent copy, tied to the tier actually configured - `AI-05` §5.4, `SEC-04`.

`AC-AI-05.8`: "The consent text rendered by the client matches the tier actually
configured, asserted by a test that reads both the flag and the copy key."

§5.4 states the failure this exists to prevent, and states it as the one
unacceptable outcome rather than as a risk:

> What is **not** acceptable is a consent text that implies the first while
> running the second.

Which is an easy thing to end up doing by accident. The copy is written once,
early, when someone intends to be on the paid tier; the tier is a variable
someone else sets later, or leaves unset, or changes to save money in a month
when the bill looks bad. Nothing connects them, so nothing notices. The user
reads a promise that stopped being true.

So the copy and the tier are read from one place and compared by a test. There
is no version of this module in which the strings live somewhere the tier
setting cannot be checked against.

**Both texts are here, not only the configured one.** `05-ai-layer.md` §5.4
allows two positions and `16-security-and-compliance.md` §4 "holds the copy for
both", so both are written and one is selected. Keeping only the configured
one would mean a tier change is a copywriting task, which is how a tier change
ships without one.

**Why the wording is blunt.** `SEC-04` requires the itemized purposes to be
readable "in under a minute, above the fold, in plain language". For the free
tier that means saying, in the sentence a user actually reads, that Google may
use what they paste to improve their own products. "Data may be processed by
third-party subprocessors in accordance with our privacy policy" is technically
true and communicates nothing, and a consent obtained that way is not consent to
the thing that happens.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

#: `17-data-model.md` §2.1: `consent` is an append-only array on the user
#: document. This version is what a new acceptance records, and it increments
#: when what we do changes - `SEC-04`: "A change to what we do requires
#: re-consent, not a quiet policy edit."
CONSENT_VERSION = 1


class Tier(StrEnum):
    """§5.4's two acceptable positions, and nothing else.

    Not a boolean. `free`/`paid` reads correctly at every call site, and a
    boolean called `is_paid` would invert somewhere - which for this particular
    flag means telling users the opposite of the truth.
    """

    FREE = "free"
    PAID = "paid"


@dataclass(frozen=True)
class ConsentItem:
    """One of `SEC-04`'s five itemized purposes."""

    key: str
    heading: str
    body: str


#: The sentence that changes with the tier, and the only one that does.
#:
#: Sourced from the provider's own pricing page (read 2026-09-07): free tier -
#: content "used to improve our products"; paid tier - content "**not** used to
#: improve our products". The two strings below are that distinction in language
#: a person can act on.
AI_DATA_USE_FREE_TIER = (
    "We send the text of your resume and of the job descriptions you look at to "
    "Google's Gemini API so it can extract your skills, score matches and draft "
    "applications. **On the free tier we currently use, Google may use that text "
    "to improve their own products and services.** That includes your work "
    "history and the wording of your resume. We never send the resume file "
    "itself, and we never send your email address or your name."
)

AI_DATA_USE_PAID_TIER = (
    "We send the text of your resume and of the job descriptions you look at to "
    "Google's Gemini API so it can extract your skills, score matches and draft "
    "applications. We use a paid tier, under which Google does not use that text "
    "to train or improve their models. We never send the resume file itself, and "
    "we never send your email address or your name."
)

AI_DATA_USE: dict[Tier, str] = {
    Tier.FREE: AI_DATA_USE_FREE_TIER,
    Tier.PAID: AI_DATA_USE_PAID_TIER,
}


def ai_data_use_copy(tier: Tier | str) -> str:
    """The one sentence that has to match the configured tier.

    Raises on an unknown tier rather than falling back. A default here would be
    the exact failure §5.4 forbids: whichever string was chosen as the default
    would eventually be shown alongside the other tier.
    """
    try:
        return AI_DATA_USE[Tier(str(tier))]
    except ValueError as unknown:
        raise ValueError(
            f"{tier!r} is not a consent tier. §5.4 allows exactly two positions, "
            f"and there is deliberately no default: a fallback here would show "
            f"one tier's promise while the other was in force."
        ) from unknown


def tier_from_settings(settings: object) -> Tier:
    """Which tier is actually configured.

    Read from `AI_CONSENT_TIER`, which exists for one reason: the tier is a
    *commercial* fact that the code cannot infer. A paid Gemini key and a free
    one are the same string, so nothing about the credential reveals which
    terms apply. Someone has to state it, and `AC-AI-05.8` is what makes the
    statement load-bearing rather than decorative.
    """
    return Tier(str(getattr(settings, "AI_CONSENT_TIER", Tier.FREE)))


#: `SEC-04`'s five itemized purposes. The AI item is filled in per tier by
#: `consent_items`, which is why its body is empty here.
BASE_ITEMS: tuple[ConsentItem, ...] = (
    ConsentItem(
        key="what_is_stored",
        heading="What we keep",
        body=(
            "Your resume file, the text we extract from it, the structured "
            "profile that text becomes, your job preferences, the applications "
            "you track, the drafts we generate for you, and your reminders."
        ),
    ),
    ConsentItem(key="ai_data_use", heading="What we send to an AI provider", body=""),
    ConsentItem(
        key="third_party_fetch",
        heading="Where the jobs come from",
        body=(
            "We fetch public job listings from named sources on a schedule. We "
            "contact them; they do not learn who is searching, and they never "
            "receive your resume or your profile."
        ),
    ),
    ConsentItem(
        key="retention",
        heading="How long we keep it",
        body=(
            "Until you delete it. Deleting your account removes everything "
            "within 7 days, including your files. Backups made before that "
            "request age out within 14 days."
        ),
    ),
    ConsentItem(
        key="rights",
        heading="What you can do",
        body=(
            "Export everything, or delete your account, from settings - both "
            "are buttons in the product, not an email you have to send. "
            "Deletion starts a 7-day clock you can cancel."
        ),
    ),
)


def consent_items(tier: Tier | str) -> tuple[ConsentItem, ...]:
    """The five purposes, with the AI item written for the tier in force."""
    copy = ai_data_use_copy(tier)
    return tuple(
        item if item.key != "ai_data_use" else ConsentItem(item.key, item.heading, copy)
        for item in BASE_ITEMS
    )


def item_keys() -> tuple[str, ...]:
    """The keys an acceptance records against (`17-data-model.md` §2.1).

    Stored per acceptance so that "what did this user agree to in September"
    stays answerable after the copy is rewritten - which `SEC-04` requires,
    because the array is append-only and never overwritten.
    """
    return tuple(item.key for item in BASE_ITEMS)


ConsentTier = Literal["free", "paid"]

__all__ = [
    "AI_DATA_USE",
    "AI_DATA_USE_FREE_TIER",
    "AI_DATA_USE_PAID_TIER",
    "BASE_ITEMS",
    "CONSENT_VERSION",
    "ConsentItem",
    "ConsentTier",
    "Tier",
    "ai_data_use_copy",
    "consent_items",
    "item_keys",
    "tier_from_settings",
]
