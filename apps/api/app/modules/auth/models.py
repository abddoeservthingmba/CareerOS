"""Beanie documents for the auth module - persistence only.

`17-data-model.md` §2.1-§2.3: `users`, `refresh_tokens`, `email_tokens`.

Never returned from a route (`AC-FOUND-05.4`), and never exported from
`__init__.py`.

Three shapes here are decisions rather than transcriptions, and each is easier
to get wrong than to get right:

* **`email_normalized` is the uniqueness key, not `email`.** The address the
  user typed is preserved because it is what they will recognise in an email
  header; the normalized form is what an index can enforce. Storing only one of
  them means either losing their capitalisation or letting `A.User@gmail.com`
  and `auser@gmail.com` register twice as different people.
* **`consent` is an array that only ever appends.** `16-security-and-compliance.md`
  §4. Overwriting it answers "what does this user consent to" and destroys
  "what did they consent to in September", which is the question that actually
  gets asked - by a regulator, or by the user.
* **Only an IP *prefix* is stored on a refresh token.** `01-foundations.md` §14
  forbids a full IP against a person outside the consent record. A /24 is
  enough to notice a token being used from a different network and not enough
  to place someone at an address.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator
from pymongo import ASCENDING, IndexModel

from app.core import clock
from app.core.documents import BaseDoc, UserOwnedDoc
from app.shared.timeutils import ensure_utc


class Role(StrEnum):
    """`users.role` (§2.1). "There is no third role in R1."

    Two members, and the absence of a third is load-bearing: every `/admin`
    route checks for `OPERATOR`, so a `SUPPORT` role added later without
    revisiting those checks would silently be an operator.
    """

    USER = "user"
    OPERATOR = "operator"


class UserStatus(StrEnum):
    """`users.status` (§2.1)."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    PENDING_DELETION = "pending_deletion"


class DigestFrequency(StrEnum):
    """`users.settings.notif.digest` (§2.1). `weekly` is unreachable until R2."""

    OFF = "off"
    WEEKLY = "weekly"


class RevokedReason(StrEnum):
    """`refresh_tokens.revoked_reason` (§2.2).

    Six members because the answer to "why is this session gone" differs for
    the user in each case: a rotation is invisible, a `reuse_detected` is a
    security event that revokes the whole family, and `deletion` is
    irreversible.
    """

    ROTATED = "rotated"
    LOGOUT = "logout"
    REUSE_DETECTED = "reuse_detected"
    PASSWORD_CHANGED = "password_changed"
    ADMIN = "admin"
    DELETION = "deletion"


class EmailTokenKind(StrEnum):
    """`email_tokens.kind` (§2.3).

    §2.3: "Domain-separated hash prefix per kind so a token for one purpose
    cannot be replayed for the other." A verification link that also resets a
    password is an account takeover by forwarded email.
    """

    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"


