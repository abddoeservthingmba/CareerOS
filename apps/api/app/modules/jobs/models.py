"""Beanie documents for the jobs module - persistence only.

`17-data-model.md` §2.6 and §2.7: `jobs`, `raw_listings`, `connector_runs`,
`user_job_actions`. (`saved_searches` is R2 and therefore absent.)

§2.6 records four changes from BRD v1.0 Appendix A, each with a reason. Three
of them are the reason a field here is stored rather than computed, and getting
any of them wrong is a bug that only shows up under a merge or a re-crawl:

* **`apply_url` lives inside `source_refs[]`, not at the top level.** After a
  cross-source merge there is more than one apply URL, and the user must be able
  to apply via the source they trust. A single top-level `apply_url` silently
  picks one. `primary_source` names the default without destroying the others.
* **`simhash` and `unseen_runs` are stored.** Dedup and staleness both need them
  at query time; recomputing a simhash in order to compare it is pointless.
* **`revision` is stored.** Ingestion increments it when a description changes
  materially and re-runs enrichment and embedding. v2.0 asserted that behaviour
  against a field the schema never declared.

And one that is about honesty rather than mechanics: **`skills_source` and
`experience_years.source`** tell the matcher - and the user - whether a
"required skill" came from the employer's own structured field or from our
inference. That changes how confidently the explain payload may phrase it, and
a missing provenance field means the UI has to guess, which it will do
generously.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator
from pymongo import ASCENDING, DESCENDING, TEXT, IndexModel

from app.core.documents import BaseDoc, Provenance, StoredEmbedding, UserOwnedDoc
from app.shared.enums import MoneyPeriod, RemoteMode
from app.shared.timeutils import ensure_utc

#: §2.6 / `05-ai-layer.md` §6: a job description is capped before it is stored
#: and before it is rendered into a prompt. The same number in both places.
DESCRIPTION_CAP = 8_000

#: §2.7 and `DATA-05`: `raw_listings` is kept for 30 days. Config as a constant
#: rather than a literal in the index, so the retention table and the index
#: cannot disagree about the number.
RAW_LISTING_TTL_DAYS = 30


class JobStatus(StrEnum):
    """`jobs.status` (§2.6).

    `MERGED_INTO` is a tombstone, not a deletion: a `match_scores` row or an
    `applications` row may already point at the id that lost a dedup merge, and
    a hard delete would break both. The row survives and forwards.
    """

    ACTIVE = "active"
    EXPIRED = "expired"
    FLAGGED = "flagged"
    MERGED_INTO = "merged_into"


class Seniority(StrEnum):
    """`jobs.seniority` (§2.6). The same members as `profiles.seniority`,
    because the matcher compares the two directly."""

    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    PRINCIPAL = "principal"
    EXECUTIVE = "executive"
    UNKNOWN = "unknown"


class EmploymentType(StrEnum):
    """`jobs.employment_type` (§2.6)."""

    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERNSHIP = "internship"
    FREELANCE = "freelance"
    UNKNOWN = "unknown"


class SalarySource(StrEnum):
    """`jobs.salary.source` (§2.6). Null when there is no salary at all.

    The distinction matters to the user: `LISTING` means the employer said it,
    `PARSED` means we found it in prose and could be wrong. Presenting the
    second as the first is how a candidate walks into a conversation quoting a
    number nobody offered.
    """

    LISTING = "listing"
    PARSED = "parsed"


class SkillsSource(StrEnum):
    """`jobs.skills_source` (§2.6).

    Three members. Deliberately *not* the same enum as
    `match_scores.explain.skills_basis`, which has five: this field records
    where the requirement list came from, and that one additionally admits
    `semantic` (the embedding fallback) and `none`. §2.8 records that v2.0 gave
    `skills_basis` three members lining up with neither case.
    """

    LISTING = "listing"
    DICTIONARY = "dictionary"
    LLM = "llm"


class QualityFlag(StrEnum):
    """`jobs.quality_flags` (§2.6, §7's registry).

    Flags, not a status: a listing can be several of these at once, and none of
    them removes it from the feed on its own. `PAY_TO_APPLY` and
    `SUSPICIOUS_CONTACT` are the two that feed `explain.red_flags`.
    """

    NO_SALARY = "no_salary"
    VAGUE_DESCRIPTION = "vague_description"
    NO_SKILLS_LISTED = "no_skills_listed"
    STALE_POSTING = "stale_posting"
    SUSPICIOUS_CONTACT = "suspicious_contact"
    PAY_TO_APPLY = "pay_to_apply"


class UserJobActionKind(StrEnum):
    """`user_job_actions.action` (§2.7)."""

    HIDDEN = "hidden"
    NOT_INTERESTED = "not_interested"
    REPORTED = "reported"


class NotInterestedReason(StrEnum):
    """`user_job_actions.reason` (§2.7).

    §2.7: "`reason` from a fixed enum plus optional free text, because a
    free-text-only reason is useless as a matching signal". `OTHER` carries the
    free text; everything else is countable.
    """

    SALARY_TOO_LOW = "salary_too_low"
    LOCATION = "location"
    SENIORITY_MISMATCH = "seniority_mismatch"
    NOT_MY_FIELD = "not_my_field"
    COMPANY = "company"
    ALREADY_APPLIED = "already_applied"
    SCAM_SUSPECTED = "scam_suspected"
    OTHER = "other"


class ConnectorRunStatus(StrEnum):
    """`connector_runs.status` (§2.7)."""

    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class CircuitState(StrEnum):
    """`connector_runs.circuit_state` (§2.7, `06-connectors.md` §4)."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class SourceRef(BaseModel):
    """One source's view of a listing (§2.6).

    A list of these rather than flat fields is the whole point of change 1: a
    merged job carries every source that described it, each with its own apply
    URL and its own attribution string. `attribution` is stored per source
    because a terms-of-use requirement to display "Jobs by Adzuna" belongs to
    the source, not to the merged row.
    """

    source: str
    external_id: str
    url: str | None = None
    apply_url: str | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    attribution: str | None = None

    @field_validator("first_seen_at", "last_seen_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None


class Company(BaseModel):
    """§2.6. `normalized` is the dedup input; `name` is what the source said."""

    name: str
    normalized: str
    url: str | None = None
    logo_url: str | None = None
    size: str | None = None
    industry: str | None = None


class JobLocation(BaseModel):
    """§2.6.

    `raw` is never overwritten - the UI shows it, and a normalizer bug is
    diagnosable only if the input survives. `remote_regions` exists because
    "remote" is almost never global: a remote-in-India role is onsite-equivalent
    for a candidate in Berlin, and scoring it as remote is a wrong match the
    user only discovers at the application stage.
    """

    raw: str
    city: str | None = None
    region: str | None = None
    country: str | None = None
    remote_mode: RemoteMode = RemoteMode.UNKNOWN
    remote_regions: list[str] = Field(default_factory=list)


class SalaryRange(BaseModel):
    """§2.6. Minor units, integers.

    `CLAUDE.md`: "Money is a minor-unit integer, never a float." A salary is
    quoted back to the user and sometimes into a cover letter; floating-point
    drift in that number is a mistake the user sends to an employer.
    """

    min: int | None = None
    max: int | None = None
    currency: str | None = None
    period: MoneyPeriod | None = None
    source: SalarySource | None = None


class ExperienceRequirement(BaseModel):
    """§2.6. `source` distinguishes the employer's structured field from our
    regex over prose."""

    min: float | None = None
    max: float | None = None
    source: SkillsSource | None = None


class FlagReport(BaseModel):
    """User reports against a listing (§2.6)."""

    count: int = 0
    reasons: list[str] = Field(default_factory=list)
    reviewed_at: datetime | None = None

    @field_validator("reviewed_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None


class Job(BaseDoc):
    """`jobs` - the canonical, deduplicated listing (§2.6).

    Not user-owned: a job belongs to nobody, which is why `BaseDoc` is right
    here and why every user-specific fact about a job (`hidden`, a score, an
    application) lives in a different collection keyed by `(user_id, job_id)`.
    """

    #: `sha1(norm_company|norm_title|norm_locus)`. Unique - exact dedup.
    dedup_key: str
    #: A u64 as a string. Stored because fuzzy dedup compares it at query time.
    simhash: str | None = None

    source_refs: list[SourceRef] = Field(default_factory=list)
    primary_source: str | None = None

    title: str
    title_family: str | None = None
    seniority: Seniority = Seniority.UNKNOWN
    company: Company
    location: JobLocation
    employment_type: EmploymentType = EmploymentType.UNKNOWN
    salary: SalaryRange = Field(default_factory=SalaryRange)

    description_text: str = Field(default="", max_length=DESCRIPTION_CAP)
    description_html_sanitized: str = ""

    required_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    skills_source: SkillsSource | None = None
    experience_years: ExperienceRequirement = Field(default_factory=ExperienceRequirement)
    education_required: str | None = None
    visa_sponsorship: bool | None = None
    apply_deadline: datetime | None = None

    posted_at: datetime | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    #: Consecutive ingestion runs in which no source mentioned this listing.
    #: `JOB-08` expires it at a threshold rather than on first absence, because
    #: one source failing for an hour is not a job being withdrawn.
    unseen_runs: int = 0
    expired_at: datetime | None = None

    #: Incremented when the description changes materially (simhash distance
    #: >6), which re-runs enrichment and embedding.
    revision: int = 1
    status: JobStatus = JobStatus.ACTIVE
    #: Set when `status` is `merged_into`, naming the surviving job.
    merged_into: str | None = None

    enrichment: Provenance | None = None
    embedding: StoredEmbedding | None = None

    quality_flags: list[QualityFlag] = Field(default_factory=list)
    flagged: FlagReport = Field(default_factory=FlagReport)

    @field_validator("apply_deadline", "posted_at", "first_seen_at", "last_seen_at", "expired_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    class Settings:
        name = "jobs"
        validate_on_save = True
        indexes = [
            IndexModel([("dedup_key", ASCENDING)], name="dedup_key", unique=True),
            # Unique multikey: one source's id maps to one job, which is what
            # makes ingestion an upsert rather than an insert-and-hope.
            IndexModel(
                [
                    ("source_refs.source", ASCENDING),
                    ("source_refs.external_id", ASCENDING),
                ],
                name="source_ref",
                unique=True,
            ),
            IndexModel([("status", ASCENDING), ("posted_at", DESCENDING)], name="status_posted"),
            # §3 writes this row as `title_family, location.country,
            # remote_mode, status`. `remote_mode` is abbreviated there; the
            # field is `location.remote_mode` (§2.6), and the real path is what
            # is declared - an index on a field that does not exist is an index
            # the planner never chooses, and it looks identical to a correct one
            # in `listIndexes`.
            IndexModel(
                [
                    ("title_family", ASCENDING),
                    ("location.country", ASCENDING),
                    ("location.remote_mode", ASCENDING),
                    ("status", ASCENDING),
                ],
                name="candidate_set",
            ),
            # `JOB-06`'s search. Weights 10/5/1: a title match is what the user
            # meant, a company match is usually what they meant, and a
            # description match is a coincidence often enough that ranking it
            # equally buries the first two.
            IndexModel(
                [
                    ("title", TEXT),
                    ("company.name", TEXT),
                    ("description_text", TEXT),
                ],
                name="job_search",
                weights={"title": 10, "company.name": 5, "description_text": 1},
            ),
            # Fuzzy-dedup shortlist. Stored rather than recomputed: comparing a
            # simhash requires having it, and 50k recomputations per run is the
            # cost of not storing one 8-byte string.
            IndexModel([("simhash", ASCENDING)], name="simhash"),
            IndexModel(
                [("primary_source", ASCENDING), ("last_seen_at", ASCENDING)],
                name="staleness_sweep",
            ),
        ]


class RawListing(BaseDoc):
    """`raw_listings` - untouched connector payloads, TTL 30 d (§2.7).

    Kept because a normalization bug is otherwise undiagnosable: the only
    evidence of what a source actually sent is what a source actually sent.
    TTL rather than forever because it is the largest collection by volume and
    Atlas M0 has 512 MB (`DATA-05`, `DATA-06`).
    """

    connector: str
    external_id: str
    run_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    fetched_at: datetime | None = None

    @field_validator("fetched_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    class Settings:
        name = "raw_listings"
        validate_on_save = True
        indexes = [
            # TTL 30 d (§2.7, `DATA-05`). The largest collection by volume, and
            # Atlas M0 has 512 MB - so the retention rule is an index rather
            # than a cron, which cannot fall behind.
            IndexModel(
                [("fetched_at", ASCENDING)],
                name="fetched_at_ttl",
                expireAfterSeconds=RAW_LISTING_TTL_DAYS * 86_400,
            ),
            IndexModel(
                [("connector", ASCENDING), ("external_id", ASCENDING)],
                name="connector_external_id",
            ),
        ]


class RunError(BaseModel):
    """One failure inside a run (§2.7). A code, never a provider message -
    a message can echo a payload (`AC-FOUND-14.5`)."""

    stage: str
    code: str
    at: datetime | None = None

    @field_validator("at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None


class ConnectorRun(BaseDoc):
    """`connector_runs` - per-run ingestion statistics (§2.7).

    Every counter is stored separately rather than derived, because the useful
    question is which of them changed: `fetched` steady with `new` at zero is a
    working connector against an exhausted query set, and `normalize_failures`
    rising is a source that changed its format. A single "count" would hide
    both.
    """

    connector: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    queries: int = 0
    fetched: int = 0
    new: int = 0
    updated: int = 0
    deduped_into_existing: int = 0
    normalize_failures: int = 0
    errors: list[RunError] = Field(default_factory=list)
    status: ConnectorRunStatus = ConnectorRunStatus.RUNNING
    circuit_state: CircuitState = CircuitState.CLOSED

    @field_validator("started_at", "finished_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    class Settings:
        name = "connector_runs"
        validate_on_save = True
        indexes = [
            IndexModel(
                [("connector", ASCENDING), ("started_at", DESCENDING)],
                name="connector_recent",
            ),
        ]


class UserJobAction(UserOwnedDoc):
    """`user_job_actions` - hide / not-interested / report (§2.7).

    User-owned and keyed `(user_id, job_id, action)`, which is what makes
    hiding idempotent: pressing hide twice is one row, not two.
    """

    job_id: str
    action: UserJobActionKind
    reason: NotInterestedReason | None = None
    #: Only meaningful with `reason == OTHER`. Free text is stored so a person
    #: can read it; it is never counted, because counting free text is how a
    #: dashboard invents categories.
    reason_text: str | None = None
    at: datetime | None = None

    @field_validator("at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    class Settings:
        name = "user_job_actions"
        validate_on_save = True
        indexes = [
            # Unique, which is the whole idempotency mechanism: pressing hide
            # twice is one row, not two, and the second press is a duplicate-key
            # error the service treats as success.
            IndexModel(
                [("user_id", ASCENDING), ("job_id", ASCENDING), ("action", ASCENDING)],
                name="user_job_action",
                unique=True,
            ),
        ]


DOCUMENTS = (Job, RawListing, ConnectorRun, UserJobAction)
