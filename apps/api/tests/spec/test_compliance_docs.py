"""T-AI-05.1 - the procurement statement exists, is complete, and is current.

`AC-AI-05.1`: "`docs/compliance/ai-providers.md` exists, states the dedicated
Cloud project and billing account, names the budget-alert threshold, and carries
a review date within 90 days. (R1 gate: signed statement.)"

`05-ai-layer.md` §5.2 is explicit about what this test can and cannot do: "This
is a manual control with a documented owner; **the code cannot verify it**, so
the gate item is a signed statement, not a test."

So this checks the *form*: the document exists, has every required heading,
carries a review date inside the window, and has no field still marked
`UNFILLED`. Whether the statements are true is a human's signature, and no
assertion here should be read as evidence that they are.

**Why the form is worth checking at all.** A compliance document that exists but
is half-written is worse than one that is missing, because it looks like the
control is in place. `UNFILLED` is a deliberate sentinel: it makes an unsigned
statement *fail* rather than sit in the repository looking official, and the
failure is what stops the R1 gate being walked past.

The document is currently unsigned, so `test_no_field_is_still_unfilled` is
expected to fail until the owner fills it in. That is recorded in
`tests/spec/spec_defects.py` as an open item rather than being asserted away -
weakening the check to make it pass would defeat the point of having it.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.ai import pricing

DOCUMENT = Path("docs") / "compliance" / "ai-providers.md"

#: `AC-AI-05.1`'s four required statements, as the headings that carry them.
REQUIRED_HEADINGS = (
    "## 1. Provider inventory",
    "## 2. The dedicated Cloud project",
    "### Budget alert",
    "## 3. Credential isolation (HR-6)",
    "## 4. Data sent to a provider, and what may be done with it",
    "### D5 — the tier, and what its terms permit",
    "## 5. Model identifiers and prices",
    "## 6. Review",
    "## Signature",
)

#: §5.2's window. The same 90 days the price verification uses, so the two go
#: stale together and are refreshed in one sitting.
MAX_REVIEW_AGE_DAYS = 90

UNFILLED = "UNFILLED"


@pytest.fixture
def text(repo: Path) -> str:
    return (repo / DOCUMENT).read_text(encoding="utf-8")


def dated(text: str, label: str) -> date | None:
    """A `| Label | YYYY-MM-DD |` row, or `None`."""
    found = re.search(rf"\|\s*{re.escape(label)}\s*\|\s*(\d{{4}}-\d{{2}}-\d{{2}})\s*\|", text)
    return date.fromisoformat(found.group(1)) if found else None


# -- it exists, and it has the required sections -----------------------------


def test_the_document_exists(repo: Path):
    """AC-AI-05.1, first clause."""
    assert (repo / DOCUMENT).is_file(), (
        f"{DOCUMENT.as_posix()} is missing. The R1 gate item is a signed "
        "statement about a control the code cannot verify; without the document "
        "there is nothing to sign."
    )


@pytest.mark.parametrize("heading", REQUIRED_HEADINGS)
def test_every_required_heading_is_present(text: str, heading: str):
    """A missing section is a statement nobody made."""
    assert heading in text, f"{heading!r} is missing"


def test_it_states_the_dedicated_cloud_project(text: str):
    """§5.2: "the key belongs to a Cloud project created solely for this
    product, with its own billing account"."""
    assert "Cloud project id" in text
    assert "Billing account" in text
    assert "Other APIs enabled in the project" in text


def test_it_names_the_budget_alert_threshold(text: str):
    """§5.2: "a project-level budget alert set at twice `AI_DAILY_COST_CAP_USD`
    × 30".

    The arithmetic is checked, not just the presence of a number. A document
    naming the wrong threshold is a control that does not fire.
    """
    assert "Alert threshold configured" in text
    assert "2 × 2.00 × 30 = $120.00 per month" in text, (
        "the stated threshold does not match 2 × AI_DAILY_COST_CAP_USD × 30 for the configured cap"
    )


def test_the_stated_threshold_matches_the_configured_cap(text: str, repo: Path):
    """And the cap it is derived from is the one actually configured.

    If someone raises `AI_DAILY_COST_CAP_USD` without revisiting the document,
    the alert threshold silently becomes too low - which means it fires on a
    normal day and gets muted.
    """
    example = (repo / ".env.example").read_text(encoding="utf-8")
    cap = next(
        line.split("=", 1)[1].strip()
        for line in example.split("\n")
        if line.startswith("AI_DAILY_COST_CAP_USD=")
    )
    expected = float(cap) * 2 * 30

    assert f"${expected:.2f} per month" in text, (
        f"AI_DAILY_COST_CAP_USD is {cap}, so the alert threshold should be ${expected:.2f}/month"
    )


def test_it_records_which_tier_is_in_force(text: str):
    """§5.4 (D5). The whole point of `AC-AI-05.8` is that this is a stated fact
    rather than an inferred one - a paid key and a free key are the same
    string."""
    assert "| Tier in force |" in text
    assert "**free**" in text or "**paid**" in text


