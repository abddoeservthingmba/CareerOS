"""What must never be written down - `FOUND-14`.

`01-foundations.md` §14: "Every line binds `request_id`, `module`, and - where
authenticated - `user_id`. Never an email address, never a token, never a code,
never a request or response body, never resume or job text."

One list, three consumers: the log processor, Sentry's `before_send`, and the
span-attribute filter. They are three places a value leaks from, and a rule
written three times is a rule that is eventually written twice.

**The shape of the problem.** A log aggregator is a copy of your user table that
nobody counts as one: it is searchable, retained for months, shipped to a vendor,
and readable by everyone with a dashboard login. The same is true of Sentry, and
more so - an exception report carries local variables. So the question is not
"could this be sensitive" but "is there any reason for this string to exist in
a system built for reading".

**Redaction is by key first, value second.** By key, because the field name is
the reliable signal: `password`, `token`, `email` mean what they say wherever
they appear. By value as well, because the leak that actually happens is an
address interpolated into a message - `f"no user for {email}"` - where there is
no key to match on.

Neither is complete, and that is the point of `AC-FOUND-14.1`: an end-to-end
test that captures every log line from a real flow and asserts the test's own
email, password, JWT, OTP, resume text and job text appear nowhere. This module
is the mechanism; that test is the check on it.
"""

from __future__ import annotations

import re
from typing import Any

#: Field names whose *value* is never logged, whatever it contains. Matched as a
#: substring of the lowercased key, so `user_email`, `emailAddress` and
#: `x_api_token` are all covered by three entries rather than nine.
SENSITIVE_KEYS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "credential",
    "cookie",
    "session",
    "email",
    "otp",
    "code_verifier",
    "pepper",
    "signature",
    # Content, not credentials. A resume is the most personal document a user
    # will ever give this product, and a job description is a third party's
    # copyrighted text.
    "resume_text",
    "resume",
    "job_description",
    "job_text",
    "description",
    "body",
    "payload",
    "prompt",
    "completion",
    "content",
    "message_body",
)

#: Keys that *look* sensitive by the rule above and are not. Without this,
#: `request_body_hash` - which is a digest and the thing that makes idempotency
#: debuggable - would be redacted, and so would `status_code`.
ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "body_hash",
        "request_body_hash",
        "content_hash",
        "content_type",
        "content_length",
        "token_count",
        "input_tokens",
        "output_tokens",
        "prompt_version",
        "session_count",
        "email_undeliverable",
        "template_id",
    }
)

REDACTED = "[redacted]"

#: Values that are recognisably a secret wherever they appear, including inside
#: a formatted message where there is no key to match on.
_EMAIL = re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
#: `header.payload.signature`, base64url, which is a JWT and nothing else.
_JWT = re.compile(r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}\b")
#: `Bearer ...`, and the prefixed shape most providers use for an API key.
#: Both separators: OpenAI and Anthropic write `sk-`, Stripe and Resend write
#: `sk_`, and matching only one leaves half the providers' keys in the logs.
_BEARER = re.compile(r"\bBearer\s+[\w.\-~+/]{12,}=*", re.IGNORECASE)
_API_KEY = re.compile(r"\b(?:sk|rk|pk|re|ghp|gho|xox[baprs])[-_][A-Za-z0-9_\-]{12,}")

VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (_EMAIL, _JWT, _BEARER, _API_KEY)


def is_sensitive_key(key: str) -> bool:
    """Whether a field's value is redacted on the strength of its name alone."""
    lowered = key.lower()
    if lowered in ALLOWED_KEYS:
        return False
    return any(marker in lowered for marker in SENSITIVE_KEYS)


def scrub_text(value: str) -> str:
    """Replace anything recognisably secret inside a string.

    The leak this catches is the one that actually happens: an address
    interpolated into a message, where there is no key to match on and the
    author was three lines deep in a debugging session.
    """
    for pattern in VALUE_PATTERNS:
        value = pattern.sub(REDACTED, value)
    return value


def scrub(value: Any, *, depth: int = 0) -> Any:
    """Redact a value of any shape.

    Recursion is bounded: a deeply nested structure in a log line is already a
    mistake, and following it forever turns a logging call into a hang.
    """
    if depth > 6:
        return REDACTED
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {
            key: (REDACTED if is_sensitive_key(str(key)) else scrub(item, depth=depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return type(value)(scrub(item, depth=depth + 1) for item in value)
    return value


def scrub_event(event: dict[str, Any]) -> dict[str, Any]:
    """One log record's fields, redacted.

    Both rules applied: the key rule removes the value entirely, and the value
    rule catches what the key rule cannot see.
    """
    cleaned: dict[str, Any] = {}
    for key, value in event.items():
        if is_sensitive_key(str(key)):
            cleaned[key] = REDACTED
            continue
        cleaned[key] = scrub(value)
    return cleaned


__all__ = [
    "ALLOWED_KEYS",
    "REDACTED",
    "SENSITIVE_KEYS",
    "VALUE_PATTERNS",
    "is_sensitive_key",
    "scrub",
    "scrub_event",
    "scrub_text",
]