class OAuthLink(BaseModel):
    """One linked provider identity (§2.1).

    HR-6: this is sign-in only. Nothing here is reachable from the AI path, and
    no token is stored - only the provider's stable subject id, which is what
    identifies the account on a later sign-in.
    """

    provider: str
    sub: str
    linked_at: datetime = Field(default_factory=clock.now)

    @field_validator("linked_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class ConsentRecord(BaseModel):
    """One accepted consent version (§2.1, `SEC-04`).

    The IP is stored here and only here. §14's rule is "no full IP against a
    person *beyond the consent record*" - a consent needs to be evidenced, and
    an evidenced consent with no source address is weak evidence.
    """

    version: str
    accepted_at: datetime = Field(default_factory=clock.now)
    ip: str | None = None
    items: list[str] = Field(default_factory=list)

    @field_validator("accepted_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class QuietHours(BaseModel):
    """A local-time window in which nothing is sent (§2.1, HR-10).

    Local, deliberately, and the only place local time appears in storage: a
    quiet-hours window means the user's night, not UTC's. The conversion happens
    at reminder scheduling.
    """

    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=0, le=23)


class NotificationSettings(BaseModel):
    """`users.settings.notif` (§2.1)."""

    email: bool = True
    in_app: bool = True
    push: bool = False
    digest: DigestFrequency = DigestFrequency.OFF
    quiet_hours: QuietHours | None = None


class UserSettings(BaseModel):
    """`users.settings` (§2.1)."""

    match_threshold: int = Field(default=60, ge=0, le=100)
    notif: NotificationSettings = Field(default_factory=NotificationSettings)


class User(BaseDoc):
    """`users` - identity, role, settings, consent (§2.1).

    `BaseDoc` rather than `UserOwnedDoc`: this document *is* the user, so its
    `_id` is the `user_id` every other collection points at. It carries
    `deleted_at` itself because the soft-delete convention applies to it too -
    `AUTH-07`'s sweep needs the same field name here as everywhere else.
    """

    email: str
    #: The uniqueness key: lowercased and, for Gmail-family domains,
    #: dot-stripped. `email` preserves what the user typed.
    email_normalized: str
    email_verified: bool = False
    #: Argon2id. Nullable because an OAuth-only account has no password
    #: (`AUTH-03`), which is different from having an empty one.
    password_hash: str | None = None
    oauth: list[OAuthLink] = Field(default_factory=list)
    role: Role = Role.USER
    #: An IANA zone. Reminders are scheduled in UTC and rendered here (HR-10).
    tz: str = "UTC"
    #: Append-only. A new version appends; nothing is ever overwritten.
    consent: list[ConsentRecord] = Field(default_factory=list)
    settings: UserSettings = Field(default_factory=UserSettings)
    status: UserStatus = UserStatus.ACTIVE
    #: Set when the user asks; `deleted_at` is set when the purge completes.
    #: Two fields because the gap between them is the grace period (`AUTH-07`).
    deletion_requested_at: datetime | None = None
    deleted_at: datetime | None = None

    class Settings:
        name = "users"
        validate_on_save = True
        indexes = [
            # §3: the login and registration-collision key. Unique, so two
            # accounts for one person is a write failure rather than a support
            # ticket six months later.
            IndexModel([("email_normalized", ASCENDING)], name="email_normalized", unique=True),
            # Sparse: most users have no linked provider, and a non-sparse
            # unique index would collide every one of them on `null`.
            IndexModel(
                [("oauth.provider", ASCENDING), ("oauth.sub", ASCENDING)],
                name="oauth_identity",
                unique=True,
                sparse=True,
            ),
            # `account.purge_deleted`'s cron scan. Not user-scoped on purpose:
            # `users` is not a user-owned collection - it *is* the user.
            IndexModel(
                [("status", ASCENDING), ("deletion_requested_at", ASCENDING)],
                name="pending_deletion",
            ),
        ]


class DeviceFingerprint(BaseModel):
    """What a refresh token remembers about where it was issued (§2.2)."""

    ua: str | None = None
    #: A network, never a host. `01-foundations.md` §14.
    ip_prefix: str | None = None


class RefreshToken(UserOwnedDoc):
    """`refresh_tokens` - rotating refresh families (§2.2).

    A *family* rather than a token is the unit of revocation: presenting an
    already-rotated token means either a replay or a stolen token, and there is
    no way to tell which, so the whole family goes. `replaced_by` is what makes
    that chain reconstructible.
    """

    family_id: str
    #: sha256 with a pepper. The token itself is never stored - a database dump
    #: must not be a set of working sessions.
    token_hash: str
    expires_at: datetime
    revoked_at: datetime | None = None
    revoked_reason: RevokedReason | None = None
    replaced_by: str | None = None
    device: DeviceFingerprint = Field(default_factory=DeviceFingerprint)

    @field_validator("expires_at", "revoked_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    class Settings:
        name = "refresh_tokens"
        validate_on_save = True
        indexes = [
            IndexModel([("token_hash", ASCENDING)], name="token_hash", unique=True),
            # Family revoke: presenting a rotated token revokes the whole
            # family, so the family has to be findable in one query.
            IndexModel([("family_id", ASCENDING)], name="family_id"),
            # TTL. Mongo's reaper runs about once a minute, so expiry is
            # eventual - which is why `expires_at` is *also* checked on every
            # refresh rather than trusted to the index.
            IndexModel([("expires_at", ASCENDING)], name="expires_at_ttl", expireAfterSeconds=0),
        ]


class EmailToken(UserOwnedDoc):
    """`email_tokens` - verification and reset tokens, hashed (§2.3).

    `attempts` is stored rather than counted in Redis because the limit has to
    survive a restart: a reset token that becomes brute-forceable whenever a
    container recycles is not rate-limited.
    """

    kind: EmailTokenKind
    #: `sha256('<kind>:' + token)`. The prefix is the domain separation.
    token_hash: str
    expires_at: datetime
    used_at: datetime | None = None
    attempts: int = 0

    @field_validator("expires_at", "used_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    class Settings:
        name = "email_tokens"
        validate_on_save = True
        indexes = [
            IndexModel([("token_hash", ASCENDING)], name="token_hash", unique=True),
            IndexModel([("expires_at", ASCENDING)], name="expires_at_ttl", expireAfterSeconds=0),
        ]


#: Every document this module owns, for `init_beanie` and the ownership check
#: (`AC-DATA-02.2`). Enumerated rather than discovered so that a document added
#: without being registered fails the schema snapshot instead of silently never
#: being initialised.
DOCUMENTS = (User, RefreshToken, EmailToken)
