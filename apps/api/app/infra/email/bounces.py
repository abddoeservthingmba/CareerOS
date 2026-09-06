"""Bounces and complaints - `FOUND-16`, `AC-FOUND-16.6`.

`01-foundations.md` §16: "a webhook marks `users.email_undeliverable`, stops
further sends to that address, and surfaces the state in the in-app inbox.
Continuing to send to a bouncing address damages the domain for every other
user."

Three things happen on a bounce, and they belong to three different owners:

1. **Stop sending.** That is this module's job, and it is done here.
2. **Mark the user.** `users.email_undeliverable` is a `DATA-01` field on a
   collection that does not exist until `AUTH-01` in P1. The registry publishes
   to listeners so `modules/auth` can set it without `infra/email` knowing that
   a `User` document exists (`infra-is-dumb`).
3. **Write the in-app notification.** That row is `NOTIF-02`'s, phase P6.

So `AC-FOUND-16.6` is satisfied in halves across phases, which is why the
listener seam is here from the start rather than being retrofitted: the
notification is a subscriber, and P6 adds it by subscribing.

The registry is deliberately not a `Document`. A bounce list that only exists in
one process is wrong for more than one worker - Redis or a collection replaces
`MemoryBounceRegistry` behind the same protocol when `FOUND-10` lands - but the
rule "a marked address is never sent to" is enforced in `SenderBase`, where no
adapter can skip it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from app.core import clock

logger = logging.getLogger("app.email.bounces")


class BounceKind(StrEnum):
    """Why the address stopped being deliverable.

    A complaint (the recipient pressed "this is spam") is treated exactly like a
    hard bounce: both damage the sending domain, and continuing to send after
    either one is the behaviour that gets a domain blocklisted.
    """

    BOUNCE = "bounce"
    COMPLAINT = "complaint"


@dataclass(frozen=True)
class Bounce:
    """One address, marked once.

    `reason` is the provider's classification code, never its message body,
    which can echo the message content (`AC-FOUND-14.5`).
    """

    address: str
    kind: BounceKind
    reason: str
    at: datetime


#: A subscriber. `modules/auth` sets `users.email_undeliverable`; `notifications`
#: writes the inbox row. Neither is imported here.
BounceListener = Callable[[Bounce], None]


class BounceRegistry(Protocol):
    """What `SenderBase` needs from a bounce list, and nothing more."""

    def is_undeliverable(self, address: str) -> bool: ...

    def mark(self, address: str, kind: BounceKind, reason: str = "") -> Bounce: ...


class MemoryBounceRegistry:
    """The in-process implementation.

    Correct for one process, which is every test and local development. A shared
    store replaces it where more than one worker sends.
    """

    def __init__(self) -> None:
        self._marked: dict[str, Bounce] = {}
        self._listeners: list[BounceListener] = []

    # -- the write side (the webhook) ---------------------------------------

    def mark(self, address: str, kind: BounceKind, reason: str = "") -> Bounce:
        """Record the address and tell everyone who asked.

        Idempotent: a provider that delivers the same webhook twice - which they
        all do - must not produce two notifications.
        """
        normalised = _normalise(address)
        existing = self._marked.get(normalised)
        if existing is not None:
            return existing

        bounce = Bounce(normalised, kind, reason, clock.now())
        self._marked[normalised] = bounce
        # `AC-FOUND-16.4` - the address never reaches a log line. The kind and
        # the code are what an operator actually needs.
        logger.info(
            "address marked undeliverable",
            extra={"kind": str(kind), "reason": reason},
        )
        self._publish(bounce)
        return bounce

    def clear(self, address: str) -> None:
        """A user corrected their address, or the provider retracted a soft bounce.

        Without this, one transient failure would lock an account out of every
        future password reset.
        """
        self._marked.pop(_normalise(address), None)

    # -- the read side (every send) -----------------------------------------

    def is_undeliverable(self, address: str) -> bool:
        return _normalise(address) in self._marked

    def get(self, address: str) -> Bounce | None:
        return self._marked.get(_normalise(address))

    def __len__(self) -> int:
        return len(self._marked)

    # -- listeners -----------------------------------------------------------

    def subscribe(self, listener: BounceListener) -> None:
        self._listeners.append(listener)

    def _publish(self, bounce: Bounce) -> None:
        for listener in self._listeners:
            try:
                listener(bounce)
            except Exception:  # noqa: BLE001 - same rule as `core.events.EventBus`
                # A listener that raises must not undo the marking. The address
                # is already stopped; a failed inbox write is a lesser problem
                # than continuing to send to a bouncing address.
                logger.exception("bounce listener failed", extra={"kind": str(bounce.kind)})


def _normalise(address: str) -> str:
    """Addresses are matched case-insensitively.

    The local part is technically case-sensitive; no provider in practice treats
    it that way, and being wrong in the strict direction here means continuing
    to send to an address that just bounced.
    """
    return address.strip().lower()


__all__ = [
    "Bounce",
    "BounceKind",
    "BounceListener",
    "BounceRegistry",
    "MemoryBounceRegistry",
]
