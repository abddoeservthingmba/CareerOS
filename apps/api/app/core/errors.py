"""Errors - `FOUND-12`.

`01-foundations.md` §12: "One error shape, one place that maps exceptions to it,
and a machine-readable code for every failure a client must handle differently."

The rule that matters most: **`code` is the client's contract.** `message` is
human-readable and may change; clients switch on `code`, never on `message` or
status alone. `13-web-client.md` §6 maps every `ErrorCode` to user-facing copy
and reports an unmapped one, which only works if the registry is closed and
exported.

`AC-FOUND-12.4`: "A grep finds no string literal used as an error code outside
`core/errors.py`." Two modules inventing `not_found` is how a client ends up
unable to tell "this job was deleted" from "this is not your application".
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """Every failure a client may need to handle differently.

    Exported to OpenAPI so generated clients get it as a type
    (`AC-FOUND-13.1`), and rendered to `docs/error-codes.md`
    (`AC-FOUND-12.5`).
    """

    # -- generic ------------------------------------------------------------
    INTERNAL_ERROR = "internal_error"
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    NOT_IMPLEMENTED = "not_implemented"
    SERVICE_UNAVAILABLE = "service_unavailable"

    # -- auth (`02-auth-and-account.md`) ------------------------------------
    PASSWORD_TOO_SHORT = "password_too_short"
    PASSWORD_TOO_LONG = "password_too_long"
    PASSWORD_BREACHED = "password_breached"
    CONSENT_VERSION_STALE = "consent_version_stale"
    INVALID_CREDENTIALS = "invalid_credentials"
    OAUTH_INVALID_TOKEN = "oauth_invalid_token"
    OAUTH_EMAIL_UNVERIFIED = "oauth_email_unverified"
    LAST_CREDENTIAL = "last_credential"
    EMAIL_NOT_VERIFIED = "email_not_verified"
    TOKEN_EXPIRED = "token_expired"
    TOKEN_INVALID = "token_invalid"
    REFRESH_REUSED = "refresh_reused"
    ACCOUNT_PENDING_DELETION = "account_pending_deletion"
    SIGNUPS_CLOSED = "signups_closed"

    # -- foundations --------------------------------------------------------
    INVALID_CURSOR = "invalid_cursor"
    IDEMPOTENCY_IN_PROGRESS = "idempotency_in_progress"
    IDEMPOTENCY_KEY_REUSE = "idempotency_key_reuse"

    # -- profile (`03-profile.md`) ------------------------------------------
    PROFILE_VERSION_CONFLICT = "profile_version_conflict"
    UNMAPPABLE_TITLE = "unmappable_title"

    # -- resume (`04-resume-pipeline.md`) -----------------------------------
    FILE_TOO_LARGE = "file_too_large"
    UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
    FILE_REJECTED_SUSPICIOUS = "file_rejected_suspicious"

    # -- ai (`05-ai-layer.md`) ----------------------------------------------
    AI_BUDGET_EXCEEDED = "ai_budget_exceeded"
    AI_UNAVAILABLE = "ai_unavailable"

    # -- apply (`09-apply.md`) ----------------------------------------------
    PACK_NOT_APPROVABLE = "pack_not_approvable"
    PACK_IMMUTABLE = "pack_immutable"
    ANSWER_TYPE_MISMATCH = "answer_type_mismatch"

    # -- tracker (`10-tracker.md`) ------------------------------------------
    INVALID_TRANSITION = "invalid_transition"


# The human-readable one-liner each code carries into `docs/error-codes.md`.
# The client's own copy table (`13-web-client.md` §6) is separate and may say
# something friendlier; this is the operator-facing description.
DESCRIPTIONS: dict[ErrorCode, str] = {
    ErrorCode.INTERNAL_ERROR: "An unhandled failure. The response carries no detail; the log does.",
    ErrorCode.VALIDATION_ERROR: "The request body failed validation. `details.fields` names each.",
    ErrorCode.NOT_FOUND: "No such resource, or it is not yours (`02` §6: 404, never 403).",
    ErrorCode.CONFLICT: "The request conflicts with the resource's current state.",
    ErrorCode.RATE_LIMITED: "Too many requests. `Retry-After` says when to try again.",
    ErrorCode.NOT_IMPLEMENTED: "A reserved route with no implementation behind it (`01` §15).",
    ErrorCode.SERVICE_UNAVAILABLE: "A dependency the request needs is down.",
    ErrorCode.PASSWORD_TOO_SHORT: "Passwords are at least 10 characters.",
    ErrorCode.PASSWORD_TOO_LONG: "Passwords are at most 128 characters.",
    ErrorCode.PASSWORD_BREACHED: "The password appears in a known breach corpus.",
    ErrorCode.CONSENT_VERSION_STALE: "The accepted consent version is not the current one.",
    ErrorCode.INVALID_CREDENTIALS: "Identical for a wrong password and an unknown account.",
    ErrorCode.OAUTH_INVALID_TOKEN: "The Google ID token failed verification.",
    ErrorCode.OAUTH_EMAIL_UNVERIFIED: "Google did not assert the address is verified.",
    ErrorCode.LAST_CREDENTIAL: "Unlinking would leave the account with no way to sign in.",
    ErrorCode.EMAIL_NOT_VERIFIED: "The address must be verified before this operation.",
    ErrorCode.TOKEN_EXPIRED: "The token is past its expiry.",
    ErrorCode.TOKEN_INVALID: "The token is malformed, used, or of the wrong kind.",
    ErrorCode.REFRESH_REUSED: "A revoked refresh token was presented; the family is revoked.",
    ErrorCode.ACCOUNT_PENDING_DELETION: "The account is in its deletion grace period.",
    ErrorCode.SIGNUPS_CLOSED: "Registration is closed (`FLAG_SIGNUP_ENABLED`, D10).",
    ErrorCode.INVALID_CURSOR: "The pagination cursor is malformed or was tampered with.",
    ErrorCode.IDEMPOTENCY_IN_PROGRESS: "A request with this key is still running.",
    ErrorCode.IDEMPOTENCY_KEY_REUSE: "This key was used with a different body.",
    ErrorCode.PROFILE_VERSION_CONFLICT: "The profile changed since this edit was started.",
    ErrorCode.UNMAPPABLE_TITLE: "The title maps to no family, so it would yield no feed.",
    ErrorCode.FILE_TOO_LARGE: "The upload exceeds the 5 MB cap.",
    ErrorCode.UNSUPPORTED_FILE_TYPE: "Magic bytes say this is not a PDF or DOCX.",
    ErrorCode.FILE_REJECTED_SUSPICIOUS: "The archive has zip-bomb characteristics.",
    ErrorCode.AI_BUDGET_EXCEEDED: "The daily AI cap is reached. `Retry-After` gives the reset.",
    ErrorCode.AI_UNAVAILABLE: "The AI provider could not be reached.",
    ErrorCode.PACK_NOT_APPROVABLE: "Open fabrication flags or unresolved answers remain.",
    ErrorCode.PACK_IMMUTABLE: "An approved pack cannot be edited; revise it into a new one.",
    ErrorCode.ANSWER_TYPE_MISMATCH: "The answer does not match the question's declared type.",
    ErrorCode.INVALID_TRANSITION: "`details.allowed` lists the transitions that are possible.",
}


class AppError(Exception):
    """The base of every failure the API renders as `problem+json`.

    `01-foundations.md` §12: `AppError(code, message, http_status, details)`.
    """

    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    http_status: int = 500

    def __init__(
        self,
        message: str | None = None,
        *,
        code: ErrorCode | None = None,
        http_status: int | None = None,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.code = code or type(self).code
        self.http_status = http_status if http_status is not None else type(self).http_status
        self.message = message or DESCRIPTIONS.get(self.code, self.code.value)
        self.details = details
        self.headers = headers or {}
        super().__init__(self.message)

    def problem(self, request_id: str) -> dict[str, Any]:
        """RFC 7807 `application/problem+json`.

        A 500 never leaks an internal message (`AC-FOUND-12.2`): the body is the
        code and the request id, and the detail goes to the log with the
        traceback.
        """
        body: dict[str, Any] = {
            "type": f"about:blank#{self.code.value}",
            "title": self.code.value,
            "status": self.http_status,
            "code": self.code.value,
            "request_id": request_id,
        }
        if self.http_status >= 500 and self.code is ErrorCode.INTERNAL_ERROR:
            return body
        body["detail"] = self.message
        if self.details:
            body["details"] = self.details
        return body


# -- the hierarchy ----------------------------------------------------------
# Subclasses exist where a module raises the same failure from several places
# and the status must not be restated each time.


class NotFound(AppError):
    """`02-auth-and-account.md` §6: a failed ownership check answers 404, never
    403, so an id-addressed endpoint is not an enumeration oracle."""

    code = ErrorCode.NOT_FOUND
    http_status = 404


class ValidationFailed(AppError):
    code = ErrorCode.VALIDATION_ERROR
    http_status = 422


class Conflict(AppError):
    code = ErrorCode.CONFLICT
    http_status = 409


class RateLimited(AppError):
    code = ErrorCode.RATE_LIMITED
    http_status = 429


class NotImplementedRoute(AppError):
    """`01-foundations.md` §15 `stub-501`: a route reserved so a client can tell
    "not yet" from "not a thing". The response never varies by input."""

    code = ErrorCode.NOT_IMPLEMENTED
    http_status = 501


class ServiceUnavailable(AppError):
    code = ErrorCode.SERVICE_UNAVAILABLE
    http_status = 503


class InternalError(AppError):
    code = ErrorCode.INTERNAL_ERROR
    http_status = 500


ERROR_CODES_HEADER = """# Error codes — generated from `app/core/errors.py`

Do not edit. Regenerate with `make error-codes`.

`code` is the client's contract (`01-foundations.md` §12). Clients switch on it,
never on `detail` or on the status alone.

| Code | Status | Meaning |
|---|---|---|
"""


def render_error_codes() -> str:
    """`AC-FOUND-12.5` - `docs/error-codes.md` matches the enum."""
    status_of = {
        ErrorCode.NOT_FOUND: 404,
        ErrorCode.VALIDATION_ERROR: 422,
        ErrorCode.CONFLICT: 409,
        ErrorCode.RATE_LIMITED: 429,
        ErrorCode.NOT_IMPLEMENTED: 501,
        ErrorCode.SERVICE_UNAVAILABLE: 503,
        ErrorCode.INTERNAL_ERROR: 500,
    }
    rows = [
        f"| `{code.value}` | {status_of.get(code, '—')} | {DESCRIPTIONS[code]} |"
        for code in ErrorCode
    ]
    return ERROR_CODES_HEADER + "\n".join(rows) + "\n"
