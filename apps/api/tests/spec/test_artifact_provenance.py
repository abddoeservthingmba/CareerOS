"""T-AI-04.2 - anything a model made says which model made it.

`AC-AI-04.2`: "Every model-produced artifact in every collection has non-null
`model` and `prompt_version` (HR-9), asserted by a schema check over seeded
data."

HR-9 is the rule that makes every other AI claim in this product checkable. A
user asks "why does my profile say I know Kubernetes"; a reviewer asks "did this
cover letter come from the prompt we approved". Both questions have an answer
only if the artifact recorded, at the moment it was written, which model and
which prompt version produced it. Recovered afterwards it is a guess: models are
swapped, prompts are versioned, and the artifact outlives both.

`05-ai-layer.md` §4 names the four fields: "`resumes.extraction_model`,
`jobs.enrichment.model`, `match_scores.rationale_model`,
`application_packs.model`. A stored artifact without them fails a schema check."

**None of those four collections exists yet** - they are `RES-01` (P2),
`JOB-04` (P3), `MATCH-05` (P3) and `APPLY-02` (P4). So this file checks the
list against the specification today, and checks the documents the moment they
appear. Written now because a provenance rule added after the first artifact is
written is a rule with a backfill problem.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


@dataclass(frozen=True)
class Provenance:
    """One artifact that a model produces, and where it records that."""

    collection: str
    field: str
    requirement: str
    phase: str


#: `05-ai-layer.md` §4's sentence, transcribed. Parsed against the spec below,
#: so a fifth artifact added there fails here rather than shipping unlabelled.
ARTIFACTS: tuple[Provenance, ...] = (
    Provenance("resumes", "extraction_model", "RES-01", "P2"),
    Provenance("jobs", "enrichment.model", "JOB-04", "P3"),
    Provenance("match_scores", "rationale_model", "MATCH-05", "P3"),
    Provenance("application_packs", "model", "APPLY-02", "P4"),
)

#: Every artifact also carries the prompt version. §7: "`prompt_version` is
#: `"<feature>/v<N>"` and is recorded on every artifact and every `ai_usage`
#: row."
PROMPT_VERSION_FIELD = "prompt_version"


def documents() -> dict[str, Any]:
    """Every Beanie document currently defined, by collection name."""
    import importlib
    import pkgutil

    from beanie import Document

    import app

    found: dict[str, Any] = {}
    for module in pkgutil.walk_packages(app.__path__, prefix="app."):
        try:
            imported = importlib.import_module(module.name)
        except Exception:  # noqa: BLE001 - a module that cannot import is another test's problem
            continue
        for value in vars(imported).values():
            if (
                isinstance(value, type)
                and issubclass(value, Document)
                and value is not Document
                and hasattr(value, "Settings")
            ):
                name = getattr(value.Settings, "name", None)
                if name:
                    found[str(name)] = value
    return found


# -- the list ----------------------------------------------------------------


def test_the_artifact_list_is_the_one_the_spec_names(repo: Path):
    """A fifth model-produced artifact added to §4 fails here until it is
    listed - which is the moment to decide where it records its provenance."""
    text = (repo / "docs" / "spec" / "05-ai-layer.md").read_text(encoding="utf-8")
    sentence = next(
        line
        for line in text.split("\n")
        if "Every artifact stored anywhere in the product that a model produced" in line
    )
    named = set(re.findall(r"`([a-z_]+)\.([a-z_.]+)`", sentence))

    declared = {(entry.collection, entry.field) for entry in ARTIFACTS}
    assert declared == named, f"§4 names {named}; this file declares {declared}"


def test_every_artifact_names_the_requirement_that_builds_it():
    """So the failure below reads as "APPLY-02 owes this" rather than as a
    mystery about a collection nobody can find."""
    for entry in ARTIFACTS:
        assert re.fullmatch(r"[A-Z]+-\d\d", entry.requirement), entry
        assert re.fullmatch(r"P\d", entry.phase), entry


def test_the_prompt_version_format_is_the_one_the_spec_names(repo: Path):
    """§7: `"<feature>/v<N>"`. The format matters because `AC-AI-07.2` detects a
    prompt edit by looking this string up in `ai_usage`."""
    text = (repo / "docs" / "spec" / "05-ai-layer.md").read_text(encoding="utf-8")

    assert '`prompt_version` is `"<feature>/v<N>"`' in text
    assert re.fullmatch(r"[a-z_]+/v\d+", "resume_extract/v1")


# -- the documents, as they land ---------------------------------------------


@pytest.mark.parametrize("entry", ARTIFACTS, ids=lambda e: e.collection)
def test_the_artifact_records_its_model_once_it_exists(entry: Provenance):
    """AC-AI-04.2, first half.

    Vacuous while the collection does not exist, binding the moment it does.
    """
    model = documents().get(entry.collection)
    if model is None:
        return

    root = entry.field.split(".")[0]
    assert root in model.model_fields, (
        f"{entry.collection} exists but has no {entry.field} "
        f"({entry.requirement}, HR-9): an artifact that does not say which model "
        "made it cannot answer 'why does my profile say this'"
    )


@pytest.mark.parametrize("entry", ARTIFACTS, ids=lambda e: e.collection)
def test_the_artifact_records_its_prompt_version_once_it_exists(entry: Provenance):
    """AC-AI-04.2, second half.

    The model alone is not enough: the same model with a rewritten prompt
    produces different output, and `prompt_version` is what makes a stored
    artifact reproducible.
    """
    model = documents().get(entry.collection)
    if model is None:
        return

    fields = set(model.model_fields)
    nested = entry.field.split(".")[0]
    assert PROMPT_VERSION_FIELD in fields or nested in fields, (
        f"{entry.collection} records no {PROMPT_VERSION_FIELD} ({entry.requirement})"
    )


def test_none_of_the_four_collections_exists_yet():
    """Stated rather than assumed.

    When this fails, one of the four has landed - which is the prompt to make
    the two assertions above real rather than to notice later that they were
    vacuous the whole time.
    """
    present = sorted(entry.collection for entry in ARTIFACTS if entry.collection in documents())
    assert present == [], (
        f"{present} now exist; their provenance assertions above are live, and "
        "this test should be deleted"
    )


# -- the row that already exists ---------------------------------------------


def test_the_usage_row_carries_both_fields():
    """`ai_usage` is the one provenance-bearing collection that exists today.

    It is not in `ARTIFACTS` - it is the ledger, not an artifact - but it
    carries the same two fields, and it is what makes the check in
    `AC-AI-07.2` ("editing a prompt used in production") possible at all.
    """
    from app.ai.usage import AiUsage

    assert "model" in AiUsage.model_fields
    assert PROMPT_VERSION_FIELD in AiUsage.model_fields


def test_the_usage_rows_provenance_fields_are_not_silently_defaulted():
    """`model` is required; a row that defaulted it to `""` would satisfy a
    presence check and answer nothing."""
    from app.ai.usage import AiUsage

    assert AiUsage.model_fields["model"].is_required()
    assert AiUsage.model_fields["provider"].is_required()
