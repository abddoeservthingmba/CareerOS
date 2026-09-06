"""The bounce webhook - `FOUND-16`, `AC-FOUND-16.6`.

`01-foundations.md` §16, Outputs: "`infra/email/{base,resend,mailpit}.py`; the
template registry; **the bounce webhook**".

This is the provider calling us, not a user calling the API, so it lives outside
`/api/v1` and outside the generated clients (`FOUND-13`) for the same reason
`/healthz` does: a webhook receiver is not an API consumer.

Two decisions worth stating.

**It fails closed.** With no `EMAIL_WEBHOOK_SECRET` configured the endpoint
returns 503 rather than accepting anything. An unauthenticated bounce endpoint
is a way for anyone to stop a chosen user from receiving a password reset, which
is an account-takeover step, not a nuisance.

**It normalises before it authenticates nothing else.** Each provider posts its
own JSON shape; the parser turns that into `(address, kind, reason)` and refuses
anything it does not recognise. A parser that guessed would mark the wrong
address undeliverable on a payload change.
"""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field

from app.core.errors import AppError, ErrorCode
from app.infra.email.bounces import BounceKind, MemoryBounceRegistry

router = APIRouter(tags=["ops"], include_in_schema=False)


class BouncePayload(BaseModel):
    """The normalised shape.

    Provider-specific payloads (Resend's `type`/`data.to`, SES's SNS envelope)
    are translated into this by `normalise_payload` when those adapters land.
    """

    address: str = Field(min_length=3, max_length=320)
    kind: BounceKind = BounceKind.BOUNCE
    #: The provider's classification code, never its message body
    #: (`AC-FOUND-14.5`).
    reason: str = Field(default="", max_length=120)


@router.post("/internal/email/bounce", status_code=202)
async def receive_bounce(
    request: Request,
    payload: BouncePayload,
    x_webhook_secret: str = Header(default=""),
) -> dict[str, Any]:
    """Mark the address undeliverable and stop sending to it."""
    configured: str = getattr(request.app.state, "email_webhook_secret", "")
    if not configured:
        raise AppError(
            "the bounce webhook is not configured; set EMAIL_WEBHOOK_SECRET. "
            "An unauthenticated bounce endpoint lets anyone stop a chosen user "
            "from receiving a password reset.",
            code=ErrorCode.SERVICE_UNAVAILABLE,
            http_status=503,
        )
    if not hmac.compare_digest(x_webhook_secret, configured):
        raise AppError(code=ErrorCode.TOKEN_INVALID, http_status=401)

    registry = getattr(request.app.state, "bounces", None)
    if registry is None:  # pragma: no cover - the app factory always sets it
        registry = MemoryBounceRegistry()
        request.app.state.bounces = registry
    registry.mark(payload.address, payload.kind, payload.reason)

    # The response echoes no address: a webhook receiver that reflects its input
    # is a way to read the bounce list one probe at a time.
    return {"status": "marked", "kind": str(payload.kind)}


__all__ = ["BouncePayload", "router"]
