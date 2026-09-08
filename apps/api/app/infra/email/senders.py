"""Email adapters - `FOUND-16`.

Two implementations of one protocol, which is what makes `AC-FOUND-16.9`
("swapping the adapter requires no change outside `infra/email`") a fact rather
than a hope:

* `MemorySender` — records instead of sending. Local development with no SMTP,
  and the default in tests (`AC-FOUND-16.5`: no test sends mail outside mailpit).
* `SmtpSender` — talks SMTP, which is what mailpit speaks locally.

`ResendSender` (D7's default) and an SES adapter are HTTP clients and arrive
with the credential; they implement the same protocol and are covered by the
same contract suite, which is the point of writing that suite against the
protocol rather than against an adapter.

Everything shared - the registry lookup, the render, the idempotency window,
the bounce list, the retry policy, the logging redaction - lives in
`SenderBase`, so an adapter is the transport and nothing else. That is what
keeps a second adapter cheap and keeps the privacy rules from being
reimplemented per provider.
"""

from __future__ import annotations

import abc
import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from app.core import clock
from app.core.ids import new_id
from app.infra.email.base import (
    EmailError,
    EmailSender,
    IdempotencyStore,
    MemoryIdempotencyStore,
    MessageId,
    SendFailed,
    SentMessage,
    TemplateRegistry,
    Undeliverable,
)
from app.infra.email.bounces import BounceKind, BounceRegistry, MemoryBounceRegistry

logger = logging.getLogger("app.email")

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (1.0, 4.0)