def test_it_states_the_providers_data_use_terms(text: str):
    """The sentence a consent screen has to be honest about. Recorded with its
    source, because the terms are the provider's to change."""
    assert "used to improve" in text
    assert "ai.google.dev" in text


def test_it_names_the_review_owner_field(text: str):
    """§5.2: "a manual control with a documented owner". A control with no owner
    is a paragraph."""
    assert "Owner accountable for this control" in text
    assert "Reviewed by" in text


# -- it is current -----------------------------------------------------------


def test_it_carries_a_review_date(text: str):
    """AC-AI-05.1, last clause."""
    assert dated(text, "Last reviewed") is not None, "no `Last reviewed` date"
    assert dated(text, "Next review due") is not None, "no `Next review due` date"


def test_the_review_window_is_ninety_days(text: str):
    """The window §5.2 gives, asserted against the document's own two dates
    rather than against today - so the *policy* is checked here and the
    *freshness* below."""
    reviewed = dated(text, "Last reviewed")
    due = dated(text, "Next review due")

    assert reviewed is not None and due is not None
    assert (due - reviewed) <= timedelta(days=MAX_REVIEW_AGE_DAYS)


def test_the_review_is_not_overdue(text: str):
    """`AC-AI-05.1`'s "within 90 days".

    Uses the wall clock deliberately: this is the one assertion in the suite
    that is *supposed* to start failing with the passage of time. That is what
    a review date is for.
    """
    from app.core import clock

    reviewed = dated(text, "Last reviewed")
    assert reviewed is not None
    age = clock.now().date() - reviewed

    assert age <= timedelta(days=MAX_REVIEW_AGE_DAYS), (
        f"the compliance statement was last reviewed {age.days} days ago. "
        "Re-verify the model prices, the tier, and the budget alert, then "
        "update the dates."
    )


def test_the_review_window_matches_the_price_verification_window():
    """One window, two artifacts. If they differed, one would always be the
    stale one and nobody would know which."""
    assert MAX_REVIEW_AGE_DAYS == pricing.MAX_PRICE_AGE_DAYS


def test_the_prices_in_the_document_match_the_pricing_table(text: str):
    """The document is for a human; the table is what the code bills against.
    Two copies of a price is one copy too many, so this compares them."""
    for model in ("gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-embedding-001"):
        assert model in text, f"{model} is configured but not recorded in the statement"
        price = pricing.MODEL_PRICING[model]
        assert f"${price.input_per_million:.2f}" in text, (
            f"{model}'s input price in the document does not match model-pricing.yaml"
        )


def test_the_document_records_the_price_verification_date(text: str):
    """§5.2: "recorded with a date"."""
    assert f"**Verified on:** {pricing.VERIFIED_ON.isoformat()}" in text


# -- the signature ------------------------------------------------------------


def test_the_document_says_plainly_that_it_is_unsigned(text: str):
    """While it is unsigned, it has to *say so* at the top.

    A half-written compliance document that reads as complete is worse than a
    missing one: it makes the control look present. The status line is what
    stops that.
    """
    if UNFILLED not in text:
        return
    assert "STATUS: NOT YET SIGNED" in text, (
        "the statement has unfilled fields but does not say it is unsigned"
    )


def test_no_field_is_still_unfilled(text: str, repo: Path):
    """AC-AI-05.1's "signed statement".

    Expected to fail until the owner supplies the procurement facts - the Cloud
    project, the billing account, the alert recipients, the signature. Those are
    facts no test can obtain and no developer should invent.

    Recorded as an open item in `tests/spec/spec_defects.py` rather than skipped
    (`AC-FOUND-15.7` forbids a skipped test on an R1 path) and rather than
    weakened, which would defeat the purpose of having the check.
    """
    from tests.spec.spec_defects import UNSIGNED_COMPLIANCE_FIELDS

    # Only table *rows* whose value cell is the sentinel. The prose above
    # explains what `UNFILLED` means and mentions it twice; counting those would
    # make the ledger number a statement about the documentation rather than
    # about the facts still owed.
    remaining = [
        line.strip()
        for line in text.split("\n")
        if line.lstrip().startswith("|") and f"`{UNFILLED}`" in line
    ]

    assert len(remaining) == UNSIGNED_COMPLIANCE_FIELDS, (
        f"{len(remaining)} fields are still {UNFILLED}, and the ledger in "
        f"spec_defects.py expects {UNSIGNED_COMPLIANCE_FIELDS}. If fields were "
        "filled in, lower the number in the same commit; when it reaches 0, "
        "delete the ledger entry and this comparison becomes `== 0`."
    )


def test_the_signature_block_asks_for_what_matters(text: str):
    """A signature under a vague sentence commits nobody to anything. The block
    states which claims are being attested."""
    signature = text.split("## Signature", 1)[1]

    assert "procurement facts are true" in signature
    assert "budget alert exists" in signature
    assert "tier recorded" in signature
