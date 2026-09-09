"""T-AUTH-01.7 - consent is captured at registration, or there is no account.

`AC-AUTH-01.7`: "A registration with a stale `consent_version` is rejected
`422 consent_version_stale` and creates no user."

§1: "Consent is captured **at registration, not after**: the request body
carries `consent_version` and the accepted item keys, and a version that is not
the current one is rejected." `SEC-04` gives the reason: "A change to what we do
requires re-consent, not a quiet policy edit."

Driven against the service rather than the route. The error's mapping to a 422
body is `FOUND-12`'s app-factory handler and is tested there; what belongs here
is that the *right* error is raised and that the database is untouched when it
is. Asserting through HTTP would re-test the handler and hide the "creates no
user" half behind a status code.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from beanie import init_beanie

from app.core import consent
from app.core.errors import ErrorCode
from app.core.events import EventBus
from app.infra.email.senders import MemorySender
from app.infra.email.templates import build_registry
from app.modules.auth.models import EmailToken, User
from app.modules.auth.repository import EmailTokenRepository, UserRepository
from app.modules.auth.schemas import RegisterRequest
from app.modules.auth.service import AuthService, ConsentVersionStale

EMAIL = "consenting@example.com"
PASSWORD = "a-long-enough-password"


@pytest.fixture
async def documents(database: Any) -> AsyncIterator[Any]:
    await init_beanie(database=database, document_models=[User, EmailToken])
    yield database


@pytest.fixture
def service(documents: Any) -> AuthService:
    return AuthService(
        users=UserRepository(),
        email_tokens=EmailTokenRepository(),
        email=MemorySender(
            build_registry(), sender_address="no-reply@test", product_name="JobPilot"
        ),
        breaches=None,
        events=EventBus(),
        product_name="JobPilot",
        web_origin="http://localhost:5173",
        # No padding: this suite asserts behaviour, not timing, and 400 ms per
        # call would make it the slowest file in the repository for no gain.
        min_register_millis=0,
    )


def _request(**overrides: Any) -> RegisterRequest:
    body: dict[str, Any] = {
        "email": EMAIL,
        "password": PASSWORD,
        "consent_version": consent.CONSENT_VERSION,
        "consent_items": list(consent.item_keys()),
    }
    body.update(overrides)
    return RegisterRequest(**body)


async def test_a_current_consent_version_is_accepted(service: AuthService) -> None:
    """The control, and the "captured at registration" half of §1."""
    await service.register(_request())

    user = await User.find_one(User.email_normalized == EMAIL)
    assert user is not None
    assert len(user.consent) == 1
    assert user.consent[0].version == str(consent.CONSENT_VERSION)


async def test_a_stale_version_is_rejected(service: AuthService) -> None:
    """`AC-AUTH-01.7`, first half - the error and its code."""
    with pytest.raises(ConsentVersionStale) as caught:
        await service.register(_request(consent_version=consent.CONSENT_VERSION - 1))

    assert caught.value.code is ErrorCode.CONSENT_VERSION_STALE
    assert caught.value.http_status == 422


async def test_a_stale_version_creates_no_user(service: AuthService) -> None:
    """`AC-AUTH-01.7`, second half - and the reason the check comes first.

    `service._register` validates consent before it hashes, reads or writes
    anything, so there is nothing to roll back. A check placed after the insert
    would leave an account whose consent record is a version the user never
    accepted, which is worse than refusing them.
    """
    before = await User.find_all().count()

    with pytest.raises(ConsentVersionStale):
        await service.register(_request(consent_version=consent.CONSENT_VERSION - 1))

    assert await User.find_all().count() == before
    assert await User.find_one(User.email_normalized == EMAIL) is None


async def test_a_future_version_is_also_stale(service: AuthService) -> None:
    """Not-current, in either direction.

    A client claiming a version we have not published has not been shown it, so
    accepting it would record consent to text that does not exist. `!=` rather
    than `<` is what makes this hold.
    """
    with pytest.raises(ConsentVersionStale):
        await service.register(_request(consent_version=consent.CONSENT_VERSION + 1))


async def test_the_right_version_with_no_items_is_rejected(service: AuthService) -> None:
    """§1 carries "the accepted item keys", not just a version.

    Without this, a client sends the current version and an empty list and the
    stored consent is evidence of nothing - which is exactly the state `SEC-04`
    exists to prevent, and it would pass a version-only check.
    """
    with pytest.raises(ConsentVersionStale):
        await service.register(_request(consent_items=[]))

    assert await User.find_one(User.email_normalized == EMAIL) is None


async def test_a_partial_item_set_is_rejected(service: AuthService) -> None:
    """Every current item, or none of them.

    A subset would let a client opt out of an item the product requires by
    simply not listing it, while still looking like a valid consent.
    """
    keys = list(consent.item_keys())
    assert len(keys) > 1, "this test needs more than one item to drop one"

    with pytest.raises(ConsentVersionStale) as caught:
        await service.register(_request(consent_items=keys[:-1]))

    # The refusal names what was missing, so a client can show the user the
    # item they did not accept rather than a bare "stale consent".
    assert caught.value.details is not None
    assert caught.value.details.get("missing") == [keys[-1]]


async def test_extra_items_are_tolerated(service: AuthService) -> None:
    """A superset is accepted, and stored as sent.

    The rule is that the current set is *covered*, not that the lists match: a
    client that still remembers a retired key should not be refused, and the
    consent record is append-only history, so what the user actually accepted is
    what belongs in it.
    """
    keys = [*consent.item_keys(), "a_retired_key"]

    await service.register(_request(consent_items=keys))

    user = await User.find_one(User.email_normalized == EMAIL)
    assert user is not None
    assert "a_retired_key" in user.consent[0].items


async def test_the_source_address_is_recorded_with_the_consent(service: AuthService) -> None:
    """§2.1 - "The IP is stored here and only here."

    `01-foundations.md` §14 forbids a full IP against a person *beyond* the
    consent record, and this is the exception: an evidenced consent with no
    source address is weak evidence.
    """
    await service.register(_request(), ip="203.0.113.7")

    user = await User.find_one(User.email_normalized == EMAIL)
    assert user is not None
    assert user.consent[0].ip == "203.0.113.7"


async def test_the_new_account_is_unverified(service: AuthService) -> None:
    """§1's Outputs: a `users` document with `email_verified: false`.

    Stated as its own test because the field defaults to `False` on the model -
    so this passes by construction today, and would keep passing silently if
    someone later set it eagerly at registration.
    """
    await service.register(_request())

    user = await User.find_one(User.email_normalized == EMAIL)
    assert user is not None
    assert user.email_verified is False