class SenderBase(abc.ABC):
    """The half of an adapter that is the same for every provider."""

    name = "base"

    def __init__(
        self,
        registry: TemplateRegistry,
        *,
        sender_address: str,
        product_name: str,
        idempotency: IdempotencyStore | None = None,
        bounces: BounceRegistry | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._registry = registry
        self._from = sender_address
        self._product = product_name
        # `is None`, not `or`: an empty `MemoryBounceRegistry` is falsy (it
        # defines `__len__`), so `bounces or ...` would silently swap the shared
        # registry the webhook writes to for a private empty one, and every
        # bounce would stop nothing.
        self._idempotency = MemoryIdempotencyStore() if idempotency is None else idempotency
        self.bounces: BounceRegistry = MemoryBounceRegistry() if bounces is None else bounces
        self._sleep = asyncio.sleep if sleep is None else sleep
        self.attempts = 0

    # -- bounce handling (`AC-FOUND-16.6`) ----------------------------------

    def mark_undeliverable(
        self, address: str, kind: BounceKind = BounceKind.BOUNCE, reason: str = ""
    ) -> None:
        """A bounce or complaint webhook lands here.

        Continuing to send to a bouncing address damages the sending domain for
        every other user, so the address is refused rather than retried.
        """
        self.bounces.mark(address, kind, reason)

    def is_undeliverable(self, address: str) -> bool:
        return self.bounces.is_undeliverable(address)

    # -- the send path -------------------------------------------------------

    async def send(
        self,
        to: str,
        template_id: str,
        data: Mapping[str, object],
        idempotency_key: str | None = None,
    ) -> MessageId:
        if self.is_undeliverable(to):
            raise Undeliverable(
                f"{template_id} not sent: the address has bounced. Continuing to "
                "send damages the sending domain for every other user."
            )

        if idempotency_key is not None:
            existing = self._idempotency.seen(idempotency_key)
            if existing is not None:
                # `AC-FOUND-16.3` - a no-op returning the original MessageId.
                logger.info(
                    "email suppressed as duplicate",
                    extra={"template_id": template_id, "message_id": existing},
                )
                return existing

        # `AC-FOUND-16.2` - raises before the provider is contacted.
        template = self._registry.get(template_id)
        subject, html, text = template.render({"product": self._product, **data})

        message_id = await self._deliver_with_retries(to, subject, html, text, template_id)

        if idempotency_key is not None:
            self._idempotency.remember(idempotency_key, message_id)
        return message_id

    async def _deliver_with_retries(
        self, to: str, subject: str, html: str, text: str, template_id: str
    ) -> MessageId:
        """`AC-FOUND-16.8` - 3 attempts on 5xx and transport errors, never on 4xx."""
        last: SendFailed | None = None
        for attempt in range(MAX_ATTEMPTS):
            self.attempts += 1
            try:
                message_id = await self.deliver(to, subject, html, text)
            except SendFailed as failure:
                if not failure.retryable:
                    # A 4xx means the address or the payload is wrong; retrying
                    # burns quota and delays the failure the caller needs.
                    self._log_failure(template_id, failure)
                    raise
                last = failure
                self._log_failure(template_id, failure, attempt=attempt + 1)
                if attempt < MAX_ATTEMPTS - 1:
                    await self._sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
                continue
            # `AC-FOUND-16.4` - template, id and outcome. Never the address,
            # never the body, never a token.
            logger.info(
                "email sent",
                extra={
                    "template_id": template_id,
                    "message_id": message_id,
                    "outcome": "ok",
                    "provider": self.name,
                },
            )
            return message_id
        assert last is not None
        raise last

    def _log_failure(
        self, template_id: str, failure: SendFailed, attempt: int | None = None
    ) -> None:
        logger.warning(
            "email send failed",
            extra={
                "template_id": template_id,
                "outcome": "failed",
                "provider": failure.provider,
                # A code and a status, never the provider's message body, which
                # can echo content (`AC-FOUND-14.5`).
                "status": failure.status,
                "code": failure.code,
                "attempt": attempt,
            },
        )

    @abc.abstractmethod
    async def deliver(self, to: str, subject: str, html: str, text: str) -> MessageId:
        """Put the message on the wire, and nothing else.

        Abstract rather than a `NotImplementedError` body: an adapter that
        forgot to implement it then fails at import rather than at the first
        password reset.
        """


@dataclass
class _Recorded:
    to: str
    subject: str
    html: str
    text: str
    message_id: MessageId


class MemorySender(SenderBase):
    """Records instead of sending.

    The default in tests and in local development with no SMTP running, which
    is how `AC-FOUND-16.5` ("no test sends mail outside mailpit") holds without
    anyone remembering it.
    """

    name = "memory"

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.outbox: list[_Recorded] = []
        self.sent: list[SentMessage] = []
        self.fail_with: SendFailed | None = None
        self.fail_times = 0

    async def deliver(self, to: str, subject: str, html: str, text: str) -> MessageId:
        if self.fail_with is not None and self.fail_times != 0:
            if self.fail_times > 0:
                self.fail_times -= 1
            raise self.fail_with
        message_id = f"memory-{new_id()}"
        self.outbox.append(_Recorded(to, subject, html, text, message_id))
        self.sent.append(SentMessage(message_id=message_id, template_id="", sent_at=clock.now()))
        return message_id

    def last(self) -> _Recorded:
        return self.outbox[-1]


@dataclass
class SmtpSettings:
    host: str = "127.0.0.1"
    port: int = 1025
    use_tls: bool = False
    username: str = ""
    password: str = ""


class SmtpSender(SenderBase):
    """SMTP, which is what mailpit speaks locally.

    `01-foundations.md` §16: "Locally and in tests, the adapter is `mailpit`; no
    test sends real mail."
    """

    name = "smtp"

    def __init__(self, *args: object, smtp: SmtpSettings | None = None, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.smtp = smtp or SmtpSettings()

    async def deliver(self, to: str, subject: str, html: str, text: str) -> MessageId:
        message_id = f"<{new_id()}@jobpilot.local>"
        try:
            await asyncio.to_thread(self._send_sync, to, subject, html, text, message_id)
        except OSError as exc:
            # A transport error, which is retryable. Status 0 marks "never
            # reached the provider" rather than inventing an HTTP code.
            raise SendFailed(self.name, 0, type(exc).__name__) from exc
        return message_id

    def _send_sync(self, to: str, subject: str, html: str, text: str, message_id: str) -> None:
        import smtplib
        from email.message import EmailMessage

        message = EmailMessage()
        message["From"] = self._from
        message["To"] = to
        message["Subject"] = subject
        message["Message-ID"] = message_id
        message.set_content(text)
        message.add_alternative(html, subtype="html")

        with smtplib.SMTP(self.smtp.host, self.smtp.port, timeout=10) as server:
            if self.smtp.use_tls:
                server.starttls()
            if self.smtp.username:
                server.login(self.smtp.username, self.smtp.password)
            server.send_message(message)


#: The adapters that exist today, keyed by `EMAIL_PROVIDER`.
#:
#: `AC-FOUND-16.9`'s claim - "swapping the adapter requires no change outside
#: `infra/email`" - is asserted by running one contract suite over every entry
#: here, so a fourth adapter is a row plus a class and nothing else.
#:
#: `memory` is not an `EMAIL_PROVIDER` value: it is the test and offline default,
#: reached through `build_sender(..., provider="memory")` rather than through
#: configuration, so no deployment can select "records instead of sending".
ADAPTERS: dict[str, type[SenderBase]] = {
    "memory": MemorySender,
    "mailpit": SmtpSender,
}

#: Named by `01-foundations.md` §16 (D7: Resend by default, SES documented) but
#: not built: both are HTTP clients that arrive with a credential. Listed rather
#: than omitted so a misconfigured deployment fails at boot with the reason,
#: instead of at the first password reset with a `KeyError`.
PLANNED_ADAPTERS = ("resend", "ses")


def build_sender(
    provider: str,
    *,
    sender_address: str,
    product_name: str,
    registry: TemplateRegistry | None = None,
    bounces: BounceRegistry | None = None,
    smtp: SmtpSettings | None = None,
) -> SenderBase:
    """Resolve `EMAIL_PROVIDER` to an adapter, at startup.

    Startup rather than first send, deliberately: an unresolvable provider that
    surfaces at the first password reset is a support ticket from a user who
    cannot get in, and a container that boots green while unable to send mail is
    exactly the "up but not ready" state `AC-OPS-01.3` exists to prevent.
    """
    from app.infra.email.templates import build_registry

    adapter = ADAPTERS.get(provider)
    if adapter is None:
        if provider in PLANNED_ADAPTERS:
            raise EmailError(
                f"EMAIL_PROVIDER={provider} names an adapter that is not built. "
                f"Built today: {sorted(ADAPTERS)}. Building it is `FOUND-16`'s "
                "remaining work and needs the provider credential."
            )
        raise EmailError(f"EMAIL_PROVIDER={provider} is not an adapter; known: {sorted(ADAPTERS)}")

    kwargs: dict[str, object] = {
        "sender_address": sender_address,
        "product_name": product_name,
        "bounces": bounces,
    }
    if adapter is SmtpSender:
        kwargs["smtp"] = smtp or SmtpSettings()
    return adapter(registry or build_registry(), **kwargs)  # type: ignore[arg-type]


__all__ = [
    "ADAPTERS",
    "BACKOFF_SECONDS",
    "MAX_ATTEMPTS",
    "PLANNED_ADAPTERS",
    "EmailSender",
    "MemorySender",
    "SenderBase",
    "SmtpSender",
    "SmtpSettings",
    "build_sender",
]
