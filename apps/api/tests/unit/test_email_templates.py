"""T-FOUND-16.1 - every R1 template renders in both forms.

`AC-FOUND-16.1`: "Every R1 template renders in HTML and plain text, and a
golden-file test catches unintended changes." Shared with `AC-NOTIF-02.1`.

The golden files live in `tests/fixtures/email/`. Their job is to make an
accidental copy change visible in review: a reset email that stops saying the
link expires in 60 minutes is a support ticket, not a diff nobody reads.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.infra.email.templates import R1_TEMPLATES

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "email"

# One representative payload per template. Values are obviously fake so a golden
# file can never contain something that looks like a real user's data.
DATA: dict[str, dict[str, object]] = {
    "verify_email": {"product": "JobPilot", "verify_url": "https://example.test/verify/TOKEN"},
    "registration_attempted": {
        "product": "JobPilot",
        "reset_url": "https://example.test/reset/TOKEN",
    },
    "password_reset": {"product": "JobPilot", "reset_url": "https://example.test/reset/TOKEN"},
    "password_changed": {"product": "JobPilot", "changed_at": "6 September 2026, 14:05 IST"},
    "deletion_requested": {
        "product": "JobPilot",
        "delete_on": "13 September 2026",
        "cancel_url": "https://example.test/cancel/TOKEN",
    },
    "deletion_completed": {"product": "JobPilot"},
}


@pytest.mark.parametrize("template", R1_TEMPLATES, ids=lambda t: t.template_id)
def test_every_template_renders_both_forms(template):
    """AC-FOUND-16.1, first half."""
    subject, html, text = template.render(DATA[template.template_id])

    assert subject.strip(), "a message with no subject reads as spam"
    assert html.strip().startswith("<!doctype html>")
    assert text.strip(), "text-only clients and spam scoring both need this"
    assert "{{" not in subject + html + text


@pytest.mark.parametrize("template", R1_TEMPLATES, ids=lambda t: t.template_id)
def test_the_rendering_matches_its_golden_file(template):
    """AC-FOUND-16.1, second half.

    Set `UPDATE_EMAIL_GOLDEN=1` to rewrite them after a deliberate copy change.
    """
    subject, html, text = template.render(DATA[template.template_id])
    actual = f"SUBJECT: {subject}\n\n--- TEXT ---\n{text}\n\n--- HTML ---\n{html}\n"
    path = GOLDEN / f"{template.template_id}.txt"

    if os.environ.get("UPDATE_EMAIL_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8", newline="")

    assert path.is_file(), f"{path.name} is missing; run with UPDATE_EMAIL_GOLDEN=1 to create it"
    assert path.read_text(encoding="utf-8") == actual, (
        f"{template.template_id} renders differently than its golden file. If the "
        "copy change is deliberate, re-run with UPDATE_EMAIL_GOLDEN=1 and review "
        "the diff."
    )


@pytest.mark.parametrize("template", R1_TEMPLATES, ids=lambda t: t.template_id)
def test_the_product_name_is_never_a_literal(template):
    """`README.md` §5 / `AC-FOUND-02.4` - D1 is unsettled, so the name is
    configuration everywhere, including in email copy."""
    source = template.subject + template.html + template.text
    assert "JobPilot" not in source, (
        "interpolate {{product}} from PRODUCT_NAME rather than naming the product"
    )


@pytest.mark.parametrize("template", R1_TEMPLATES, ids=lambda t: t.template_id)
def test_no_template_carries_another_persons_data(template):
    """§16 - "the only personal datum in an email is the recipient's own"."""
    forbidden = ("job_description", "resume_text", "other_user", "contact_email", "phone")
    for key in template.required:
        assert key not in forbidden, f"{template.template_id} would carry {key}"


def test_the_reset_email_states_its_expiry():
    """`AUTH-05` gives the token a 60-minute life; a user who does not know that
    files a support ticket instead of asking for a new link."""
    _, html, text = R1_TEMPLATES[2].render(DATA["password_reset"])
    assert "60 minutes" in text and "60 minutes" in html


def test_the_password_changed_email_mentions_no_password_material():
    """AC-AUTH-05.5."""
    _, html, text = next(t for t in R1_TEMPLATES if t.template_id == "password_changed").render(
        DATA["password_changed"]
    )
    for body in (html, text):
        lowered = body.lower()
        assert "your new password is" not in lowered
        assert "password:" not in lowered


def test_the_deletion_email_states_the_clock_and_the_backup_window():
    """`AUTH-07` is a legal obligation with a 7-day clock, and
    `16-security-and-compliance.md` §4 requires the 14-day backup retention to
    be disclosed."""
    _, html, text = next(t for t in R1_TEMPLATES if t.template_id == "deletion_requested").render(
        DATA["deletion_requested"]
    )
    for body in (html, text):
        assert "13 September 2026" in body
        assert "14 days" in body
