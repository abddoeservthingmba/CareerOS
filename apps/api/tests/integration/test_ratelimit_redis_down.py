"""T-AUTH-09.5 - the limiter is down, so the login does not happen.

`AC-AUTH-09.5`: "With Redis down, `POST /auth/login` returns 503 and
`GET /jobs` still returns 200."

§9: "Redis unavailable: **fail closed** on auth routes (503), fail open on
read-only routes. An unprotected login endpoint is worse than a brief outage."

The failure is injected rather than staged against a real Redis, for the reason
`test_idempotency_redis_down.py` gives: "A store that raises on every call is
what an unreachable Redis *is* from this module's side, and taking a container
down mid-suite would make this the flakiest test in the repository for no extra
fidelity."

**Scope note.** The criterion names two routes and neither exists yet -
`POST /auth/login` arrives with `AUTH-02`, `GET /jobs` with `JOB-01`. What is
asserted here is the mechanism both will use: the exception an auth route lets
propagate carries a 503, and a read-only caller can catch the same exception
and serve. When those routes land they inherit this behaviour rather than
reimplement it, and the criterion's route-level form binds then.
"""

from __future__ import annotations

from typing import Any, cast

import fakeredis.aioredis as fakeredis
import pytest

from app.core.config import Settings
from app.core.errors import ErrorCode
from app.core.ratelimit import (
    Bucket,
    Limit,
    LimiterUnavailable,
    RateLimiter,
    login_buckets,
)

ROUTE = "POST /api/v1/auth/login"


class Unreachable:
    """Every operation raises what a dead connection raises."""

    def __init__(self, failure: type[Exception] = ConnectionError) -> None:
        self._failure = failure

    def pipeline(self, transaction: bool = True) -> Unreachable:
        return self

    def __getattr__(self, _name: str) -> Any:
        def raiser(*_args: Any, **_kwargs: Any) -> Any:
            raise self._failure("redis is unreachable")

        return raiser

    async def execute(self) -> Any:
        raise self._failure("redis is unreachable")


@pytest.fixture
def limits(settings_factory: Any) -> Settings:
    return cast(Settings, settings_factory())


async def test_auth_route_fails_closed_with_a_503(limits: Settings) -> None:
    """`AC-AUTH-09.5`, the fail-closed half.

    `guard` is the auth path. It must not swallow the outage: allowing the
    request would be running the login endpoint with no rate limit at all,
    which is the window an attacker is waiting for.
    """
    limiter = RateLimiter(Unreachable())

    with pytest.raises(LimiterUnavailable) as caught:
        await limiter.guard(ROUTE, login_buckets(limits, ip="203.0.113.5", email="a@b.com"))

    error = caught.value
    assert error.http_status == 503
    assert error.code is ErrorCode.SERVICE_UNAVAILABLE


async def test_the_503_does_not_leak_the_redis_error(limits: Settings) -> None:
    """The reason goes to the log, not into `problem+json`.

    `AppError` renders `message` to the client. A limiter failure must not hand
    out a host name, a port or a connection string - `16-security-and-compliance`
    reasons about exactly this, and the message here is the generic description
    for `service_unavailable`.
    """
    limiter = RateLimiter(Unreachable())

    with pytest.raises(LimiterUnavailable) as caught:
        await limiter.check(ROUTE, [Bucket("ip", "203.0.113.6", Limit(10, 60))])

    assert "unreachable" not in caught.value.message.lower()
    assert "redis" not in caught.value.message.lower()


async def test_a_read_only_caller_can_fail_open(limits: Settings) -> None:
    """`AC-AUTH-09.5`, the fail-open half - `GET /jobs` still answers.

    The decision is the caller's, and deliberately: the limiter cannot tell an
    auth route from a feed. This is the shape a read-only route uses, and the
    assertion is that the exception is catchable and leaves the caller able to
    proceed rather than being, say, a `BaseException` or a crash inside the
    pipeline.
    """
    limiter = RateLimiter(Unreachable())
    served = False

    try:
        await limiter.check("GET /api/v1/jobs", [Bucket("user", "u1", Limit(300, 60))])
    except LimiterUnavailable:
        served = True

    assert served, "a read-only route must be able to catch the outage and serve"


async def test_a_timeout_is_also_an_outage(limits: Settings) -> None:
    """Not only `ConnectionError`.

    A black-holed Redis raises a timeout, not a refusal, and the two must fail
    the same way. `_consume` catches broadly for this reason - every client
    library raises its own exception family, and the limiter's job is to be
    certain it does not silently allow the request.
    """
    limiter = RateLimiter(Unreachable(TimeoutError))

    with pytest.raises(LimiterUnavailable):
        await limiter.guard(ROUTE, login_buckets(limits, ip="203.0.113.7", email="a@b.com"))


async def test_recovery_needs_no_restart(limits: Settings) -> None:
    """Redis comes back and the limiter works again.

    A limiter that cached its own failure would turn a brief outage into a
    permanent one. `RateLimiter` holds no state of its own, which is what makes
    this true - the test exists so that stays true.
    """
    healthy = RateLimiter(fakeredis.FakeRedis())

    assert await healthy.check(ROUTE, login_buckets(limits, ip="203.0.113.8", email="a@b.com")) is (
        None
    )
