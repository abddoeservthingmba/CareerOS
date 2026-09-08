"""Beanie documents for the apply module - persistence only.

`17-data-model.md` §2.9 and §2.12: `answer_bank`, `application_packs`,
`audit_log`.

Three properties this shape guarantees, each of which is the difference between
a product a user can trust with an employer-facing document and one they cannot:

**An approved pack is immutable.** §2.9: "Editing an approved pack creates a new
document and sets the old one to `superseded` - approvals are immutable
(`APPLY-07`)." `supersedes` and `content_hash` are what make "this is what I
approved" a checkable claim rather than a memory. Mutating in place would mean
the audit row says a pack was approved and the pack now says something else.

**`edited_by_user` is per item.** §2.9: it "is what lets the UI honestly label
which text is AI-generated and which the user wrote (HR-9)". Per pack would be
useless: a user who rewrote the cover letter and left the summary alone has one
of each, and a single flag has to lie about one of them.

**A pack with an open fabrication flag cannot be approved.** `AC-APPLY-04.4`.
The flag is a document field rather than a UI state because the check has to
happen at the write, not in the client - the client is the part an extension or
a mobile build can be an old version of.

`audit_log` lives here and is **append-only**: the repository exposes `append`
and `find` and nothing else, and `AC-DATA-02.4` additionally requires the Atlas
role used by the app to hold no `update`/`remove` privilege on the collection.
Two independent controls, because an append-only log enforced only in code is
append-only until someone writes a migration.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from app.core.documents import BaseDoc, StoredEmbedding, UserOwnedDoc
from app.shared.timeutils import ensure_utc


class AnswerType(StrEnum):
    """`answer_bank.answer_type` (§7's registry).

    The type decides how an answer may be reused. A `MONEY` answer cannot be
    pasted into a different currency's form and a `DATE` answer goes stale, so
    reuse without a type is reuse that is sometimes wrong in a field an employer
    reads.
    """

    TEXT = "text"
    BOOLEAN = "boolean"
    MONEY = "money"
    DURATION = "duration"
    DATE = "date"
    URL = "url"
    ENUM = "enum"


class PackStatus(StrEnum):
    """`application_packs.status` (§2.9)."""

    DRAFT = "draft"
    APPROVED = "approved"
    SUPERSEDED = "superseded"


class PackTone(StrEnum):
    """`application_packs.tone` (§2.9).

    Stored **only** at the top level of the pack, because it is the parameter
    the pack was generated with. §2.9 records that v2.0 also carried it inside
    `items.cover_letter`, "where it could drift from the value that actually
    produced the text".
    """

    CONCISE = "concise"
    WARM = "warm"
    FORMAL = "formal"


class FabricationStatus(StrEnum):
    """`fabrication_flags[].status` (§2.9).

    `OVERRIDDEN` is not `RESOLVED`: the user asserting a claim is true is a
    different fact from the claim being traceable to their profile, and the
    audit log records the override separately (`fabrication_overridden`).
    Collapsing the two would lose who took responsibility.
    """

    OPEN = "open"
    RESOLVED = "resolved"
    OVERRIDDEN = "overridden"


class EntityType(StrEnum):
    """What kind of unverifiable thing a fabrication flag found (§2.9).

    Numbers, dates and named entities are flagged because they are the claims
    a model invents most confidently and an interviewer checks first.
    """

    NUMBER = "number"
    DATE = "date"
    ORGANISATION = "organisation"
    TITLE = "title"
    CREDENTIAL = "credential"
    OTHER = "other"


class SuggestionType(StrEnum):
    """`items.resume_suggestions[].type` (§2.9). A suggestion about the user's
    own résumé, never an edit to it - the user makes the change."""

    EMPHASIZE = "emphasize"
    REPHRASE = "rephrase"
    ADD = "add"
    REORDER = "reorder"


class AuditKind(StrEnum):
    """`audit_log.kind` (§2.12). Ten members, exactly as §2.12 lists them.

    Every one is an action whose having happened is itself a fact someone may
    need to prove later - an approval, a consent, an export, a deletion. An
    eleventh member is a decision about what the product considers consequential,
    not a refactor.
    """

    PACK_GENERATED = "pack_generated"
    PACK_APPROVED = "pack_approved"
    PACK_SUPERSEDED = "pack_superseded"
    FABRICATION_OVERRIDDEN = "fabrication_overridden"
    APPLIED_CONFIRMED = "applied_confirmed"
    CONSENT_ACCEPTED = "consent_accepted"
    DATA_EXPORT = "data_export"
    DELETION_REQUESTED = "deletion_requested"
    DELETION_COMPLETED = "deletion_completed"
    ADMIN_ACTION = "admin_action"


class Claim(BaseModel):
    """A span of generated text and the profile path it came from (§2.9).

    `source_path` is what makes anti-fabrication checkable rather than
    aspirational: a sentence with no path into the profile is a sentence nobody
    can stand behind, and `APPLY-04` flags exactly those.
    """

    span: str
    source_path: str


class PackText(BaseModel):
    """One generated text item (§2.9)."""

    text: str = ""
    claims: list[Claim] = Field(default_factory=list)
    edited_by_user: bool = False


class PackAnswer(BaseModel):
    """One answered application question (§2.9).

    `needs_user` is a stored decision rather than a threshold applied at render
    time, so the same pack does not become "ready" because a confidence cutoff
    was tuned.
    """

    question: str
    question_key: str | None = None
    answer: str = ""
    #: `answer_bank:<id>`, or the feature that produced it.
    source: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_user: bool = False
    edited_by_user: bool = False


class ResumeSuggestion(BaseModel):
    """Advice about the user's own résumé (§2.9)."""

    type: SuggestionType
    target: str
    suggestion: str
    reason: str | None = None


class PackItems(BaseModel):
    """`application_packs.items` (§2.9).

    `unanswerable_questions` is a first-class list rather than an omission.
    A question the pack could not answer has to be visible, because the
    alternative is a form the user submits with a blank they never saw.
    """

    summary: PackText = Field(default_factory=PackText)
    cover_letter: PackText = Field(default_factory=PackText)
    answers: list[PackAnswer] = Field(default_factory=list)
    resume_suggestions: list[ResumeSuggestion] = Field(default_factory=list)
    unanswerable_questions: list[str] = Field(default_factory=list)


class FabricationFlag(BaseModel):
    """One unverifiable claim (§2.9, `APPLY-04`)."""

    item: str
    span: str
    entity_type: EntityType = EntityType.OTHER
    status: FabricationStatus = FabricationStatus.OPEN
    overridden_at: datetime | None = None

    @field_validator("overridden_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None


class AnswerBankEntry(UserOwnedDoc):
    """`answer_bank` - reusable Q&A (§2.9).

    §2.9: "`question_key` is from the canonical taxonomy in
    `apply/questions.yaml`; free questions get `question_key: null` and match by
    embedding." Both paths exist because employers ask the same twenty questions
    in a hundred wordings, and a taxonomy that had to cover all of them would
    never be finished.
    """

    question_key: str | None = None
    question_text: str
    #: Other wordings seen for the same question, so the exact-match path
    #: catches more before the embedding path is needed.
    variants: list[str] = Field(default_factory=list)
    answer: str
    answer_type: AnswerType = AnswerType.TEXT
    tags: list[str] = Field(default_factory=list)
    source: str = "user"
    confirmed: bool = True
    embedding: StoredEmbedding | None = None

    class Settings:
        name = "answer_bank"
        validate_on_save = True


class ApplicationPack(UserOwnedDoc):
    """`application_packs` - generated artifacts and approval state (§2.9)."""

    application_id: str
    job_id: str
    status: PackStatus = PackStatus.DRAFT
    #: The pack this one replaces. Set on the *new* document, so the chain runs
    #: newest to oldest and the current pack is findable without a scan.
    supersedes: str | None = None
    tone: PackTone = PackTone.CONCISE

    items: PackItems = Field(default_factory=PackItems)
    fabrication_flags: list[FabricationFlag] = Field(default_factory=list)

    #: HR-9's pair, flat because §2.9 names the two fields flat.
    model: str | None = None
    prompt_version: str | None = None

    generated_at: datetime | None = None
    approved_at: datetime | None = None
    #: sha256 of `items` at approval. What makes "this is what I approved" a
    #: claim anyone can check against the audit row.
    content_hash: str | None = None

    @field_validator("generated_at", "approved_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    @property
    def has_open_fabrication_flag(self) -> bool:
        """`AC-APPLY-04.4`: a pack with an open flag cannot be approved.

        A property on the document rather than a check in the service, because
        every write path has to honour it and a service-level check is one new
        endpoint away from being bypassed.
        """
        return any(flag.status is FabricationStatus.OPEN for flag in self.fabrication_flags)

    class Settings:
        name = "application_packs"
        validate_on_save = True


class AuditEntry(BaseDoc):
    """`audit_log` - append-only. No updates, no deletes (§2.12).

    `BaseDoc` rather than `UserOwnedDoc` on purpose: `deleted_at` has no meaning
    on an append-only log, and inheriting a soft-delete field would suggest a
    row could be retired. `user_id` is declared here directly and is nullable,
    because an `admin_action` row has an actor but not necessarily a subject.

    The `at` field duplicates `created_at` because §2.12 names it, and the
    export and compliance queries in `12-admin.md` are written against `at`.
    """

    user_id: str | None = None
    kind: AuditKind
    ref_id: str | None = None
    content_hash: str | None = None
    at: datetime | None = None
    #: A network, never a host (`01-foundations.md` §14).
    ip_prefix: str | None = None
    request_id: str | None = None
    detail: dict[str, str] = Field(default_factory=dict)

    @field_validator("at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    class Settings:
        name = "audit_log"
        validate_on_save = True


DOCUMENTS = (AnswerBankEntry, ApplicationPack, AuditEntry)
