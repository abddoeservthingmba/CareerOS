"""T-FOUND-16.6 - a bounce stops the sending.

`AC-FOUND-16.6`: "A bounce webhook marks the address undeliverable, stops sends,
and writes an in-app notification" (shared with `AC-NOTIF-02.3`).

The criterion spans three owners and two phases. What is asserted here is what
exists in P0:

* the webhook marks the address — asserted;
* further sends stop — asserted, in `SenderBase`, so no adapter can skip it;
* listeners are told — asserted, which is the seam `modules/auth` uses in P1 to
  set `users.email_undeliverable` and `notifications` uses in P6 to write the
  inbox row.

The inbox row itself is `NOTIF-02`, phase P6, and `docs/spec/status.yaml` says
so. Writing a fake one here would make this test green about something that
does not exist.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import clock
from app.infra.email.base import Undeliverable
from app.infra.email.bounces import Bounce, BounceKind, MemoryBounceRegistry
from app.infra.email.senders import MemorySender
from app.infra.email.templates import build_registry

DATA = {"verify_url": "https://example.test/verify/TOKEN"}
SECRET = "webhook-secret-for-tests"


def sender(bounces: MemoryBounceRegistry) -> MemorySender:
    return MemorySender(
        build_registry(),
        sender_address="no-reply@localhost",
        product_name="JobPilot",
        bounces=bounces,
    )


# -- the registry ------------------------------------------------------------


async def test_a_marked_address_is_never_sent_to():
    """AC-FOUND-16.6, "stops sends"."""
    bounces = MemoryBounceRegistry()
    mailer = sender(bounces)

    await mailer.send("a@example.test", "verify_email", DATA)
    bounces.mark("a@example.test", BounceKind.BOUNCE, "hard_bounce")

    with pytest.raises(Undeliverable):
        await mailer.send("a@example.test", "verify_email", DATA)
    assert len(mailer.outbox) == 1


async def test_the_refusal_happens_before_the_provider_is_contacted():
    bounces = MemoryBounceRegistry()
    mailer = sender(bounces)
    bounces.mark("a@example.test", BounceKind.BOUNCE)

    with pytest.raises(Undeliverable):
        await mailer.send("a@example.test", "verify_email", DATA)
    assert mailer.attempts == 0


async def test_only_the_bouncing_address_is_stopped():
    bounces = MemoryBounceRegistry()
    mailer = sender(bounces)
    bounces.mark("a@example.test", BounceKind.BOUNCE)

    await mailer.send("b@example.test", "verify_email", DATA)
    assert len(mailer.outbox) == 1


async def test_a_complaint_stops_sending_exactly_like_a_bounce():
    """Both damage the sending domain; continuing after either is what gets a
    domain blocklisted."""
    bounces = MemoryBounceRegistry()
    mailer = sender(bounces)
    bounces.mark("a@example.test", BounceKind.COMPLAINT, "spam_report")

    with pytest.raises(Undeliverable):
        await mailer.send("a@example.test", "verify_email", DATA)


def test_matching_is_case_insensitive():
    bounces = MemoryBounceRegistry()
    bounces.mark("Someone@Example.Test", BounceKind.BOUNCE)
    assert bounces.is_undeliverable("someone@example.test")
    assert bounces.is_undeliverable("  SOMEONE@EXAMPLE.TEST  ")


def test_marking_twice_is_one_marking():
    """Every provider redelivers a webhook; two notifications for one bounce is
    the bug that produces."""
    bounces = MemoryBounceRegistry()
    seen: list[Bounce] = []
    bounces.subscribe(seen.append)

    first = bounces.mark("a@example.test", BounceKind.BOUNCE, "hard_bounce")
    second = bounces.mark("a@example.test", BounceKind.BOUNCE, "hard_bounce")

    assert first is second
    assert len(seen) == 1
    assert len(bounces) == 1


def test_clearing_restores_delivery():
    """One transient failure must not lock an account out of every future reset."""
    bounces = MemoryBounceRegistry()
    bounces.mark("a@example.test", BounceKind.BOUNCE)
    bounces.clear("A@Example.test")
    assert not bounces.is_undeliverable("a@example.test")


def test_a_listener_receives_the_record():
    """The seam `modules/auth` (P1) and `notifications` (P6) subscribe to."""
    bounces = MemoryBounceRegistry()
    received: list[Bounce] = []
    bounces.subscribe(received.append)

    before = clock.now()
    bounces.mark("a@example.test", BounceKind.COMPLAINT, "spam_report")

    assert len(received) == 1
    assert received[0].address == "a@example.test"
    assert received[0].kind is BounceKind.COMPLAINT
    assert received[0].reason == "spam_report"
    assert received[0].at >= before


def test_a_failing_listener_does_not_undo_the_marking():
    """Same rule as `core.events.EventBus`: a failed inbox write is a lesser
    problem than continuing to send to a bouncing address."""
    bounces = MemoryBounceRegistry()

    def explode(bounce: Bounce) -> None:
        raise RuntimeError("the inbox write failed")

    reached: list[Bounce] = []
    bounces.subscribe(explode)
    bounces.subscribe(reached.append)

    bounces.mark("a@example.test", BounceKind.BOUNCE)

    assert bounces.is_undeliverable("a@example.test")
    assert len(reached) == 1, "a raising listener must not stop the next one"


# -- the webhook -------------------------------------------------------------


def state(client: TestClient) -> Any:
    """`TestClient.app` is typed as a bare ASGI callable, so its `state` is
    invisible to mypy; this is the one place that says so."""
    return client.app.state  # type: ignore[attr-defined]


@pytest.fixture
def client(settings_factory) -> TestClient:
    from app.main import create_app

    app = create_app(settings_factory(EMAIL_WEBHOOK_SECRET=SECRET))
    # The lifespan opens a Mongo connection this endpoint does not use; the
    # webhook is exercised without it so the test stays a unit of `FOUND-16`.
    return TestClient(app)


def test_the_webhook_marks_the_address(client: TestClient):
    """AC-FOUND-16.6, "a bounce webhook marks the address undeliverable"."""
    response = client.post(
        "/internal/email/bounce",
        headers={"X-Webhook-Secret": SECRET},
        json={"address": "a@example.test", "kind": "bounce", "reason": "hard_bounce"},
    )
    assert response.status_code == 202
    assert state(client).bounces.is_undeliverable("a@example.test")


def test_the_marked_address_is_the_one_the_sender_refuses(client: TestClient):
    """The webhook and the sender share one registry, rather than each keeping
    a list that drifts from the other."""
    client.post(
        "/internal/email/bounce",
        headers={"X-Webhook-Secret": SECRET},
        json={"address": "a@example.test"},
    )
    assert state(client).email.is_undeliverable("a@example.test")


def test_a_wrong_secret_is_refused(client: TestClient):
    response = client.post(
        "/internal/email/bounce",
        headers={"X-Webhook-Secret": "wrong"},
        json={"address": "a@example.test"},
    )
    assert response.status_code == 401
    assert not state(client).bounces.is_undeliverable("a@example.test")


def test_a_missing_secret_is_refused(client: TestClient):
    response = client.post("/internal/email/bounce", json={"address": "a@example.test"})
    assert response.status_code == 401


def test_an_unconfigured_webhook_fails_closed(settings_factory):
    """An unauthenticated bounce endpoint lets anyone stop a chosen user from
    receiving a password reset."""
    from app.main import create_app

    unconfigured = TestClient(create_app(settings_factory(EMAIL_WEBHOOK_SECRET="")))
    response = unconfigured.post(
        "/internal/email/bounce",
        headers={"X-Webhook-Secret": ""},
        json={"address": "a@example.test"},
    )
    assert response.status_code == 503
    assert not state(unconfigured).bounces.is_undeliverable("a@example.test")


def test_the_response_echoes_no_address(client: TestClient):
    """`AC-FOUND-16.4` - a receiver that reflects its input is a way to read the
    bounce list one probe at a time."""
    response = client.post(
        "/internal/email/bounce",
        headers={"X-Webhook-Secret": SECRET},
        json={"address": "a@example.test", "reason": "hard_bounce"},
    )
    assert "a@example.test" not in response.text


def test_the_webhook_is_outside_the_generated_client(client: TestClient):
    """`FOUND-13` - a provider callback is not an API consumer, so it is not in
    the OpenAPI document the clients are generated from."""
    paths = client.get("/openapi.json").json()["paths"]
    assert "/internal/email/bounce" not in paths
