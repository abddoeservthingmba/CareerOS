"""T-FOUND-16.8 - the retry policy.

`AC-FOUND-16.8`: "A 4xx from the provider is not retried; a 5xx is retried three
times with backoff."

`01-foundations.md` §16: "never on a 4xx, which means the address or the payload
is wrong and retrying just burns quota."
"""

from __future__ import annotations

import pytest

from app.infra.email.base import SendFailed
from app.infra.email.senders import MAX_ATTEMPTS, MemorySender
from app.infra.email.templates import build_registry

DATA = {"verify_url": "https://example.test/verify/TOKEN"}


def sender(**kwargs: object) -> MemorySender:
    slept: list[float] = []

    async def record(seconds: float) -> None:
        slept.append(seconds)

    instance = MemorySender(
        build_registry(),
        sender_address="no-reply@localhost",
        product_name="JobPilot",
        sleep=record,
        **kwargs,
    )
    instance.slept = slept  # type: ignore[attr-defined]
    return instance


async def test_a_successful_send_makes_one_attempt():
    mailer = sender()
    await mailer.send("a@example.test", "verify_email", DATA)
    assert mailer.attempts == 1
    assert mailer.slept == []  # type: ignore[attr-defined]


async def test_a_4xx_is_not_retried():
    """AC-FOUND-16.8, first half."""
    mailer = sender()
    mailer.fail_with = SendFailed("memory", 422, "invalid_recipient")
    mailer.fail_times = -1  # fail every time

    with pytest.raises(SendFailed) as caught:
        await mailer.send("bad@example.test", "verify_email", DATA)

    assert caught.value.status == 422
    assert mailer.attempts == 1, "a 4xx must not be retried"
    assert mailer.slept == []  # type: ignore[attr-defined]


async def test_a_5xx_is_retried_three_times_with_backoff():
    """AC-FOUND-16.8, second half."""
    mailer = sender()
    mailer.fail_with = SendFailed("memory", 503, "upstream_unavailable")
    mailer.fail_times = -1

    with pytest.raises(SendFailed) as caught:
        await mailer.send("a@example.test", "verify_email", DATA)

    assert caught.value.status == 503
    assert mailer.attempts == MAX_ATTEMPTS == 3
    # Backoff between attempts, not after the last one.
    assert mailer.slept == [1.0, 4.0]  # type: ignore[attr-defined]


async def test_a_transport_error_is_retried():
    """Status 0 marks "never reached the provider" rather than inventing an
    HTTP code for a socket failure."""
    mailer = sender()
    mailer.fail_with = SendFailed("memory", 0, "ConnectionRefusedError")
    mailer.fail_times = -1

    with pytest.raises(SendFailed):
        await mailer.send("a@example.test", "verify_email", DATA)
    assert mailer.attempts == 3


async def test_a_recovered_send_stops_retrying():
    mailer = sender()
    mailer.fail_with = SendFailed("memory", 500, "transient")
    mailer.fail_times = 1  # fail once, then succeed

    message_id = await mailer.send("a@example.test", "verify_email", DATA)

    assert message_id
    assert mailer.attempts == 2
    assert len(mailer.outbox) == 1


def test_retryability_is_decided_by_the_status():
    assert SendFailed("p", 500, "x").retryable
    assert SendFailed("p", 503, "x").retryable
    assert SendFailed("p", 0, "socket").retryable
    assert not SendFailed("p", 400, "x").retryable
    assert not SendFailed("p", 422, "x").retryable
    assert not SendFailed("p", 429, "x").retryable


def test_a_failure_carries_a_code_not_a_message_body():
    """`AC-FOUND-14.5` - a provider's body can echo prompt or message content."""
    failure = SendFailed("resend", 422, "invalid_recipient")
    assert "invalid_recipient" in str(failure)
    assert "422" in str(failure)
