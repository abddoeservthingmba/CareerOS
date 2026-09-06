"""The app factory - `FOUND-01`, and the error handler from `FOUND-12`.

`01-foundations.md` §1: "`main.py` - app factory only: settings, middleware,
routers, lifespan." No business rule lives here.

`/healthz`, `/readyz` and `/metrics` sit **outside** `/api/v1` and outside the
generated clients (`FOUND-13`), because a load balancer and a scrape job are not
API consumers.

`/readyz` is the one with teeth: `AC-OPS-01.3` requires 503 when Mongo is down,
when Redis is down, or when a declared index is missing - "a container that is
up but missing an index is not ready". Redis and the index check arrive with
`FOUND-10` and `DATA-03`; what it checks today is reported honestly in the
response rather than implied by a bare 200.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core import clock
from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode, InvalidCursor
from app.core.idempotency import Idempotency, MemoryStore
from app.core.ids import new_id
from app.infra import mongo
from app.infra.email import webhook as email_webhook
from app.infra.email.bounces import MemoryBounceRegistry
from app.infra.email.senders import SmtpSettings, build_sender
from app.shared.pagination import CursorError

STARTED_AT = time.monotonic()

# What `/readyz` checks today. Each entry is a dependency the container must
# reach before it can serve. Redis (`FOUND-10`) and the declared-index check
# (`DATA-03`) join this list when they land, so the response is never a bare
# "ready" that means less than it looks.
READINESS_CHECKS = ("mongo",)
PENDING_CHECKS = ("redis", "indexes")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    app.state.mongo = mongo.build_client(settings.MONGODB_URI.get_secret_value())
    app.state.database = app.state.mongo[settings.MONGODB_DB]
    try:
        yield
    finally:
        await app.state.mongo.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title=f"{settings.PRODUCT_NAME} API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.state.settings = settings

    # `FOUND-16`. Resolved here rather than at the first send: a container that
    # boots green while unable to send mail is the "up but not ready" state
    # `AC-OPS-01.3` exists to prevent, and the user who finds out is one who
    # cannot get back into their account.
    app.state.bounces = MemoryBounceRegistry()
    app.state.email = build_sender(
        settings.EMAIL_PROVIDER,
        sender_address=settings.EMAIL_FROM,
        product_name=settings.PRODUCT_NAME,
        bounces=app.state.bounces,
        smtp=SmtpSettings(host=settings.SMTP_HOST, port=settings.SMTP_PORT),
    )
    app.state.email_webhook_secret = settings.EMAIL_WEBHOOK_SECRET.get_secret_value()
    app.include_router(email_webhook.router)

    # `FOUND-08`. The store is `MemoryStore` until the Redis client lands with
    # `FOUND-10`'s queue - correct for one worker, wrong the moment two
    # containers serve the same user, which is why `/readyz` still names
    # `redis` in `not_yet_checked` rather than reporting ready without it.
    app.state.idempotency = Idempotency(MemoryStore())

    # `16-security-and-compliance.md` §2, control 7: an explicit origin
    # allowlist, credentials true, never a wildcard outside local.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.WEB_ORIGIN],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next: Any) -> Any:
        """`FOUND-14`: one middleware assigns `request_id` and echoes it back."""
        incoming = request.headers.get("X-Request-ID", "")
        request.state.request_id = incoming or new_id()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        """`FOUND-12`: one place that renders RFC 7807 `problem+json`."""
        return JSONResponse(
            status_code=exc.http_status,
            content=exc.problem(getattr(request.state, "request_id", "")),
            media_type="application/problem+json",
            headers=exc.headers,
        )

    @app.exception_handler(CursorError)
    async def handle_bad_cursor(request: Request, exc: CursorError) -> JSONResponse:
        """`AC-FOUND-07.2` - 400 `invalid_cursor`.

        Converted here rather than in every list endpoint: `shared.pagination`
        raises a plain `ValueError` because `shared` may not import `core`, and
        a `try/except` per route is exactly the boilerplate one of them would
        eventually forget - turning a tampered cursor into a 500.
        """
        error = InvalidCursor()
        return JSONResponse(
            status_code=error.http_status,
            content=error.problem(getattr(request.state, "request_id", "")),
            media_type="application/problem+json",
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        """`AC-FOUND-12.2`: a 500 leaks no internal message."""
        error = AppError(code=ErrorCode.INTERNAL_ERROR, http_status=500)
        return JSONResponse(
            status_code=500,
            content=error.problem(getattr(request.state, "request_id", "")),
            media_type="application/problem+json",
        )

    @app.get("/healthz", tags=["ops"], include_in_schema=False)
    async def healthz() -> dict[str, Any]:
        """Liveness: the process is up. No dependency is consulted."""
        return {
            "status": "ok",
            "product": settings.PRODUCT_NAME,
            "environment": settings.APP_ENV.value,
            "version": app.version,
            "uptime_seconds": round(time.monotonic() - STARTED_AT, 1),
            "time": clock.now().isoformat(),
        }

    @app.get("/readyz", tags=["ops"], include_in_schema=False)
    async def readyz() -> JSONResponse:
        """Readiness: every dependency this container needs is reachable."""
        checks: dict[str, str] = {}
        try:
            checks["mongo"] = "ok" if await mongo.ping(app.state.database) else "failed"
        except Exception as exc:  # noqa: BLE001 - the reason is reported, not raised
            checks["mongo"] = f"unreachable: {type(exc).__name__}"

        ready = all(value == "ok" for value in checks.values())
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "status": "ready" if ready else "not ready",
                "checks": checks,
                # Named rather than omitted: a `/readyz` that quietly checks
                # less than it should is worse than one that says so.
                "not_yet_checked": list(PENDING_CHECKS),
                "time": clock.now().isoformat(),
            },
        )

    return app


app = create_app
