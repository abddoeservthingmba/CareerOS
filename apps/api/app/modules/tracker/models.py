"""Beanie documents for the tracker module - persistence only.

`17-data-model.md` §2.10: `applications`.

Three decisions, each recorded in §2.10 and each easy to undo without noticing:

**Exactly one of `job_id` and `manual_job` is set** (`TRACK-05`). A user tracking
an application they found somewhere we never crawled is a first-class case, not
an edge one - it is most of early usage. Both fields set would mean two
different jobs; neither set would mean an application to nothing. `AC-DATA-02.3`
enforces it at write time *and* with a JSON-schema validator on the collection,
because a rule held only in application code is a rule a migration script does
not know about.

**`listing_expired` is a flag, not a status** (`TRACK-01`). An expired listing
does not change where the application sits on the board. Making it a status
would move a card the user is actively interviewing for into a column meaning
"the posting went away", which is not a thing that happened to their
application.

**`status_history` is append-only and records who moved it.** The board is the
product's memory of a months-long process; "when did I apply" and "how long has
this been in screening" are the questions it exists to answer, and a single
`status` field cannot answer either.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.core.documents import UserOwnedDoc
from app.core.ids import new_id
from app.shared.enums import MoneyPeriod
from app.shared.timeutils import ensure_utc


class ApplicationStatus(StrEnum):
    """`applications.status` (§2.10). Ten members, in board order.

    `GHOSTED` is a real member and not a synonym for `REJECTED`: silence is the
    commonest outcome and it is the one a follow-up reminder acts on. Folding it
    into `REJECTED` would tell the user they were turned down by an employer who
    simply never replied.
    """

    SAVED = "saved"
    PREPARING = "preparing"
    APPLIED = "applied"
    SCREENING = "screening"
    INTERVIEW = "interview"
    OFFER = "offer"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    GHOSTED = "ghosted"


class AppliedVia(StrEnum):
    """`applications.applied_via` (§2.10).

    `EXTENSION` exists as a member but nothing writes it in R1: HR-1 forbids
    submitting anything to a third-party site, so the extension fills a form the
    user then submits themselves. The member records *how the user got there*,
    never that we applied for them.
    """

    EXTERNAL_LINK = "external_link"
    MANUAL = "manual"
    EXTENSION = "extension"


class ApplicationSource(StrEnum):
    """`applications.source` (§2.10).

    §2.10: it "tells you later whether matching was actually the thing driving
    applications" - which is the one metric that says whether the product's
    central premise works.
    """

    MATCH = "match"
    SEARCH = "search"
    MANUAL = "manual"


class InterviewType(StrEnum):
    """`interviews.type` (§7's registry, §2.10)."""

    SCREENING = "screening"
    TECHNICAL = "technical"
    SYSTEM_DESIGN = "system_design"
    BEHAVIOURAL = "behavioural"
    HR = "hr"
    TAKE_HOME = "take_home"
    PANEL = "panel"
    FINAL = "final"
    OTHER = "other"


class InterviewOutcome(StrEnum):
    """`interviews.outcome` (§2.10). Null until the round has happened."""

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class SalaryLogKind(StrEnum):
    """`salary_log.kind` (§2.10).

    A log rather than a pair of numbers because a negotiation is a sequence, and
    the useful artefact afterwards is what was said in what order. A single
    "expected" and "offered" field loses the counter-offer, which is the part
    the user wants to remember next time.
    """

    EXPECTATION_GIVEN = "expectation_given"
    OFFER_RECEIVED = "offer_received"
    COUNTER_MADE = "counter_made"
    REVISED_OFFER = "revised_offer"
    ACCEPTED = "accepted"


class DocumentKind(StrEnum):
    """`applications.documents[].kind` (§2.10)."""

    RESUME = "resume"
    COVER_LETTER = "cover_letter"
    PORTFOLIO = "portfolio"
    OFFER_LETTER = "offer_letter"
    OTHER = "other"


class ManualJob(BaseModel):
    """A job the user typed in (§2.10, `TRACK-05`).

    Deliberately small. It is not a `Job`: nothing here is deduplicated,
    enriched, scored or embedded, and pretending otherwise would put
    user-entered text into the matching pipeline where a canonical listing
    belongs.
    """

    title: str
    company: str
    location: str | None = None
    url: str | None = None
    description: str | None = None


class StatusChange(BaseModel):
    """One move on the board (§2.10). Append-only.

    `by` distinguishes a move the user made from one a rule made - a
    `deadline_48h` sweep marking something `ghosted`, say. Without it, the
    history says the user did something they did not do.
    """

    from_status: ApplicationStatus | None = Field(default=None, alias="from")
    to: ApplicationStatus
    at: datetime | None = None
    by: str = "user"
    reason: str | None = None

    model_config = {"populate_by_name": True}

    @field_validator("at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None


class Contact(BaseModel):
    """A person at the employer (§2.10). PII, and the user's own note - never
    enriched from a third party."""

    name: str
    role: str | None = None
    email: str | None = None
    notes: str = ""


class StoredDocument(BaseModel):
    """A file the user attached (§2.10).

    `r2_key` and never a URL: `DATA-04` requires every key to sit under a user
    prefix so deletion is a prefix sweep, and requires no key to contain
    anything a person supplied - `name` holds the filename they chose.
    """

    r2_key: str
    name: str
    kind: DocumentKind = DocumentKind.OTHER
    size_bytes: int = 0
    uploaded_at: datetime | None = None

    @field_validator("uploaded_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None


class Interview(BaseModel):
    """One round (§2.10).

    §1: "Documents are never embedded past one level of nesting where the nested
    item can grow unbounded. `applications.interviews` is bounded (a handful)."
    Its own `id` because reminders point at a specific round.
    """

    id: str = Field(default_factory=new_id)
    round: int = 1
    type: InterviewType = InterviewType.OTHER
    at: datetime | None = None
    duration_min: int | None = None
    location: str | None = None
    notes: str = ""
    outcome: InterviewOutcome | None = None

    @field_validator("at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None


class SalaryLogEntry(BaseModel):
    """One step in a negotiation (§2.10). Minor units, integers."""

    at: datetime | None = None
    kind: SalaryLogKind
    amount_minor: int | None = None
    currency: str | None = None
    period: MoneyPeriod | None = None
    note: str = ""

    @field_validator("at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None


class JobReferenceInvalid(ValueError):
    """`AC-DATA-02.3` - "exactly one of `job_id`, `manual_job`".

    Its own exception type rather than a bare `ValueError` so the router can map
    it to a specific error code, and so a test can assert *which* rule fired
    rather than that something was rejected.

    **It does not escape the document's validator.** Pydantic wraps any
    `ValueError` raised inside validation into a `ValidationError`, so
    constructing an illegal `Application` raises that, carrying this message.
    Which is why `check_job_reference` exists as a plain function: the service
    calls it *before* constructing, and gets this type back unwrapped so the
    router can map it to one error code rather than parsing a message.
    """


def check_job_reference(job_id: str | None, manual_job: ManualJob | None) -> None:
    """`AC-DATA-02.3` at the service boundary. Raises `JobReferenceInvalid`.

    Separate from the document validator on purpose, and not a duplicate of it:
    this one is callable before anything is constructed, which is where a
    request handler wants to reject - with a specific code and a field-level
    message, rather than a pydantic `ValidationError` whose shape the client
    has to unpack.
    """
    has_job = job_id is not None
    has_manual = manual_job is not None
    if has_job == has_manual:
        both = "both" if has_job else "neither"
        raise JobReferenceInvalid(
            f"an application references exactly one of job_id and manual_job; "
            f"{both} is set. A tracked application with neither points at "
            "nothing, and one with both points at two different jobs "
            "(TRACK-05)."
        )


class Application(UserOwnedDoc):
    """`applications` - the tracked application (§2.10)."""

    #: Exactly one of these two. Enforced by the validator below at write time
    #: and by a collection-level JSON-schema validator (`AC-DATA-02.3`).
    job_id: str | None = None
    manual_job: ManualJob | None = None

    status: ApplicationStatus = ApplicationStatus.SAVED
    status_history: list[StatusChange] = Field(default_factory=list)

    applied_at: datetime | None = None
    applied_via: AppliedVia | None = None
    current_pack_id: str | None = None

    notes_md: str = ""
    contacts: list[Contact] = Field(default_factory=list)
    documents: list[StoredDocument] = Field(default_factory=list)
    interviews: list[Interview] = Field(default_factory=list)
    salary_log: list[SalaryLogEntry] = Field(default_factory=list)

    next_action_at: datetime | None = None
    last_activity_at: datetime | None = None
    #: A flag, not a status. An expired listing does not move the card.
    listing_expired: bool = False
    source: ApplicationSource = ApplicationSource.MANUAL

    @field_validator("applied_at", "next_action_at", "last_activity_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    def model_post_init(self, context: object, /) -> None:
        """`AC-DATA-02.3`, at write time.

        A model validator as well as a service check: every path that
        constructs an `Application` has to satisfy it, including a migration, a
        fixture and a future endpoint nobody has written yet. Pydantic wraps
        the raise into a `ValidationError`, which is the right shape here -
        this is the backstop, and `check_job_reference` is the front door.
        """
        check_job_reference(self.job_id, self.manual_job)

    class Settings:
        name = "applications"
        validate_on_save = True
        indexes = [
            IndexModel(
                [
                    ("user_id", ASCENDING),
                    ("status", ASCENDING),
                    ("last_activity_at", DESCENDING),
                ],
                name="kanban",
            ),
            # Unique *partial*: one application per job per user, but only
            # where `job_id` exists. Without the partial filter, every manual
            # application (`job_id: null`) would collide with every other one
            # the same user tracked - and manual applications are most of early
            # usage (`TRACK-05`).
            IndexModel(
                [("user_id", ASCENDING), ("job_id", ASCENDING)],
                name="user_job",
                unique=True,
                partialFilterExpression={"job_id": {"$exists": True, "$type": "string"}},
            ),
            IndexModel(
                [("user_id", ASCENDING), ("next_action_at", ASCENDING)],
                name="user_next_action",
            ),
        ]


DOCUMENTS = (Application,)
