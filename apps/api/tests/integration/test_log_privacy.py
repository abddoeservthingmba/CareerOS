"""T-FOUND-16.4 - nothing personal reaches a log line.

`AC-FOUND-16.4`: "No log line, metric label, or Sentry event contains a
recipient address or a message body." Shared with `FOUND-14`'s redaction rules.

`01-foundations.md` §16: "Logs carry `template_id`, `MessageId` and outcome —
never the address, never the body, never a token. A provider error is logged as
a code (`AC-FOUND-14.5`)."

The reason this is a test and not a review note: the address is the one value in
scope on every code path here, so it is the value a debugging `logger.info` picks
up first, and a log aggregator is a copy of your user table that nobody counts as
one.
"""

from __future__ import annotations

import logging

import pytest

from app.infra.email.base import SendFailed
from app.infra.email.bounces import BounceKind, MemoryBounceRegistry
from app.infra.email.senders import MemorySender
from app.infra.email.templates import build_registry

ADDRESS = "someone.private@example.test"
TOKEN = "tok_5f4dcc3b5aa765d61d8327deb882cf99"
DATA = {"verify_url": f"https://example.test/verify/{TOKEN}"}

#: Everything that must never appear, in any field of any record.
FORBIDDEN = (ADDRESS, "someone.private", TOKEN, "Confirm this address")


#: The attributes `logging` puts on every record. Anything else came from an
#: `extra`, which is what a structured logger ships as fields.
_STANDARD = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


def everything_logged(caplog: pytest.LogCaptureFixture) -> str:
    """Every rendered message plus every `extra` value, as one blob.

    Formatting the message is not enough: a structured logger ships the `extra`
    dict too, so an address passed as `extra={"to": ...}` would pass a
    message-only assertion and still land in the aggregator.
    """
    parts: list[str] = []
    for record in caplog.records:
        parts.append(record.getMessage())
        parts.extend(
            f"{key}={value}" for key, value in record.__dict__.items() if key not in _STANDARD
        )
    return "\n".join(parts)


@pytest.fixture
def logs(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.DEBUG)
    return caplog


def sender(**kwargs: object) -> MemorySender:
    return MemorySender(
        build_registry(),
        sender_address="no-reply@localhost",
        product_name="JobPilot",
        **kwargs,
    )


async def test_a_successful_send_logs_no_address_and_no_body(logs):
    """AC-FOUND-16.4."""
    mailer = sender()
    message_id = await mailer.send(ADDRESS, "verify_email", DATA)

    blob = everything_logged(logs)
    assert logs.records, "a send that logs nothing is not what is being asserted"
    for secret in FORBIDDEN:
        assert secret not in blob, f"{secret!r} reached a log record"
    # What it does carry, so the line is still useful to an operator.
    assert "verify_email" in blob
    assert message_id in blob


async def test_a_provider_failure_logs_a_code_not_a_body(logs):
    """`AC-FOUND-14.5` - a provider's message can echo the content it refused."""
    mailer = sender(sleep=_no_sleep)
    mailer.fail_with = SendFailed("memory", 422, "invalid_recipient")
    mailer.fail_times = -1

    with pytest.raises(SendFailed):
        await mailer.send(ADDRESS, "verify_email", DATA)

    blob = everything_logged(logs)
    for secret in FORBIDDEN:
        assert secret not in blob
    assert "invalid_recipient" in blob
    assert "422" in blob


async def test_a_retried_failure_logs_no_address(logs):
    mailer = sender(sleep=_no_sleep)
    mailer.fail_with = SendFailed("memory", 503, "unavailable")
    mailer.fail_times = -1

    with pytest.raises(SendFailed):
        await mailer.send(ADDRESS, "verify_email", DATA)

    assert ADDRESS not in everything_logged(logs)


async def test_a_suppressed_duplicate_logs_no_address(logs):
    mailer = sender()
    await mailer.send(ADDRESS, "verify_email", DATA, "k")
    await mailer.send(ADDRESS, "verify_email", DATA, "k")

    blob = everything_logged(logs)
    assert ADDRESS not in blob
    assert "duplicate" in blob


def test_a_bounce_logs_no_address(logs):
    """The bounce path handles nothing *but* an address, so it is the easiest
    place to leak one."""
    MemoryBounceRegistry().mark(ADDRESS, BounceKind.COMPLAINT, "spam_report")

    blob = everything_logged(logs)
    assert ADDRESS not in blob
    assert "complaint" in blob
    assert "spam_report" in blob


async def test_the_rendered_body_is_never_logged(logs):
    """The body carries the token, which is the credential in a reset link."""
    mailer = sender()
    await mailer.send(ADDRESS, "password_reset", {"reset_url": f"https://x.test/{TOKEN}"})

    blob = everything_logged(logs)
    assert TOKEN not in blob
    assert "<!doctype html>" not in blob


async def _no_sleep(seconds: float) -> None:
    """Backoff is asserted in `test_email_retries.py`; here it is only delay."""
    return None
