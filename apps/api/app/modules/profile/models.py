"""Beanie documents for the profile module - persistence only.

`17-data-model.md` §2.5 and §2.5.1: `profiles`, `skill_aliases`. (`profile_audit`
is R2 and therefore absent - `01-foundations.md` §15.)

The two properties this shape exists to guarantee:

**Every extracted item says where it came from and whether a human agreed.**
`source`, `confidence`, `confirmed`, `evidence` on each skill and each
experience item. HR-7 and `PROF-03`: a model's guess and a user's statement must
never be indistinguishable, because the whole product then repeats a guess back
to the user as fact - and eventually into an application pack an employer reads.
`evidence` is the phrase from the résumé the guess came from, so a wrong one is
correctable rather than merely deniable.

**`version` is stamped onto every score.** §2.5: it "increments on every
accepted change and is stamped onto every `match_scores` row, so a score can be
attributed to the profile that produced it". Without it, "why did this job score
82" is unanswerable the moment the user edits a skill - the score is still 82
and the inputs are gone.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator
from pymongo import ASCENDING, IndexModel

from app.core.documents import BaseDoc, StoredEmbedding, UserOwnedDoc
from app.shared.enums import RemoteMode
from app.shared.timeutils import ensure_utc


class FieldSource(StrEnum):
    """`profile.field.source` (§2.5, §7's registry).

    Two members, and the distinction is the product's central honesty
    guarantee. `AI` means nobody has confirmed it.
    """

    AI = "ai"
    USER = "user"


class SkillLevel(StrEnum):
    """A self-assessed level. Ordered weakest to strongest."""

    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class Seniority(StrEnum):
    """`profiles.seniority`, derived from total experience.

    The same members as `jobs.seniority` (§2.6) because the matcher compares
    the two directly, and two enums that must compare are one enum. It is
    defined in both places by §7's registry, which is what keeps them equal.
    """

    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    PRINCIPAL = "principal"
    EXECUTIVE = "executive"
    UNKNOWN = "unknown"


class AliasSource(StrEnum):
    """`skill_aliases.source` (§2.5.1)."""

    SEED = "seed"
    ADMIN = "admin"


class Attributed(BaseModel):
    """The four fields every extracted item carries (§2.5, HR-7, `PROF-03`).

    A base class rather than four repeated fields: an item that acquired only
    three of them would still validate, and the one most likely to be dropped
    is `confirmed` - the one that decides whether the product may state the
    item as fact.
    """

    source: FieldSource = FieldSource.AI
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    confirmed: bool = False
    #: The phrase in the résumé this was drawn from. `PROF-03` shows it beside
    #: the field so an unconfirmed guess is auditable rather than mysterious.
    evidence: str | None = None


class Skill(Attributed):
    """One skill on a profile (§2.5).

    `raw` and `canonical` are both stored. Comparing raw skill strings anywhere
    is a defect (`01-foundations.md` §3), and `raw` survives so the UI can show
    the user their own wording rather than our slug.
    """

    raw: str
    canonical: str
    years: float | None = None
    level: SkillLevel | None = None


class ExperienceItem(Attributed):
    """One role (§2.5).

    `end` is nullable and its absence means "current" rather than "unknown" -
    the two would otherwise be the same value, and total-experience arithmetic
    would treat an unparsed date as an ongoing job.
    """

    company: str
    title: str
    start: date | None = None
    end: date | None = None
    is_current: bool = False
    location: str | None = None
    bullets: list[str] = Field(default_factory=list)


class EducationItem(Attributed):
    institution: str
    degree: str | None = None
    field_of_study: str | None = None
    start: date | None = None
    end: date | None = None


class CertificationItem(Attributed):
    name: str
    issuer: str | None = None
    issued_on: date | None = None
    expires_on: date | None = None


class ProjectItem(Attributed):
    name: str
    description: str | None = None
    url: str | None = None
    skills: list[str] = Field(default_factory=list)


class LanguageItem(Attributed):
    name: str
    proficiency: str | None = None


class Identity(BaseModel):
    """Name and headline (§2.5). Not contact details - those are separate so a
    redaction rule can name one field path and cover all of them."""

    full_name: str | None = None
    headline: str | None = None
    summary: str | None = None


class Contact(BaseModel):
    """The PII (§2.5, `03-profile.md` §6).

    Its own object so that `profile_audit` can store a masked value for this
    subtree and nothing else, and so a log-redaction rule has one prefix to
    match rather than five field names to remember.
    """

    email: str | None = None
    phone: str | None = None
    city: str | None = None
    country: str | None = None
    links: list[str] = Field(default_factory=list)


class LocationPreference(BaseModel):
    city: str | None = None
    region: str | None = None
    country: str | None = None


class Preferences(BaseModel):
    """What the candidate is looking for (§2.5).

    Money is a minor-unit integer, never a float: a cover letter quoting a
    salary of 2499999.9999 is a bug the user sends to an employer.
    """

    title_families: list[str] = Field(default_factory=list)
    locations: list[LocationPreference] = Field(default_factory=list)
    remote_mode: RemoteMode = RemoteMode.UNKNOWN
    employment_types: list[str] = Field(default_factory=list)
    salary_min_minor: int | None = None
    salary_currency: str | None = None
    open_to_relocation: bool = False


class StagedExtraction(BaseModel):
    """A pending review (§2.5).

    §2.5: "applying it clears the field and bumps `version`". Staged rather
    than applied because `PROF-03` requires the user to accept an extraction
    before it becomes their profile - writing it straight in would make the
    model's guess indistinguishable from the user's own statement, which is
    exactly what HR-7 forbids.
    """

    resume_id: str
    extraction: dict[str, Any] = Field(default_factory=dict)
    staged_at: datetime | None = None

    @field_validator("staged_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None


class Profile(UserOwnedDoc):
    """`profiles` - the candidate profile, one per user (§2.5).

    The full shape is `03-profile.md` §2's; this is the persistence contract.
    """

    version: int = 1

    identity: Identity = Field(default_factory=Identity)
    contact: Contact = Field(default_factory=Contact)

    skills: list[Skill] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    certifications: list[CertificationItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    languages: list[LanguageItem] = Field(default_factory=list)

    total_experience_months: int = 0
    seniority: Seniority = Seniority.UNKNOWN

    preferences: Preferences = Field(default_factory=Preferences)
    #: Null until R2.
    completeness: int | None = None

    embedding: StoredEmbedding | None = None
    staged_extraction: StagedExtraction | None = None

    class Settings:
        name = "profiles"
        validate_on_save = True
        indexes = [
            # Unique: one profile per user (§2.5). Without the constraint, a
            # retried create writes a second profile and the user has two
            # answers to every question about themselves.
            IndexModel([("user_id", ASCENDING)], name="user_id", unique=True),
            # Multikey. `MATCH-01`'s candidate-set selection reads from the
            # *profile* side too - "which users want a backend role" - when a
            # newly ingested job is scored against everyone.
            IndexModel([("preferences.title_families", ASCENDING)], name="pref_title_families"),
            IndexModel(
                [
                    ("preferences.locations.country", ASCENDING),
                    ("preferences.remote_mode", ASCENDING),
                ],
                name="pref_location",
            ),
        ]


class SkillAlias(BaseDoc):
    """`skill_aliases` - alias to canonical skill (§2.5.1).

    §2.5.1: "the alias IS the `_id`, normalized". So the lookup is a primary-key
    read rather than an indexed query, and the same alias cannot be registered
    twice pointing at two different canonicals.

    Not a `UserOwnedDoc`: the table is global. That is deliberate - a per-user
    alias table would mean two users' identical résumés canonicalize
    differently, and their scores would not be comparable.
    """

    #: Overridden so the alias itself is the key. The default ULID factory is
    #: wrong here and would produce a table nothing could look up by alias.
    id: str = Field(alias="_id")
    canonical: str
    category: str | None = None
    source: AliasSource = AliasSource.SEED

    @property
    def alias(self) -> str:
        """A name for `_id` that says what it holds, for call sites that would
        otherwise read `alias_doc.id` and mean something else."""
        return self.id

    class Settings:
        name = "skill_aliases"
        validate_on_save = True
        # §3 lists only `_id` for this collection, which Mongo creates itself.
        # Declared as empty rather than omitted: an absent `indexes` and a
        # deliberately empty one look the same to a reader, and only one of them
        # is a decision.
        indexes: list[IndexModel] = []


DOCUMENTS = (Profile, SkillAlias)
