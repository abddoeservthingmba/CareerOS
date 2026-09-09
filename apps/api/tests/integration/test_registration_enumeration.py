"""T-AUTH-01.4 - registering a known address is indistinguishable.

`AC-AUTH-01.4`: "Registering an already-registered email returns a response
byte-identical to a fresh registration (same status, same body, timing within
50 ms), and sends the 'attempted registration' email rather than a verification
link."

§1's objective names this as the point of the whole requirement: "Create an
account ... **without revealing whether an email is registered**." A signup form
that answers differently for a known address is a membership oracle - and for a
job-search product, "is this person looking" is exactly the fact a current
employer would pay to learn.

Driven through the real route rather than the service, because "byte-identical
response" is a claim about bytes. The app here is the auth router with the state
the factory would give it, which keeps the test from needing Redis, prompts and
an object store to assert a property of one endpoint.

`httpx.ASGITransport` rather than `TestClient`: `TestClient` drives the app on
its own event loop through a portal, and `AsyncMongoClient` binds to the loop it
was created on - so the sync client and the `database` fixture cannot share a
connection. The transport runs the app in the test's loop instead.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any, cast

import fakeredis.aioredis as fakeredis
import httpx
import pytest
from beanie import init_beanie
from fastapi import FastAPI

from app.core import consent, ratelimit
from app.core.config import Settings
from app.core.events import EventBus
from app.infra.email.senders import MemorySender
from app.infra.email.templates import build_registry
from app.modules.auth import router as auth_router
from app.modules.auth.models import EmailToken, User
from app.modules.auth.repository import EmailTokenRepository, UserRepository
from app.modules.auth.service import AuthService

TAKEN = "already@example.com"
FRESH = "brand-new@example.com"
PASSWORD = "a-long-enough-password"


def _body(email: str) -> dict[str, Any]:
    return {
        "email": email,
        "password": PASSWORD,
        "consent_version": consent.CONSENT_VERSION,
        "consent_items": list(consent.item_keys()),
    }


@pytest.fixture
async def documents(database: Any) -> AsyncIterator[Any]:
    """A real Mongo, with the unique `email_normalized` index in place.

    The index is the collision mechanism, so an in-memory substitute would be
    testing a different thing - which is the argument `tests/conftest.py` makes
    for using a real database throughout.
    """
    await init_beanie(database=database, document_models=[User, EmailToken])
    yield database


@pytest.fixture
def email() -> MemorySender:
    """`AC-FOUND-16.5` - nothing leaves the process."""
    return MemorySender(build_registry(), sender_address="no-reply@test", product_name="JobPilot")


@pytest.fixture
def settings(settings_factory: Any) -> Settings:
    # §9 limits registration to 5/hour/IP, and `TestClient` sends every request
    # from one host, so the limit would refuse this test rather than the
    # behaviour under test. Raised through configuration, which is what §9 says
    # limits are for.
    return cast(Settings, settings_factory(RATE_REGISTER_PER_HOUR_IP=10_000))


@pytest.fixture
async def client(
    documents: Any, email: MemorySender, settings: Settings
) -> AsyncIterator[tuple[httpx.AsyncClient, MemorySender]]:
    # No exception handlers installed: both registration paths answer 202, so
    # nothing here raises. `test_consent_capture.py` asserts the 422 against
    # the service, where the error is raised, rather than duplicating the app
    # factory's handler.
    app = FastAPI()
    app.state.settings = settings
    app.state.limiter = ratelimit.RateLimiter(fakeredis.FakeRedis())
    app.state.auth_service = AuthService(
        users=UserRepository(),
        email_tokens=EmailTokenRepository(),
        email=email,
        # `None`, so no test reaches the real Pwned Passwords API. §1's outage
        # path allows the registration, which is what this test needs.
        breaches=None,
        events=EventBus(),
        product_name=settings.PRODUCT_NAME,
        web_origin=settings.WEB_ORIGIN,
        min_register_millis=settings.REGISTER_MIN_MILLIS,
    )
    app.include_router(auth_router.router, prefix="/api/v1")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client, email


async def test_a_fresh_registration_is_accepted(client: Any, documents: Any) -> None:
    """The control. Without it, every assertion below could pass on two 500s."""
    http_client, email = client

    response = await http_client.post("/api/v1/auth/register", json=_body(FRESH))

    assert response.status_code == 202
    assert await User.find_one(User.email_normalized == FRESH) is not None
    assert [record.to for record in email.outbox] == [FRESH]


async def test_the_two_responses_are_byte_identical(client: Any, documents: Any) -> None:
    """`AC-AUTH-01.4`'s "byte-identical" - status, body and headers.

    Headers too, though the criterion says status and body: a differing
    `Content-Length` would be a byte difference, and so would a header only one
    branch sets. `Date` is excluded because it is a clock, not a branch.
    """
    http_client, _ = client
    await http_client.post("/api/v1/auth/register", json=_body(TAKEN))

    taken = await http_client.post("/api/v1/auth/register", json=_body(TAKEN))
    fresh = await http_client.post("/api/v1/auth/register", json=_body(FRESH))

    assert taken.status_code == fresh.status_code == 202
    assert taken.content == fresh.content
    volatile = {"date"}
    assert {k.lower(): v for k, v in taken.headers.items() if k.lower() not in volatile} == {
        k.lower(): v for k, v in fresh.headers.items() if k.lower() not in volatile
    }


async def test_the_existing_address_gets_the_attempt_email_not_a_link(
    client: Any, documents: Any
) -> None:
    """`AC-AUTH-01.4`'s second half.

    §1: "The existing-account case sends a 'someone tried to register with your
    address' email instead of a verification link." Asserted on the rendered
    body, because the interesting failure is a verification *link* reaching
    someone who did not ask - anyone could then be sent a token for an address
    they do not own.
    """
    http_client, email = client
    await http_client.post("/api/v1/auth/register", json=_body(TAKEN))
    email.outbox.clear()

    await http_client.post("/api/v1/auth/register", json=_body(TAKEN))

    assert len(email.outbox) == 1
    sent = email.outbox[0]
    assert sent.to == TAKEN
    assert "verify-email?token=" not in sent.html
    assert "verify-email?token=" not in sent.text


async def test_no_second_user_is_created(client: Any, documents: Any) -> None:
    """The collision is refused at the database, not just in the response."""
    http_client, _ = client
    await http_client.post("/api/v1/auth/register", json=_body(TAKEN))
    await http_client.post("/api/v1/auth/register", json=_body(TAKEN))

    assert await User.find(User.email_normalized == TAKEN).count() == 1


async def test_the_timings_are_within_fifty_milliseconds(client: Any, documents: Any) -> None:
    """`AC-AUTH-01.4`'s timing clause - the one a naive implementation fails.

    An early `return` for the taken address skips the Argon2 hash, and Argon2 at
    64 MiB is tens of milliseconds. That difference is measurable over a network
    and is a working oracle. `service.register` therefore hashes on both paths.

    Medians over several samples, not single measurements: a first-call import
    or an index load makes any one request an outlier, and a flaky security test
    gets muted rather than fixed.
    """
    http_client, _ = client
    await http_client.post("/api/v1/auth/register", json=_body(TAKEN))

    async def sample(email: str) -> float:
        started = time.perf_counter()
        await http_client.post("/api/v1/auth/register", json=_body(email))
        return (time.perf_counter() - started) * 1000

    # Warm both paths so neither pays a one-off cost inside a measurement.
    await sample(TAKEN)
    await sample("warm-up@example.com")

    taken = sorted([await sample(TAKEN) for _ in range(5)])[2]
    fresh = sorted([await sample(f"fresh-{index}@example.com") for index in range(5)])[2]

    assert abs(taken - fresh) < 50, (
        f"taken={taken:.1f}ms fresh={fresh:.1f}ms - a measurable difference is an "
        "enumeration oracle (AC-AUTH-01.4)"
    )


async def test_a_verification_token_exists_for_a_new_user_only(client: Any, documents: Any) -> None:
    """§1's Outputs: an `email_tokens` row of kind `verify_email`, for the new
    account - and none for the attempt against an existing one.

    A token minted on the collision path would be a credential issued to
    whoever sent the request, for an address they do not control.
    """
    http_client, _ = client
    await http_client.post("/api/v1/auth/register", json=_body(TAKEN))
    before = await EmailToken.find_all().count()

    await http_client.post("/api/v1/auth/register", json=_body(TAKEN))

    assert await EmailToken.find_all().count() == before
    assert before == 1
