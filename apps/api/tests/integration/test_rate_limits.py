"""T-AUTH-09.1-.3 - both dimensions, and the limiter is not an oracle.

`02-auth-and-account.md` §9. Three criteria live here:

* `AC-AUTH-09.1` 11 logins in a minute from one IP: the 11th returns 429 with
  `Retry-After`.
* `AC-AUTH-09.2` 6 logins in a minute for one email from six different IPs: the
  6th returns 429.
* `AC-AUTH-09.3` Rate-limit counters increment identically for a wrong password
  and a nonexistent account.

Against `fakeredis`, for the reason `pyproject.toml` gives for having it: "A
real Redis, in process ... asserting that it is atomic against a hand-written
double would be asserting against my own assumption rather than against Redis."
The sorted-set window and its `MULTI`/`EXEC` are Redis semantics, so a stub
would be testing the stub.

**Scope note.** §9's criteria name `POST /auth/login`, and that route does not
exist yet - it arrives with `AUTH-02`. These tests drive the limiter through the
same `login_buckets` policy the route will use, so the limits and both
dimensions are asserted now; the criteria's *route-level* form binds when
`AUTH-02` wires `guard` into the handler. Recorded here rather than left as a
surprise, because a reader comparing this file to §9 will notice.
"""

from __future__ import annotations

from typing import Any, cast

import fakeredis.aioredis as fakeredis
import pytest

from app.core.config import Settings
from app.core.ratelimit import (
    Bucket,
    Limit,
    RateLimited,
    RateLimiter,
    identifier,
    login_buckets,
)

ROUTE = "POST /api/v1/auth/login"
EMAIL = "alice@example.com"


@pytest.fixture
def redis() -> Any:
    return fakeredis.FakeRedis()


@pytest.fixture
def limiter(redis: Any) -> RateLimiter:
    return RateLimiter(redis)


@pytest.fixture
def limits(settings_factory: Any) -> Settings:
    """Real `Settings`, so the limits under test are the shipped defaults."""
    return cast(Settings, settings_factory())


async def test_eleventh_login_from_one_ip_is_refused(
    limiter: RateLimiter, limits: Settings
) -> None:
    """`AC-AUTH-09.1`.

    Ten is the configured per-minute IP limit, so the assertion is written
    against `limits.RATE_LOGIN_PER_MIN_IP` rather than against `10`: a test
    with the number inlined would keep passing after someone retuned the limit
    and stop testing the limit.
    """
    allowed = limits.RATE_LOGIN_PER_MIN_IP
    # Each attempt uses a different email so the *email* dimension cannot be
    # what refuses; this criterion is about the IP dimension alone.
    for attempt in range(allowed):
        buckets = login_buckets(limits, ip="203.0.113.7", email=f"user{attempt}@example.com")
        assert await limiter.check(ROUTE, buckets) is None, f"attempt {attempt + 1} refused early"

    buckets = login_buckets(limits, ip="203.0.113.7", email="user-final@example.com")
    refusal = await limiter.check(ROUTE, buckets)
    assert refusal is not None
    assert refusal.dimension == "ip"
    # `Retry-After` must be a usable number of seconds, not zero - a client
    # that honours a zero retries immediately into a certain refusal.
    assert refusal.retry_after_seconds >= 1


async def test_retry_after_header_is_present_on_the_raised_error(
    limiter: RateLimiter, limits: Settings
) -> None:
    """`AC-AUTH-09.1`'s "with `Retry-After`" half, on the response path."""
    with pytest.raises(RateLimited) as caught:
        for attempt in range(limits.RATE_LOGIN_PER_MIN_IP + 1):
            await limiter.guard(
                ROUTE,
                login_buckets(limits, ip="198.51.100.9", email=f"u{attempt}@example.com"),
            )

    error = caught.value
    assert error.http_status == 429
    assert "Retry-After" in error.headers
    assert int(error.headers["Retry-After"]) >= 1


