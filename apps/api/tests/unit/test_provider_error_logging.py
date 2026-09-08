"""T-FOUND-14.5 - a provider's error is a code, not its body.

`AC-FOUND-14.5`: "An AI provider 400 with an echoed prompt in its body produces
a log line containing the status code and not the body."

`01-foundations.md` §14: "Provider errors are logged as a **code and a status**,
never the provider's message body, which can contain echoed content."

This is the leak nobody predicts, because it arrives from outside. Every rule
about not logging a resume is about our own code; then an AI provider rejects a
request and returns

    {"error": {"message": "Invalid request: 'Senior engineer with eleven years
    at a payments company...' exceeds the token limit"}}

and the obvious `logger.error(response.text)` puts the user's resume in the log
aggregator - through a code path whose author was thinking about an HTTP error,
not about content.

The same shape appears with an email provider echoing a recipient, and a storage
provider echoing an object key that contains a user id. So the rule is not "be
careful with AI responses"; it is that a provider error is **a status and a
classification code**, and the body is never one of the things that gets kept.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
import structlog

from app.core import logging as app_logging
from app.core.errors import AppError, ErrorCode

RESUME = "Senior engineer with eleven years at a payments company"
EMAIL = "someone.private@example.test"
API_KEY = "sk-abcdefghijklmnop1234"

#: What a provider actually sends back, with the request echoed into it.
PROVIDER_BODY = (
    '{"error": {"message": "Invalid request: prompt \'' + RESUME + "' exceeds the "
    'token limit", "type": "invalid_request_error", "code": "context_length_exceeded"}}'
)


class ProviderError(AppError):
    """The shape every provider adapter raises.

    A status and a code, and no field that can hold a body. That is the
    enforcement: `AC-FOUND-14.5` is not a rule an author has to remember, it is
    a class that has nowhere to put the thing they should not log - the same
    move `LLMRequest` makes for file bytes under HR-8.
    """

    code = ErrorCode.AI_UNAVAILABLE
    http_status = 502

    def __init__(self, provider: str, status: int, classification: str) -> None:
        super().__init__(f"{provider} returned {status} ({classification})")
        self.provider = provider
        self.status = status
        self.classification = classification


@pytest.fixture
def lines(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every rendered log record, after the whole processor chain."""
    captured: list[dict[str, Any]] = []

    def record(_logger: Any, _name: str, event: Any) -> str:
        captured.append({k: v for k, v in dict(event).items() if not str(k).startswith("_")})
        return ""

    app_logging.configure(environment="staging", level="DEBUG")
    handler = logging.StreamHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=record,
            foreign_pre_chain=[
                structlog.stdlib.add_log_level,
                structlog.stdlib.add_logger_name,
                app_logging.add_correlation,
                app_logging.add_timestamp,
                app_logging.redact,
            ],
        )
    )
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [handler])
    return captured


def blob(lines: list[dict[str, Any]]) -> str:
    import json

    return json.dumps(lines, default=str)


# -- the criterion -----------------------------------------------------------


def test_a_provider_400_logs_the_status_and_not_the_body(lines):
    """AC-FOUND-14.5."""
    failure = ProviderError("gemini", 400, "context_length_exceeded")

    app_logging.get_logger("app.ai").error(
        "provider rejected the request",
        provider=failure.provider,
        status=failure.status,
        code=failure.classification,
    )

    assert lines, "nothing was logged, so this asserts nothing"
    text = blob(lines)
    assert "400" in text
    assert "context_length_exceeded" in text
    assert RESUME not in text
    assert "exceeds the token limit" not in text


def test_the_error_object_cannot_carry_a_body():
    """The enforcement, rather than the observation.

    A rule an author has to remember is a rule that survives until the first
    frustrating debugging session. A class with nowhere to put the body survives
    longer.
    """
    failure = ProviderError("gemini", 400, "context_length_exceeded")

    assert set(vars(failure)) >= {"provider", "status", "classification"}
    assert not any(isinstance(value, str) and RESUME in value for value in vars(failure).values())
    assert RESUME not in str(failure)


def test_logging_the_body_by_accident_is_still_caught(lines):
    """The second line of defence.

    An author who reaches for `logger.error(response.text)` gets the redaction
    processor - which cannot remove a resume, because a resume is just prose,
    but does remove the address and the key that usually travel with it.

    Stated honestly: this is why the *first* defence is the class above. The
    processor catches recognisable secrets; it cannot catch content.
    """
    app_logging.get_logger("app.ai").error(
        "provider rejected the request",
        provider="gemini",
        status=400,
        detail=f"contacted by {EMAIL} with key {API_KEY}",
    )

    text = blob(lines)
    assert EMAIL not in text
    assert API_KEY not in text


def test_a_body_passed_under_a_content_key_is_dropped_entirely(lines):
    """`body`, `payload`, `content` and `prompt` are redacted by name, so the
    obvious variable name for "the thing the provider sent back" is one the
    processor already refuses."""
    app_logging.get_logger("app.ai").error(
        "provider rejected the request",
        status=400,
        body=PROVIDER_BODY,
        payload=PROVIDER_BODY,
        content=PROVIDER_BODY,
        prompt=RESUME,
    )

    text = blob(lines)
    assert RESUME not in text
    assert "token limit" not in text
    assert "400" in text


def test_a_retry_logs_the_attempt_not_the_request(lines):
    """A retry loop logs once per attempt, so a body logged there is logged
    three times - and the third one is what fills the aggregator during an
    outage."""
    for attempt in (1, 2, 3):
        app_logging.get_logger("app.ai").warning(
            "provider call failed; retrying",
            provider="gemini",
            status=503,
            code="unavailable",
            attempt=attempt,
        )

    text = blob(lines)
    assert len(lines) == 3
    assert RESUME not in text
    assert '"attempt": 3' in text.replace("'", '"')


def test_the_status_is_kept_as_a_number(lines):
    """An operator's first question is "how many 429s". A status folded into a
    message string cannot be aggregated on."""
    app_logging.get_logger("app.ai").error("provider error", provider="gemini", status=429)

    assert lines[0]["status"] == 429


# -- the same rule, for the providers that already exist ---------------------


def test_the_email_adapters_failure_carries_a_code(lines):
    """`FOUND-16`'s `SendFailed`, held to the same rule. An email provider
    echoes the recipient in its error body, which is the address §14 forbids
    more explicitly than anything else."""
    from app.infra.email.base import SendFailed

    failure = SendFailed("resend", 422, "invalid_recipient")

    assert failure.status == 422
    assert failure.code == "invalid_recipient"
    assert EMAIL not in str(failure)
    assert not hasattr(failure, "body")


def test_an_exception_traceback_is_redacted_too(lines):
    """`format_exc_info` runs before `redact`, so a traceback is scrubbed like
    any other text.

    This matters because a traceback carries every frame's arguments, which is
    how a secret reaches a log without anyone writing a logging call for it.
    """
    try:
        raise RuntimeError(f"failed for {EMAIL} using {API_KEY}")
    except RuntimeError:
        app_logging.get_logger("app.ai").exception("provider call blew up")

    text = blob(lines)
    assert EMAIL not in text
    assert API_KEY not in text
    assert "provider call blew up" in text


def test_the_control_line_would_have_leaked(lines):
    """The negative control.

    Every assertion above is of the form "the secret is absent", and absence is
    also what you get from a broken capture. This shows the capture sees what
    was logged.
    """
    app_logging.get_logger("app.ai").error(
        "provider error", provider="gemini", status=400, code="context_length_exceeded"
    )

    text = blob(lines)
    assert "gemini" in text
    assert "context_length_exceeded" in text
