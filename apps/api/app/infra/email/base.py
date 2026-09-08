"""Transactional email - `FOUND-16`.

`01-foundations.md` §16: "One way to send a templated message to one address,
available from the first phase, owned by infrastructure rather than by the
notifications module."

Why this is foundations and not notifications (`18-dependency-closure.md` §5.1,
violation V1): `AUTH-01`, `AUTH-03` and `AUTH-05` send email in **P1**, and in
v2.0 the only email specification lived in `NOTIF-02a`, phase **P6**. P1 was
unbuildable as written, and the likely improvisation was an inline SMTP call in
`modules/auth` that `notifications` later duplicated.

The cut: **delivering a templated message to an address is infrastructure**,
like storage or the queue. **Deciding which messages a user receives, when, and
through which channel is product**, and stays in `notifications`.

Four properties this module exists to guarantee:

* **No provider SDK type crosses the boundary.** `EmailSender` takes an address,
  a template id and a dict; it returns a `MessageId`. `modules/auth` depends on
  the protocol and nothing else (`AC-FOUND-16.7`).
* **Templates are a registry, validated at startup.** A `send` with a missing
  key raises *before* the provider is contacted (`AC-FOUND-16.2`) - a template
  rendering `Hello {name}` as `Hello None` is worse than a failed send.
* **Idempotent.** The same key inside 24 h is a no-op returning the original
  `MessageId` (`AC-FOUND-16.3`). This is what makes the reminder dispatcher's
  claim-then-send safe (`11-notifications.md` §3).
* **Privacy.** The only personal datum in an email is the recipient's own. Logs
  carry `template_id`, `MessageId` and outcome - never the address, never the
  body, never a token (`AC-FOUND-16.4`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

from app.core import clock

IDEMPOTENCY_WINDOW = timedelta(hours=24)

#: The provider's identifier for a sent message. A string, deliberately: a
#: provider-specific object here would be an SDK type crossing the boundary.
MessageId = str


class EmailError(Exception):
    """The base of everything this module raises."""


class UnknownTemplate(EmailError):
    """A `template_id` that the registry does not hold."""


class MissingTemplateData(EmailError):
    """`AC-FOUND-16.2` - a required key was absent, caught before the provider.

    Names the template and the keys, because the caller is usually a module
    that just added a field to a message and forgot one of its two renderings.
    """

    def __init__(self, template_id: str, missing: list[str]) -> None:
        super().__init__(
            f"{template_id} needs {sorted(missing)}; refusing to send a message "
            "with a blank where a value should be"
        )
        self.template_id = template_id
        self.missing = sorted(missing)


class Undeliverable(EmailError):
    """The address has bounced or complained (`AC-FOUND-16.6`).

    Continuing to send to a bouncing address damages the sending domain's
    reputation for every other user, so this is refused rather than retried.
    """


class SendFailed(EmailError):
    """The provider refused or could not be reached.

    Carries a status and a code, never the provider's message body, which can
    echo content (`AC-FOUND-14.5`).
    """

    def __init__(self, provider: str, status: int, code: str) -> None:
        super().__init__(f"{provider} returned {status} ({code})")
        self.provider = provider
        self.status = status
        self.code = code

    @property
    def retryable(self) -> bool:
        """`AC-FOUND-16.8` - retry a 5xx or a transport error, never a 4xx.

        A 4xx means the address or the payload is wrong; retrying just burns
        quota and delays the failure the caller needs to see.
        """
        return self.status >= 500 or self.status == 0


@dataclass(frozen=True)
class Template:
    """One message, in both renderings.

    A plain-text alternative is required, not optional: text-only clients and
    spam scoring both need one (`01-foundations.md` §16).
    """

    template_id: str
    subject: str
    required: tuple[str, ...]
    html: str
    text: str

    def missing(self, data: Mapping[str, object]) -> list[str]:
        return [key for key in self.required if key not in data or data[key] in (None, "")]

    def render(self, data: Mapping[str, object]) -> tuple[str, str, str]:
        """Return `(subject, html, text)`, or raise before any provider call."""
        absent = self.missing(data)
        if absent:
            raise MissingTemplateData(self.template_id, absent)
        values = {key: str(value) for key, value in data.items()}
        return (
            _fill(self.subject, values),
            _fill(self.html, values),
            _fill(self.text, values),
        )


def _fill(template: str, values: Mapping[str, str]) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{{" + key + "}}", value)
    return out


class TemplateRegistry:
    """Every template the product can send, validated at startup."""

    def __init__(self, templates: list[Template] | None = None) -> None:
        self._templates: dict[str, Template] = {}
        for template in templates or []:
            self.add(template)

    def add(self, template: Template) -> None:
        if template.template_id in self._templates:
            raise EmailError(f"{template.template_id} is registered twice")
        self._templates[template.template_id] = template

    def get(self, template_id: str) -> Template:
        try:
            return self._templates[template_id]
        except KeyError as exc:
            raise UnknownTemplate(
                f"{template_id} is not registered; known: {sorted(self._templates)}"
            ) from exc

    def __contains__(self, template_id: str) -> bool:
        return template_id in self._templates

    def __len__(self) -> int:
        return len(self._templates)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._templates))

    def validate(self) -> None:
        """`§16` - "Templates are a registry, validated at startup"."""
        for template in self._templates.values():
            if not template.subject.strip():
                raise EmailError(f"{template.template_id} has no subject")
            if not template.text.strip():
                raise EmailError(
                    f"{template.template_id} has no plain-text alternative; "
                    "text-only clients and spam scoring both need one"
                )
            declared = set(template.required)
            used = (
                _placeholders(template.subject)
                | _placeholders(template.html)
                | _placeholders(template.text)
            )
            undeclared = used - declared
            if undeclared:
                raise EmailError(
                    f"{template.template_id} uses undeclared keys {sorted(undeclared)}"
                )
            unused = declared - used
            if unused:
                raise EmailError(
                    f"{template.template_id} declares {sorted(unused)} but uses neither"
                )


def _placeholders(text: str) -> set[str]:
    import re

    return set(re.findall(r"\{\{([a-z0-9_]+)\}\}", text))


@dataclass
class SentMessage:
    """What was sent, minus everything that would be a privacy problem to keep."""

    message_id: MessageId
    template_id: str
    sent_at: datetime
    idempotency_key: str | None = None


class IdempotencyStore(Protocol):
    """`AC-FOUND-16.3` - keys seen inside the 24 h window.

    A protocol rather than Redis directly, so the rule is testable without one
    and so `FOUND-10`'s Redis client can supply the real implementation.
    """

    def seen(self, key: str) -> MessageId | None: ...

    def remember(self, key: str, message_id: MessageId) -> None: ...


@dataclass
class MemoryIdempotencyStore:
    """The in-process store. Redis replaces it where more than one worker runs."""

    window: timedelta = IDEMPOTENCY_WINDOW
    _entries: dict[str, tuple[MessageId, datetime]] = field(default_factory=dict)

    def seen(self, key: str) -> MessageId | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        message_id, at = entry
        if clock.now() - at >= self.window:
            del self._entries[key]
            return None
        return message_id

    def remember(self, key: str, message_id: MessageId) -> None:
        self._entries[key] = (message_id, clock.now())


@runtime_checkable
class EmailSender(Protocol):
    """The one interface `infra/email` exposes.

    `01-foundations.md` §16's signature exactly. No provider SDK type appears
    in it, which is what `AC-FOUND-16.7` and `AC-DEP-05.2` assert of
    `modules/auth`.
    """

    async def send(
        self,
        to: str,
        template_id: str,
        data: Mapping[str, object],
        idempotency_key: str | None = None,
    ) -> MessageId: ...


__all__ = [
    "IDEMPOTENCY_WINDOW",
    "EmailError",
    "EmailSender",
    "IdempotencyStore",
    "MemoryIdempotencyStore",
    "MessageId",
    "MissingTemplateData",
    "SendFailed",
    "SentMessage",
    "Template",
    "TemplateRegistry",
    "Undeliverable",
    "UnknownTemplate",
]
