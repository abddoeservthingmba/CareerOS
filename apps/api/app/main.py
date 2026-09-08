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
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.ai import prompt
from app.core import clock, metrics, sentry
from app.core import logging as app_logging
from app.core.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode, InvalidCursor
from app.core.idempotency import Idempotency, MemoryStore
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


def valid_request_id(value: str) -> bool:
    """§14: "accepting an inbound `X-Request-ID` if it is a valid UUID".

    Validated rather than trusted. The header is echoed into every log line and
    into the response, so an unvalidated one is a way to write arbitrary text
    into the log aggregator - newlines included, which is how a forged log entry
    gets in - and to poison a correlation search by sending one id with every
    request.
    """
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    # `FOUND-14`. Configured before anything else, so a failure during startup
    # is logged in the same shape as everything after it.
    app_logging.configure(environment=settings.APP_ENV.value, level=settings.LOG_LEVEL)
    sentry.configure(settings.SENTRY_DSN.get_secret_value(), environment=settings.APP_ENV.value)

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

    # `AI-07` §7: "Prompts are loaded and validated at startup ... A malformed
    # prompt fails the boot." Here rather than inside `app.ai` because
    # validation resolves each `output_schema` to a feature module's model, and
    # contract 4 (`ai-is-leaf`) forbids `app.ai -> app.modules`. `app.main` sits
    # above both and is the only place allowed to join them.
    #
    # Fails the boot deliberately. A prompt whose schema no longer imports
    # produces a `StructuredOutputInvalid` on the first real request for that
    # feature, which is a 500 for a user rather than a container that never
    # went live.
    app.state.prompts = prompt.validate_at_startup()

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
        """`AC-FOUND-14.2` - one id, on every line and in the response header.

        Also where the latency histogram is observed, because this is the one
        place that sees every request and its final status - including the ones
        that ended in an exception handler.
        """
        incoming = request.headers.get("X-Request-ID", "")
        assigned = incoming if valid_request_id(incoming) else str(uuid.uuid4())
        request.state.request_id = assigned
        app_logging.bind_request(request_id=assigned)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            app_logging.clear_request()

        metrics.observe_request(
            metrics.route_label(request),
            response.status_code,
            time.perf_counter() - started,
        )
        response.headers["X-Request-ID"] = assigned
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

    @app.get("/metrics", tags=["ops"], include_in_schema=False)
    async def prometheus(x_metrics_token: str = Header(default="")) -> Response:
        """`AC-FOUND-14.3` - 401 without a valid token, all seven families with.

        Protected because `/metrics` describes the shape of the system: which
        routes exist, how much AI spend there is, how many reminders go out. It
        is the reconnaissance step of an attack and a competitor's intelligence
        feed, in one endpoint.
        """
        if not metrics.token_matches(x_metrics_token, settings.METRICS_TOKEN.get_secret_value()):
            raise AppError(code=ErrorCode.TOKEN_INVALID, http_status=401)
        return Response(content=metrics.render(), media_type=metrics.content_type())

    return app


app = create_app
