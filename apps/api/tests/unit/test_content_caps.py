"""T-AI-06.6 - untrusted content is capped before rendering.

`AC-AI-06.6`: "Content exceeding the cap is truncated before rendering, and the
truncation is recorded on the artifact."

The caps come from `17-data-model.md` §6, where they are a storage decision as
much as a prompt one: 8,000 characters of description is what makes 25,000 jobs
fit in Atlas M0.
"""

from __future__ import annotations

from app.ai.untrusted import (
    DEFAULT_CAP,
    JOB_DESCRIPTION_CAP,
    RESUME_TEXT_CAP,
    cap_for,
    render,
    truncate,
)


def test_the_caps_are_the_ones_the_spec_states():
    assert JOB_DESCRIPTION_CAP == 8_000
    assert RESUME_TEXT_CAP == 30_000
    assert cap_for("job_description") == 8_000
    assert cap_for("resume_text") == 30_000
    # An unknown slot gets the conservative cap rather than no cap.
    assert cap_for("something_new") == DEFAULT_CAP


def test_content_under_the_cap_is_untouched():
    text = "a paragraph " * 10
    result, was_cut = truncate("job_description", text)
    assert result == text
    assert was_cut is False


def test_content_over_the_cap_is_truncated():
    text = "x" * (JOB_DESCRIPTION_CAP + 500)
    result, was_cut = truncate("job_description", text)
    assert was_cut is True
    assert len(result) <= JOB_DESCRIPTION_CAP


def test_truncation_prefers_a_whitespace_boundary():
    """A prompt cut mid-word reads as corruption to the model."""
    text = ("word " * 3000)[: JOB_DESCRIPTION_CAP + 200]
    result, was_cut = truncate("job_description", text)
    assert was_cut is True
    assert not result.endswith("wor")
    assert result == result.rstrip()


def test_truncation_is_recorded_on_the_render():
    """AC-AI-06.6 - "the truncation is recorded on the artifact"."""
    rendered = render(
        {
            "job_description": "x" * (JOB_DESCRIPTION_CAP + 1),
            "resume_text": "short",
        }
    )
    assert rendered.was_truncated
    assert rendered.truncated == ("job_description",)


def test_nothing_is_recorded_when_nothing_is_cut():
    rendered = render({"job_description": "short", "resume_text": "also short"})
    assert rendered.was_truncated is False
    assert rendered.truncated == ()


def test_the_rendered_block_respects_the_cap():
    """The cap must bind on what reaches the provider, not only on what is
    stored - the prompt is what costs money and what carries the payload."""
    rendered = render({"job_description": "x" * (JOB_DESCRIPTION_CAP * 3)})
    assert rendered.text.count("x") <= JOB_DESCRIPTION_CAP
