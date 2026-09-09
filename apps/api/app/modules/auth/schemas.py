"""Request and response bodies for the auth module - `AUTH-01`.

`01-foundations.md` §5: schemas are the module's boundary. A document is never
returned from a route (`AC-FOUND-05.4`), so the shapes here are what the API
promises and `models.py` is what the database holds.

`AUTH-01` §1's input: `RegisterRequest{email, password, consent_version,
consent_items[], tz?}`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core import passwords


class RegisterRequest(BaseModel):
    """§1's registration body.

    `extra="forbid"` so a client sending `role: "operator"` gets a 422 rather
    than having it ignored - an ignored field is a field someone will one day
    wire up by accident.

    The password bounds are declared here *and* enforced by
    `passwords.check_length` in the service. Not redundant: pydantic's error is
    a 422 `validation_error` naming the field, and §1 wants
    `password_too_short` / `password_too_long` specifically
    (`AC-AUTH-01.1`), which only the service can raise. The constraint here is
    a cheap outer bound that stops a 10 MB body reaching Argon2; the service is
    what produces the specified error code.
    """

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    #: Bounded generously - the service applies §1's exact policy and its
    #: error codes. `max_length` is the DoS guard, so it matches the policy.
    password: str = Field(min_length=1, max_length=passwords.MAX_LENGTH)
    #: The version the user was shown. A stale one is refused
    #: (`AC-AUTH-01.7`) rather than silently upgraded - `SEC-04`: "A change to
    #: what we do requires re-consent, not a quiet policy edit."
    consent_version: int
    #: The item keys the user accepted. Checked against the current set, so a
    #: client cannot register having accepted a subset.
    consent_items: list[str] = Field(default_factory=list)
    #: An IANA zone. Optional because the client may not know it yet; reminders
    #: are scheduled in UTC and rendered in this (HR-10).
    tz: str | None = None


class RegisterResponse(BaseModel):
    """§1's 202 body.

    One field, and deliberately uninformative. `AC-AUTH-01.4` requires the
    response for an already-registered address to be *byte-identical* to a fresh
    one, so there is nothing here that could differ between the two - no user
    id, no "created" flag, no email echo. Anything that varied would be the
    enumeration oracle §1 exists to close.
    """

    detail: str = "Check your email to finish signing up."


__all__ = ["RegisterRequest", "RegisterResponse"]
