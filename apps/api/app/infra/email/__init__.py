"""`infra/email` — the transactional email transport (`FOUND-16`).

`01-foundations.md` §16: "`infra/email` exposes one protocol and nothing else."

`modules/auth` imports `EmailSender`, the template ids, and — to set
`users.email_undeliverable` when an address bounces — the `Bounce` record. It
never imports an adapter, never constructs a client, and never names a provider,
which is what `AC-FOUND-16.7` and `AC-DEP-05.2` assert.
"""

from app.infra.email.base import (
    EmailError,
    EmailSender,
    MessageId,
    MissingTemplateData,
    SendFailed,
    Template,
    TemplateRegistry,
    Undeliverable,
    UnknownTemplate,
)
from app.infra.email.bounces import Bounce, BounceKind, BounceListener
from app.infra.email.templates import R1_TEMPLATE_IDS, build_registry

__all__ = [
    "R1_TEMPLATE_IDS",
    "Bounce",
    "BounceKind",
    "BounceListener",
    "EmailError",
    "EmailSender",
    "MessageId",
    "MissingTemplateData",
    "SendFailed",
    "Template",
    "TemplateRegistry",
    "Undeliverable",
    "UnknownTemplate",
    "build_registry",
]
