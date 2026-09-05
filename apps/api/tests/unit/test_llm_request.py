"""T-AI-01.2 - the request type (`05-ai-layer.md` §1).

Shared with `T-RES-05.1` (`AC-RES-05.1`), which is the structural half of HR-8:
the file the user uploaded stays ours because `LLMRequest` has nowhere to put
one.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.ai.base import Feature, LLMRequest, Message

# Any of these on `LLMRequest` would be a way to send a file to a provider.
FILE_BEARING_NAMES = (
    "file",
    "files",
    "attachment",
    "attachments",
    "bytes",
    "content_bytes",
    "blob",
    "data",
    "upload",
    "url",
    "urls",
    "file_url",
    "storage_url",
    "r2_key",
    "path",
    "document",
    "image",
    "media",
    "part",
    "parts",
)

FILE_BEARING_TYPES = (bytes, bytearray, memoryview)


def valid() -> LLMRequest:
    return LLMRequest(
        feature=Feature.RESUME_EXTRACT,
        system="Extract the profile.",
        messages=(Message(role="user", content="..."),),
        prompt_version="resume_extract/v1",
    )


def test_feature_is_required_and_must_be_a_member():
    """AC-AI-01.2."""
    with pytest.raises(TypeError):
        LLMRequest(system="no feature")  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="Feature member"):
        LLMRequest(feature="resume_extract", system="a string, not the enum")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Feature member"):
        LLMRequest(feature="not_a_feature", system="...")  # type: ignore[arg-type]


def test_the_feature_enum_matches_the_budget_matrix(repo):
    """AC-AI-03.12 - one row per member, and no member without a row."""
    matrix = (repo / "docs" / "spec" / "ai-budget.yaml").read_text(encoding="utf-8")
    body = matrix.split("features:", 1)[1].split("invariants:", 1)[0]
    rows = {
        line.strip().rstrip(":")
        for line in body.split("\n")
        if line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":")
    }
    assert rows == {f.value for f in Feature}


def test_no_field_can_carry_a_file():
    """AC-RES-05.1 / HR-8 - by introspection, so adding one fails here."""
    fields = {f.name: f for f in dataclasses.fields(LLMRequest)}

    named = sorted(set(fields) & set(FILE_BEARING_NAMES))
    assert named == [], f"LLMRequest gained a file-bearing field: {named}"

    for name, spec in fields.items():
        annotation = str(spec.type)
        for forbidden in FILE_BEARING_TYPES:
            assert forbidden.__name__ not in annotation, (
                f"LLMRequest.{name} is typed {annotation}, which can carry file bytes"
            )


def test_the_request_is_frozen():
    """A prompt that can be mutated after construction cannot be attributed to
    the `prompt_version` recorded beside its output (HR-9)."""
    request = valid()
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.system = "something else"  # type: ignore[misc]


def test_untrusted_is_a_mapping_of_text():
    """§6 - untrusted content travels here, never concatenated into `system`."""
    request = LLMRequest(
        feature=Feature.JOB_ENRICH,
        system="Enrich.",
        untrusted={"job_description": "We need a Python developer."},
    )
    assert request.untrusted["job_description"].startswith("We need")
    assert "Python developer" not in request.system


def test_out_of_range_parameters_are_refused():
    with pytest.raises(ValueError, match="temperature"):
        LLMRequest(feature=Feature.JOB_ENRICH, system="x", temperature=5.0)
    with pytest.raises(ValueError, match="max_output_tokens"):
        LLMRequest(feature=Feature.JOB_ENRICH, system="x", max_output_tokens=0)


def test_every_feature_has_a_tier_or_is_an_embedding():
    """§5.2 - "`fast` for extraction, enrichment, rationale, follow-up drafts and
    answer suggestions; `quality` for pack generation"."""
    from app.ai.base import Tier

    assert Tier.QUALITY.value == "quality"
    assert {f for f in Feature if f.value.startswith("embed_")} == {
        Feature.EMBED_PROFILE,
        Feature.EMBED_JOB,
        Feature.EMBED_QUESTION,
    }