async def test_sixth_login_for_one_email_across_six_ips_is_refused(
    limiter: RateLimiter, limits: Settings
) -> None:
    """`AC-AUTH-09.2` - the dimension that catches a rotating attacker.

    Every attempt comes from a different address, so the IP dimension never
    accumulates. Only the account dimension can refuse, which is the point:
    §9's "an attacker rotating IPs is caught by the account dimension".
    """
    allowed = limits.RATE_LOGIN_PER_MIN_EMAIL
    for attempt in range(allowed):
        buckets = login_buckets(limits, ip=f"192.0.2.{attempt + 1}", email=EMAIL)
        assert await limiter.check(ROUTE, buckets) is None, f"attempt {attempt + 1} refused early"

    refusal = await limiter.check(
        ROUTE, login_buckets(limits, ip=f"192.0.2.{allowed + 1}", email=EMAIL)
    )
    assert refusal is not None
    assert refusal.dimension == "email"


async def test_the_long_window_is_enforced_on_its_own_terms(
    limiter: RateLimiter, limits: Settings
) -> None:
    """The hourly dimension exists and refuses at its own capacity.

    Not one of §9's numbered criteria, but §9 lists two windows per dimension
    and a per-minute limit alone permits 600 attempts an hour, so the long
    window needs its own coverage. Exercised alone: combining it with the
    per-minute bucket in one tight loop only proves the per-minute bucket
    works, because every iteration lands inside the same minute.
    """
    per_hour = limits.RATE_LOGIN_PER_HOUR_IP
    bucket = (Bucket("ip", "203.0.113.60", Limit(per_hour, 3600)),)

    refusals = [await limiter.check(ROUTE, bucket) for _ in range(per_hour + 1)]

    assert all(r is None for r in refusals[:per_hour])
    assert refusals[per_hour] is not None


async def test_two_windows_on_one_dimension_do_not_share_a_key(
    limiter: RateLimiter, redis: Any, limits: Settings
) -> None:
    """A regression test, for a bug the criteria above found.

    `login_buckets` returns two `ip` buckets - 10/min and 60/hour - which share
    a dimension and a subject and differ only in their window. Keyed on
    dimension and subject alone they addressed one sorted set, so every `check`
    wrote two members to it and the 10/min limit refused the *sixth* request.

    Asserting on the key set rather than on the refusal count, because the
    symptom was "off by a factor of two" and that is the kind of thing a
    capacity assertion can accidentally still satisfy.
    """
    await limiter.check(ROUTE, login_buckets(limits, ip="203.0.113.99", email=EMAIL))

    raw_keys = await redis.keys("rl:*")
    keys = {(raw.decode() if isinstance(raw, bytes) else str(raw)) for raw in raw_keys}

    # Four buckets, four distinct keys: two windows on each of two dimensions.
    assert len(keys) == 4
    # And each holds exactly one entry - the single request just made.
    for key in keys:
        assert int(await redis.zcard(key)) == 1


async def test_counters_move_identically_for_wrong_password_and_unknown_account(
    limiter: RateLimiter, redis: Any, limits: Settings
) -> None:
    """`AC-AUTH-09.3` - the limiter must not become the enumeration oracle.

    §1's rule is that "wrong password" and "no such account" are
    indistinguishable, and §9 extends it: "rate-limit state must not differ
    between them either - otherwise the limiter itself becomes the oracle."

    So this asserts on Redis, not on the return value. The observable an
    attacker has is how the limiter's own state advances, and the two cases must
    leave it in the same shape. Two separate addresses are used so the runs
    cannot contaminate each other; the comparison is of the resulting key sets
    and their cardinalities.
    """

    async def counters_after(ip: str, email: str) -> dict[str, int]:
        for _ in range(3):
            await limiter.check(ROUTE, login_buckets(limits, ip=ip, email=email))
        state: dict[str, int] = {}
        for raw in await redis.keys("rl:*"):
            key = raw.decode() if isinstance(raw, bytes) else str(raw)
            if ip in key or identifier(email) in key:
                # Normalise the subject out of the key so the two runs are
                # comparable; what must match is the *shape*, not the address.
                shape = key.replace(ip, "<ip>").replace(identifier(email), "<email>")
                state[shape] = int(await redis.zcard(key))
        return state

    # An account that exists and was given a wrong password, and one that does
    # not exist at all. The limiter cannot tell them apart, and that is the
    # assertion: it is called identically in both cases by design.
    wrong_password = await counters_after("198.51.100.20", "real-user@example.com")
    unknown_account = await counters_after("198.51.100.21", "no-such-user@example.com")

    assert wrong_password == unknown_account
    # And it did something - an assertion that two empty dicts match would pass
    # for a limiter that never counted anything.
    assert wrong_password
    assert set(wrong_password.values()) == {3}
