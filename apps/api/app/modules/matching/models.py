"""Beanie documents for the matching module - persistence only.

`17-data-model.md` §2.8: `match_scores`.

**`rationale` is a sibling of `explain`, not a field inside it.** This is HR-3
and it is the single most important line in this file. The scorer reads
`explain` and `components`; it must be *structurally incapable* of reading
`rationale`, because a rationale is model-written prose and HR-11 forbids model
output from steering the program. If `rationale` sat inside `explain`, a future
scorer that took `explain` as its input would have the model's opinion in scope,
and the first person to use it would be doing something that looked entirely
reasonable.

The enforcement is a separate type, not a comment: `scoring.ScoreInput` in this
module carries `components` and `explain` and has no path to `rationale`, and
`tests/unit/test_scorer_input_type.py` asserts that by introspection
(`AC-DATA-02.5`).

Two other fields are stored rather than derived, each so that a score stays
explainable after its inputs have changed:

* **`profile_version`** - §2.5 stamps it here "so a score can be attributed to
  the profile that produced it". The user edits a skill and the score is still
  82; without this, nothing says which profile produced the 82.
* **`scorer_build`**, the git SHA of the scoring module, "so a score computed by
  a build with a bug is identifiable and re-computable". A bug found on Tuesday
  needs to answer "which rows are affected", and that question has no answer
  from the score alone.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from app.core.documents import UserOwnedDoc
from app.shared.timeutils import ensure_utc


class Band(StrEnum):
    """`match_scores.band` (§2.8).

    Derived from `score` and *stored*, so the feed can index on it: sorting a
    50,000-row candidate set by a computed band is a collection scan.
    §2.8's boundaries: strong >=80, good 65-79, partial 50-64, weak <50.
    """

    STRONG = "strong"
    GOOD = "good"
    PARTIAL = "partial"
    WEAK = "weak"


#: The boundaries, as data rather than as branches, so `band_for` and any
#: dashboard legend cannot disagree.
BAND_FLOORS: tuple[tuple[Band, int], ...] = (
    (Band.STRONG, 80),
    (Band.GOOD, 65),
    (Band.PARTIAL, 50),
    (Band.WEAK, 0),
)


def band_for(score: int) -> Band:
    """§2.8's four bands. One implementation, so a stored band and a rendered
    one are always the same band."""
    for band, floor in BAND_FLOORS:
        if score >= floor:
            return band
    return Band.WEAK


class SkillsBasis(StrEnum):
    """`explain.skills_basis` (§2.8).

    Five members, and explicitly **not** `jobs.skills_source`, which has three.
    §2.8: the job field "records where the requirement list came from, while the
    explain field additionally admits `semantic` (the embedding fallback used
    when the listing named no skills) and `none` (no skills and no embedding)".

    The distinction is what the user reads. "Matched on skills the employer
    listed" and "matched on overall similarity because the listing named no
    skills" are different claims, and collapsing them overstates the second.
    """

    LISTING = "listing"
    DICTIONARY = "dictionary"
    LLM = "llm"
    SEMANTIC = "semantic"
    NONE = "none"


class ExperienceVerdict(StrEnum):
    """`explain.experience.verdict` (§2.8, §7's registry)."""

    MEETS = "meets"
    EXCEEDS = "exceeds"
    BELOW = "below"
    UNKNOWN = "unknown"


class LocationVerdict(StrEnum):
    """`explain.location.verdict` (§2.8)."""

    MATCH = "match"
    REMOTE_OK = "remote_ok"
    RELOCATION_NEEDED = "relocation_needed"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


class SalaryVerdict(StrEnum):
    """`explain.salary.verdict` (§2.8).

    `UNKNOWN` is the commonest value in practice - most listings give no salary
    - and it is a distinct member rather than a null so the explain payload can
    say "the listing gives no salary" instead of showing nothing, which reads
    as a component that scored zero.
    """

    ABOVE = "above"
    WITHIN = "within"
    BELOW = "below"
    UNKNOWN = "unknown"


class SeniorityVerdict(StrEnum):
    """`explain.seniority.verdict` (§2.8)."""

    MATCH = "match"
    OVERQUALIFIED = "overqualified"
    UNDERQUALIFIED = "underqualified"
    UNKNOWN = "unknown"


class ScoreComponents(BaseModel):
    """`match_scores.components` (§2.8).

    Every component stored separately, so "why 82" is answerable by arithmetic
    rather than by rerunning the scorer against a profile that has since
    changed. `penalties` is a component and not a post-hoc adjustment for the
    same reason: a deduction nobody can see is a score nobody can explain.
    """

    skills: int = 0
    experience: int = 0
    title: int = 0
    location: int = 0
    salary: int = 0
    seniority: int = 0
    freshness: int = 0
    penalties: int = 0

    @property
    def total(self) -> int:
        return (
            self.skills
            + self.experience
            + self.title
            + self.location
            + self.salary
            + self.seniority
            + self.freshness
            + self.penalties
        )


class ExperienceExplain(BaseModel):
    required_min_years: float | None = None
    candidate_years: float | None = None
    verdict: ExperienceVerdict = ExperienceVerdict.UNKNOWN


class VerdictDetail(BaseModel):
    """A verdict plus the sentence the UI shows (§2.8).

    `detail` is generated by the scorer from its own inputs, not by a model.
    That is what lets `MATCH-04`'s explain panel render with the LLM rationale
    switched off - which is its default state (`FLAG_LLM_RATIONALE_ENABLED` is
    false) and the state the product has to be honest in.
    """

    verdict: str
    detail: str | None = None


class Explain(BaseModel):
    """`match_scores.explain` (§2.8) - the deterministic explanation.

    Contains no model output. Everything here is computed from the profile and
    the listing, which is why `MATCH-04` can show it whether or not any AI
    feature is enabled, and why the scorer may read it.
    """

    matched_required: list[str] = Field(default_factory=list)
    missing_required: list[str] = Field(default_factory=list)
    matched_nice: list[str] = Field(default_factory=list)
    missing_nice: list[str] = Field(default_factory=list)
    skills_basis: SkillsBasis = SkillsBasis.NONE
    experience: ExperienceExplain = Field(default_factory=ExperienceExplain)
    location: VerdictDetail = Field(
        default_factory=lambda: VerdictDetail(verdict=LocationVerdict.UNKNOWN.value)
    )
    salary: VerdictDetail = Field(
        default_factory=lambda: VerdictDetail(verdict=SalaryVerdict.UNKNOWN.value)
    )
    seniority: VerdictDetail = Field(
        default_factory=lambda: VerdictDetail(verdict=SeniorityVerdict.UNKNOWN.value)
    )
    red_flags: list[str] = Field(default_factory=list)


class MatchScore(UserOwnedDoc):
    """`match_scores` - score plus explanation per (user, job) (§2.8)."""

    job_id: str
    score: int = Field(default=0, ge=0, le=100)
    band: Band = Band.WEAK

    #: Which weight set produced this score. `MATCH-02` versions the weights so
    #: a re-weighting is a visible change rather than a silent re-ranking.
    weights_version: str = "w1"
    profile_version: int = 1
    #: The git SHA of the scoring module.
    scorer_build: str = "unknown"

    components: ScoreComponents = Field(default_factory=ScoreComponents)
    explain: Explain = Field(default_factory=Explain)
    embedding_sim: float | None = None

    # -- model output, deliberately outside `explain` (HR-3) ------------------
    # A sibling, never nested. The scorer's input type has no path to any of
    # these four fields, and a test asserts it.
    rationale: str | None = None
    rationale_model: str | None = None
    rationale_prompt_version: str | None = None
    rationale_at: datetime | None = None

    #: Null until R2 (`MATCH-06`).
    user_feedback: str | None = None
    computed_at: datetime | None = None

    @field_validator("rationale_at", "computed_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    class Settings:
        name = "match_scores"
        validate_on_save = True


DOCUMENTS = (MatchScore,)
