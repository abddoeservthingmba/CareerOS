"""Use cases for the auth module - the ONLY place business rules live.

A service method never touches `fastapi`, never builds a Mongo filter, and never
calls an HTTP client directly; it calls an `infra` or `ai` interface.

`AUTH-01` §1's objective: "Create an account from an email and a password that
is not already known to be compromised, **without revealing whether an email is
registered**."

That last clause is the one that shapes this file. `register` does the same
amount of work whether or not the address is taken - it hashes a password it
will throw away, it sends an email either way, and it returns the same object -
because `AC-AUTH-01.4` requires the two responses to be identical in status,
body, *and* timing to within 50 ms. Every early `return` that could have been
written here is instead a branch that keeps going.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import time
from datetime import timedelta

from app.core import clock, consent, passwords
from app.core.errors import AppError, ErrorCode
from app.core.events import EventBus
from app.infra.breaches import PwnedPasswords
from app.infra.email.base import EmailSender
from app.modules.auth.events import UserRegistered
from app.modules.auth.models import ConsentRecord, EmailToken, EmailTokenKind, User
from app.modules.auth.repository import (
    EmailAlreadyRegistered,
    EmailTokenRepository,
    UserRepository,
)
from app.modules.auth.schemas import RegisterRequest
from app.shared.emails import normalize

logger = logging.getLogger("app.auth")

#: §1's verification link lifetime. Long enough to survive an email sitting
#: unread overnight, short enough that a forwarded message is not a standing
#: credential.
VERIFY_TOKEN_TTL = timedelta(hours=24)

#: 32 bytes of `secrets` - the token goes in a URL, so it is URL-safe base64.
TOKEN_BYTES = 32


class PasswordBreached(AppError):
    """§1 - 422, with the count.

    The count is in `details` because §1 says the rejection comes "with a
    count": a user told their password appears in 12,345 breaches understands
    the problem, where one told "invalid password" tries a variation of the
    same one.
    """

    code = ErrorCode.PASSWORD_BREACHED
    http_status = 422


class ConsentVersionStale(AppError):
    """`AC-AUTH-01.7` - 422, and no user is created.

    `SEC-04`: "A change to what we do requires re-consent, not a quiet policy
    edit." Accepting a stale version would record consent to terms the user was
    never shown.
    """

    code = ErrorCode.CONSENT_VERSION_STALE
    http_status = 422


def token_hash(kind: EmailTokenKind, token: str) -> str:
    """`email_tokens.token_hash` (§2.3), domain-separated by kind.

    §2.3: "Domain-separated hash prefix per kind so a token for one purpose
    cannot be replayed for the other." A verification link that also reset a
    password would be an account takeover by forwarded email.
    """
    return hashlib.sha256(f"{kind.value}:{token}".encode()).hexdigest()


class AuthService:
    """Business rules for auth."""

    def __init__(
        self,
        *,
        users: UserRepository,
        email_tokens: EmailTokenRepository,
        email: EmailSender,
        breaches: PwnedPasswords | None,
        events: EventBus,
        product_name: str,
        web_origin: str,
        min_register_millis: int = 0,
    ) -> None:
        self._users = users
        self._email_tokens = email_tokens
        self._email = email
        #: `None` when `PWNED_PASSWORDS_BASE_URL` is blank. §1's outage
        #: behaviour covers it: allow, and the metric is already incremented by
        #: whoever decided not to build a client.
        self._breaches = breaches
        self._events = events
        self._product_name = product_name
        self._web_origin = web_origin.rstrip("/")
        self._min_register_millis = min_register_millis

    async def register(self, request: RegisterRequest, *, ip: str | None = None) -> None:
        """§1's registration, padded to a constant floor.

        `AC-AUTH-01.4` requires the fresh and already-registered paths to answer
        within 50 ms of each other, and hashing on both is not sufficient: the
        fresh branch additionally writes the user and its verification token,
        and two round trips to a managed database are ~100 ms the collision
        branch never pays. Measured before this padding existed, the fresh path
        was 59 ms *slower* - an oracle for "this address is not registered",
        which is the answer that matters to someone testing a leaked list.

        The floor is applied only to the 202 paths. The two refusals above it -
        a stale consent version and a breached password - are properties of what
        the client sent rather than facts about the address, so they reveal
        nothing and get to be fast.
        """
        started = time.perf_counter()
        await self._register(request, ip=ip)
        await self._pad_to_floor(started)

    async def _pad_to_floor(self, started: float) -> None:
        """Sleep out the remainder of `REGISTER_MIN_MILLIS`.

        If the work already took longer than the floor there is nothing to do -
        and in that case the guarantee is only as good as the floor is
        generous, which is why the value is configuration and why it defaults
        well above the measured cost. A floor that is too low fails quietly, so
        `test_registration_enumeration.py` measures the gap rather than
        trusting this.
        """
        remaining = (self._min_register_millis / 1000) - (time.perf_counter() - started)
        if remaining > 0:
            await asyncio.sleep(remaining)

    async def _register(self, request: RegisterRequest, *, ip: str | None = None) -> None:
        """The work. `register` is what makes it constant-time.

        The order is load-bearing:

        1. **Consent first.** `AC-AUTH-01.7` requires a stale version to create
           no user, and checking it before anything else means there is nothing
           to undo. It is also not enumeration-sensitive: the version a client
           sends is its own, not a fact about the address.
        2. **Password policy, then the breach check.** Both are properties of
           the submitted password, so both are safe to answer precisely.
        3. **Then the collision branch**, which is where identical behaviour
           starts mattering.
        """
        self._require_current_consent(request)
        passwords.check_length(request.password)
        await self._require_unbreached(request.password)

        email_normalized = normalize(request.email)
        existing = await self._users.by_normalized_email(email_normalized)

        # Hashed before the branch, and on both paths. Argon2 at 64 MiB is by
        # far the slowest thing here, so hashing only for new accounts would
        # make "already registered" measurably faster to answer -
        # `AC-AUTH-01.4` gives a 50 ms budget and this alone would blow it.
        password_hash = passwords.hash_password(request.password)

        if existing is not None:
            # §1: "The existing-account case sends a 'someone tried to register
            # with your address' email instead of a verification link." The
            # address is already known to its owner, so this tells them nothing
            # new - and tells a stranger nothing at all, because the response is
            # unchanged.
            await self._send_registration_attempted(existing)
            return

        user = User(
            email=request.email,
            email_normalized=email_normalized,
            email_verified=False,
            password_hash=password_hash,
            tz=request.tz or "UTC",
            consent=[
                ConsentRecord(
                    version=str(consent.CONSENT_VERSION),
                    ip=ip,
                    items=list(request.consent_items),
                )
            ],
        )

        try:
            user = await self._users.insert(user)
        except EmailAlreadyRegistered:
            # Two registrations for one address raced and the other won. The
            # honest answer is the already-registered one, which is the same
            # answer this request would have got a moment earlier.
            existing = await self._users.by_normalized_email(email_normalized)
            if existing is not None:
                await self._send_registration_attempted(existing)
            return

        await self._issue_verification(user)
        # After the user exists and the email is out. A subscriber that enqueued
        # work referencing this id would otherwise be able to run before the
        # document it names is readable.
        self._events.publish(UserRegistered(user_id=str(user.id)))

    # -- the pieces ----------------------------------------------------------

    def _require_current_consent(self, request: RegisterRequest) -> None:
        """`AC-AUTH-01.7`, and `16-security-and-compliance.md` §4.

        Both halves are checked: the version must be current, and the accepted
        keys must cover the current item set. A client that sent the right
        version with an empty `consent_items` would otherwise record a consent
        to nothing.
        """
        if request.consent_version != consent.CONSENT_VERSION:
            raise ConsentVersionStale()

        required = set(consent.item_keys())
        if not required.issubset(set(request.consent_items)):
            raise ConsentVersionStale(
                details={"missing": sorted(required - set(request.consent_items))}
            )

    async def _require_unbreached(self, password: str) -> None:
        """§1's breach check, and its outage behaviour.

        Unreachable means **allow**: "a third-party outage must not close the
        front door". `PwnedPasswords.check` never raises and reports
        `checked=False`, so there is no `except` here - the decision is already
        encoded in the verdict.
        """
        if self._breaches is None:
            return
        verdict = await self._breaches.check(password)
        if verdict.breached:
            raise PasswordBreached(details={"count": verdict.count})

    async def _issue_verification(self, user: User) -> None:
        """A `verify_email` token and the email carrying it (§1's Outputs)."""
        token = secrets.token_urlsafe(TOKEN_BYTES)
        await self._email_tokens.insert(
            EmailToken(
                user_id=str(user.id),
                kind=EmailTokenKind.VERIFY_EMAIL,
                token_hash=token_hash(EmailTokenKind.VERIFY_EMAIL, token),
                expires_at=clock.now() + VERIFY_TOKEN_TTL,
            )
        )
        await self._send(
            user,
            "verify_email",
            {
                # The only place the raw token exists outside the user's inbox.
                # It is deliberately not logged and deliberately not returned.
                "verify_url": f"{self._web_origin}/verify-email?token={token}",
            },
        )

    async def _send_registration_attempted(self, user: User) -> None:
        """§1's existing-account email.

        `reset_url` points at the reset *request* page and carries **no token**.
        The template offers a reset because the likeliest innocent explanation
        is that the account's owner forgot they had one - but minting a reset
        token here would let anyone trigger a working password-reset credential
        for an address they do not control, just by submitting the signup form.
        The recipient asks for the token themselves, which is `AUTH-04`.
        """
        await self._send(
            user,
            "registration_attempted",
            {"reset_url": f"{self._web_origin}/forgot-password"},
        )

    async def _send(self, user: User, template_id: str, data: dict[str, object]) -> None:
        """Send, and never let a mail failure decide the response.

        §1's enumeration rule reaches this far. If a send failure propagated,
        the two paths would diverge the moment one template's provider was
        unhealthy - and the observable would be a 500 for exactly the addresses
        that are already registered.

        The idempotency key is the user and the template, so a retried request
        does not send twice (`FOUND-16`).
        """
        try:
            await self._email.send(
                user.email,
                template_id,
                data,
                idempotency_key=f"{template_id}:{user.id}",
            )
        except Exception as exc:  # noqa: BLE001 - every transport raises its own family
            # The address is not in the log line: `FOUND-14`'s redaction list
            # exists for this, and a log that pairs a template with an address
            # is a list of who has an account.
            logger.warning(
                "registration email failed", extra={"template": template_id}, exc_info=exc
            )


__all__ = [
    "VERIFY_TOKEN_TTL",
    "AuthService",
    "ConsentVersionStale",
    "PasswordBreached",
    "token_hash",
]
