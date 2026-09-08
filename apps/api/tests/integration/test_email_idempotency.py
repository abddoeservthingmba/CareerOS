"""T-FOUND-16.3 - the same key twice is one delivery.

`AC-FOUND-16.3`: "The same idempotency key twice within 24 h produces one
delivery and the same `MessageId`."

This is the property that makes `11-notifications.md` §3's claim-then-send safe:
a dispatcher that crashes after sending and before recording will re-send on
restart, and this is what stops the user getting two of everything.
"""

from __future__ import annotations

from datetime import timedelta

from app.core import clock
from app.infra.email.base import IDEMPOTENCY_WINDOW, MemoryIdempotencyStore
from app.infra.email.senders import MemorySender
from app.infra.email.templates import build_registry

DATA = {"verify_url": "https://example.test/verify/TOKEN"}


def sender(store: MemoryIdempotencyStore | None = None) -> MemorySender:
    return MemorySender(
        build_registry(),
        sender_address="no-reply@localhost",
        product_name="JobPilot",
        idempotency=store or MemoryIdempotencyStore(),
    )


async def test_the_same_key_twice_delivers_once():
    """AC-FOUND-16.3."""
    mailer = sender()

    first = await mailer.send("a@example.test", "verify_email", DATA, "reminder-42")
    second = await mailer.send("a@example.test", "verify_email", DATA, "reminder-42")

    assert first == second, "the second call must return the original MessageId"
    assert len(mailer.outbox) == 1, "the provider was contacted twice"


async def test_the_suppressed_call_never_reaches_the_provider():
    """A no-op that still costs a provider call is not a no-op."""
    mailer = sender()
    await mailer.send("a@example.test", "verify_email", DATA, "k")
    attempts_after_first = mailer.attempts

    await mailer.send("a@example.test", "verify_email", DATA, "k")

    assert mailer.attempts == attempts_after_first


async def test_different_keys_deliver_separately():
    mailer = sender()
    first = await mailer.send("a@example.test", "verify_email", DATA, "k1")
    second = await mailer.send("a@example.test", "verify_email", DATA, "k2")

    assert first != second
    assert len(mailer.outbox) == 2


async def test_no_key_means_no_suppression():
    """A caller that did not ask for idempotency does not silently get it.

    Two password-reset requests a minute apart are two deliberate sends.
    """
    mailer = sender()
    await mailer.send("a@example.test", "verify_email", DATA)
    await mailer.send("a@example.test", "verify_email", DATA)
    assert len(mailer.outbox) == 2


async def test_the_window_is_twenty_four_hours():
    """AC-FOUND-16.3's "within 24 h" - the clock is `core.clock`, never
    `datetime.now` (HR-10, `AC-FOUND-06.1`)."""
    assert timedelta(hours=24) == IDEMPOTENCY_WINDOW
    store = MemoryIdempotencyStore()
    mailer = sender(store)

    start = clock.now()
    with clock.freeze(start):
        first = await mailer.send("a@example.test", "verify_email", DATA, "k")

    with clock.freeze(start + timedelta(hours=23, minutes=59)):
        assert await mailer.send("a@example.test", "verify_email", DATA, "k") == first
        assert len(mailer.outbox) == 1

    # Past the window, the key is a new key: a reminder reusing a stable key
    # must not be suppressed forever.
    with clock.freeze(start + timedelta(hours=24, seconds=1)):
        second = await mailer.send("a@example.test", "verify_email", DATA, "k")

    assert second != first
    assert len(mailer.outbox) == 2


async def test_a_failed_send_does_not_burn_the_key():
    """If the delivery never happened, the retry must be allowed to happen.

    Recording the key before the provider call would turn one transient 500 into
    a verification email the user never receives and can never request again.
    """
    import contextlib

    from app.infra.email.base import SendFailed

    mailer = sender()
    mailer.fail_with = SendFailed("memory", 422, "invalid_recipient")
    mailer.fail_times = 1

    with contextlib.suppress(SendFailed):
        await mailer.send("a@example.test", "verify_email", DATA, "k")

    message_id = await mailer.send("a@example.test", "verify_email", DATA, "k")
    assert message_id
    assert len(mailer.outbox) == 1
