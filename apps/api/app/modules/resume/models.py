"""Beanie documents for the resume module - persistence only.

`17-data-model.md` §2.4: `resumes`.

Two things in this shape are the resolution of a v2.0 defect and a capacity
constraint, and both are worth reading before changing anything here.

**One `status` enum, not a `status` and a `stage`.** §2.4: v2.0 carried both,
"whose members were the same four steps under different names (`extracting` vs
`extracting_text`), which is how a client ends up switching on a value the
server never sends". The SSE event carries `status` plus `progress`. There is
no `stage` field, and adding one back would recreate the bug.

**The extracted text lives in R2, not here.** §2.4: "a 5 MB resume's text can
approach Mongo's 16 MB document ceiling once paired with the extraction, and
Atlas M0 is 512 MB total". Mongo keeps `text_chars` and a 500-character
`text_excerpt` for admin debugging only. HR-8 is why the *file* never leaves
our infrastructure; this is why its *text* does not live in the database.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.core.documents import UserOwnedDoc

#: §2.4: "a 500-character `text_excerpt` for admin debugging only". A cap
#: rather than a convention, because an excerpt that grew would reintroduce the
#: document-size problem the R2 split exists to solve.
TEXT_EXCERPT_CHARS = 500


class ResumeStatus(StrEnum):
    """`resumes.status` (§2.4). The one enum, five members.

    Ordered as the pipeline runs, so a comparison against the list reads as
    progress. `failed` is terminal and carries `error`.
    """

    UPLOADED = "uploaded"
    EXTRACTING_TEXT = "extracting_text"
    STRUCTURING = "structuring"
    READY = "ready"
    FAILED = "failed"


class TextSource(StrEnum):
    """`resumes.text_source` (§2.4). `ocr` is reachable only in R2 (`RES-02b`).

    §2.4: "The extraction prompt is told which, because OCR input needs
    different handling of garbled tokens." A prompt that cannot tell OCR output
    from a text layer treats scanning artefacts as the candidate's own wording.
    """

    PDF = "pdf"
    DOCX = "docx"
    OCR = "ocr"


class QualityFeedback(BaseModel):
    """One piece of résumé quality advice (§2.4). Empty until R2 (`RES-04`)."""

    code: str
    message: str
    severity: str = "info"


class Resume(UserOwnedDoc):
    """`resumes` - uploaded files and extraction state (§2.4)."""

    label: str = "Default"
    #: `u/{user_id}/resumes/{resume_id}.pdf`. A key, never a URL, and never
    #: anything the user supplied (`DATA-04`).
    r2_key: str | None = None
    mime: str | None = None
    size_bytes: int = 0
    #: Of the uploaded bytes, so a re-upload of the same file is detectable
    #: without re-running the pipeline.
    sha256: str | None = None

    status: ResumeStatus = ResumeStatus.UPLOADED
    progress: int = Field(default=0, ge=0, le=100)

    text_chars: int = 0
    text_source: TextSource | None = None
    text_r2_key: str | None = None
    #: Admin debugging only, capped. Never shown to a user and never sent to a
    #: model - the model gets the full text from R2.
    text_excerpt: str | None = Field(default=None, max_length=TEXT_EXCERPT_CHARS)

    #: `ProfileExtraction`, whose shape belongs to `04-resume-pipeline.md` §4.
    #: Typed loosely here on purpose: the structured shape is that
    #: requirement's to define, and duplicating it would create the second
    #: definition `DATA-07` exists to prevent.
    extraction: dict[str, Any] | None = None
    #: HR-9's pair. Not a `Provenance` object because §2.4 names the two fields
    #: flat, and the schema snapshot compares field names against the spec.
    extraction_model: str | None = None
    prompt_version: str | None = None

    quality_feedback: list[QualityFeedback] = Field(default_factory=list)
    is_default: bool = True
    error: str | None = None

    class Settings:
        name = "resumes"
        validate_on_save = True
        indexes = [
            IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_recent"),
            # Partial on `is_default: true`: one row per user matches, so the
            # index is a handful of entries rather than one per resume, and the
            # default lookup is a single seek.
            IndexModel(
                [("user_id", ASCENDING), ("is_default", ASCENDING)],
                name="user_default",
                partialFilterExpression={"is_default": True},
            ),
        ]


DOCUMENTS = (Resume,)
