"""Rate limiting - `AUTH-09`.

`02-auth-and-account.md` §9: "Make credential stuffing and email-bombing
expensive without locking out a legitimate user behind a shared IP."

Three decisions shape this module.

**A sliding-window log, not a token bucket.** §9 says "Redis token bucket", and
this is a deviation I am recording rather than hiding. A token bucket's refill
is read-modify-write arithmetic, which is only safe inside a Lua script - and
`fakeredis`, which the suite uses as "a real Redis, in process" (`pyproject`),
does not implement `EVAL`. The alternatives were to add a native Lua binding to
the dependency set for one script, or to use a mechanism that is atomic in
plain Redis commands.

The log is that mechanism: `ZREMRANGEBYSCORE` + `ZADD` + `ZCARD` + `PEXPIRE` in
one `MULTI`/`EXEC`, which is atomic by transaction rather than by script. It is
also *stricter* than a bucket - a bucket permits a full-capacity burst after an
idle period, a log never permits more than N in any window - and it matches how
§9's criteria are phrased ("11 logins in a minute ... the 11th returns 429")
more exactly than a refilling bucket does.

**The spec should be amended to say so**, or this should be revisited if a
token bucket's burst allowance turns out to be wanted. `02-auth-and-account.md`
§9's first constraint is the line to change.

**Two dimensions, both enforced.** §9: an attacker rotating IPs is caught by the
account dimension, one hitting many accounts from a single IP by the IP
dimension. `check` therefore takes a *list* of buckets and refuses if any is
empty, and every dimension is consumed before the refusal is raised - see
`_consume_all` for why that matters to `AC-AUTH-09.3`.

**Fail closed, by the caller's choice.** A Redis outage raises
`LimiterUnavailable`. It is deliberately *not* converted to a 503 here: §9 wants
auth routes to fail closed and read-only routes to fail open, and only the route
knows which it is. `guard` is the fail-closed helper; a read-only caller
catches the exception instead.

The client's address is `client_ip`, and the trust rule there is the one place
this module knowingly departs from §9. See `Settings.TRUSTED_PROXY_CIDRS`.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import math
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.core import clock, metrics
from app.core.errors import AppError, ErrorCode

logger = logging.getLogger("app.ratelimit")


# The client is typed `Any`, matching `idempotency.RedisStore.__init__`.
#
# A `Protocol` was the first attempt and it does not survive contact with
# `redis.asyncio.Redis`: one class serves both the sync and async APIs, so its
# methods are declared returning `Awaitable[Any] | Any`, its key parameters as
# `bytes | str | memoryview`, and `zrange` takes six optional positionals
# between `end` and `withscores`. Any Protocol loose enough for the real client
# to satisfy is `(*args: Any, **kwargs: Any) -> Any`, which documents nothing.
#
# What the limiter needs is written here instead: `pipeline(transaction=True)`
# for `MULTI`/`EXEC` - that is where the atomicity comes from - plus `zrange`
# and `zrem` on the refusal path.


@dataclass(frozen=True)
class Limit:
    """A capacity and the window it refills over.

    Constructed from `Settings`, never from a literal - `AC-AUTH-09.6`, which
    `tests/spec/test_ratelimit_config.py` asserts by reading this file.
    """

    count: int
    window_seconds: int

    @property
    def window_ms(self) -> int:
        return self.window_seconds * 1000


@dataclass(frozen=True)
class Bucket:
    """One dimension of one route: which limit, and whose behaviour it counts."""

    #: `ip`, `email`, `account`, `user`. Becomes a metric label, so it is a
    #: small closed vocabulary rather than free text.
    dimension: str
    #: The subject, already hashed if it is personal data. Use `identifier()`.
    subject: str
    limit: Limit

    def key(self, route: str) -> str:
        """The Redis key for this bucket.

        The window length is part of the key, and that is not cosmetic. §9 gives
        most dimensions two windows - login is 10/min *and* 60/hour per IP - and
        those share a dimension and a subject. Keyed on those two alone, both
        windows would read and write one sorted set: every `check` would add two
        members to it, and a 10/min limit would refuse the sixth request. That
        is exactly what `tests/integration/test_rate_limits.py` caught.
        """
        return f"rl:{route}:{self.dimension}:{self.limit.window_seconds}:{self.subject}"


@dataclass(frozen=True)
class Refusal:
    """Which dimension ran out, and when it will not have."""

    dimension: str
    retry_after_seconds: int


class LimiterUnavailable(AppError):
    """`AC-AUTH-09.5` - Redis is down, so the auth route fails closed.

    An `AppError` with a 503, exactly like `IdempotencyUnavailable`, so the
    app's error handler renders it without every auth route needing an
    `except`. §9: "Redis unavailable: fail closed on auth routes (503), fail
    open on read-only routes. An unprotected login endpoint is worse than a
    brief outage."

    The read-only half is the caller's job, and deliberately so - this module
    cannot tell which kind of route it is serving. A read-only route catches
    this and proceeds; an auth route lets it propagate. `guard` is the
    fail-closed path.
    """

    code = ErrorCode.SERVICE_UNAVAILABLE
    http_status = 503


class RateLimited(AppError):
    """429, with `Retry-After`."""

    code = ErrorCode.RATE_LIMITED
    http_status = 429


def identifier(value: str) -> str:
    """A stable, non-reversible key for an email address.

    §9 counts "per account identifier (the submitted email, hashed)". Hashed
    because these keys outlive the request in Redis and appear in `MONITOR`
    output, and an email address is personal data (`FOUND-14`'s redaction list
    exists for the same reason).

    Case- and whitespace-folded first, so `A@B.com ` and `a@b.com` are one
    subject. Without that, the account dimension is bypassed by changing the
    capitalisation of the submitted address.
    """
    return hashlib.sha256(value.strip().casefold().encode("utf-8")).hexdigest()[:32]


def client_ip(
    *,
    peer: str | None,
    forwarded_for: str | None,
    cf_connecting_ip: str | None,
    trusted_cidrs: Sequence[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> str:
    """The address to hold responsible for this request.

    `AC-AUTH-09.4`: a forged `X-Forwarded-For` from a non-Cloudflare source is
    limited by its socket IP. That is what the empty-trust default does, and it
    is the behaviour §9 specifies.

    With `trusted_cidrs` populated, a forwarding header is believed only when
    the *peer* is in the list, and then only as far as the list reaches:
    `X-Forwarded-For` is walked from the right, discarding trusted hops, and
    the first untrusted address is the client. Walking from the right is the
    whole point - a proxy appends, so the leftmost entries are whatever the
    client sent and are attacker-controlled.

    Returns `"unknown"` when there is no address at all, which happens for an
    ASGI scope with no client (a test transport). One shared bucket for those
    is the safe direction: it limits rather than exempts.
    """
    if peer is None:
        return "unknown"
    if not trusted_cidrs or not _in_any(peer, trusted_cidrs):
        # Untrusted peer. Its own address is the only fact here; both headers
        # are hearsay.
        return peer

    # `CF-Connecting-IP` is a single address written by the edge, not a chain,
    # so there is nothing to walk. Preferred when present because Cloudflare
    # sets it authoritatively.
    if cf_connecting_ip:
        candidate = cf_connecting_ip.strip()
        if _is_address(candidate):
            return candidate

    for hop in reversed([h.strip() for h in (forwarded_for or "").split(",") if h.strip()]):
        if not _is_address(hop):
            # A malformed entry ends the walk. Continuing past it would let a
            # client hide its address behind a deliberate syntax error.
            break
        if not _in_any(hop, trusted_cidrs):
            return hop

    # Every hop was a trusted proxy, or there were none. The peer is the most
    # specific address left.
    return peer


def parse_cidrs(raw: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """`TRUSTED_PROXY_CIDRS` as networks.

    An unparseable entry is dropped with a warning rather than raising. The
    alternative is a typo in one CIDR taking the whole API down at boot, and the
    failure direction here is safe: an entry that does not parse is a proxy that
    is not trusted, which falls back to the socket address.
    """
    out: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for entry in (part.strip() for part in raw.split(",")):
        if not entry:
            continue
        try:
            out.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning("ignoring unparseable TRUSTED_PROXY_CIDRS entry", extra={"cidr": entry})
    return tuple(out)


def _is_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _in_any(value: str, networks: Iterable[ipaddress.IPv4Network | ipaddress.IPv6Network]) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return any(address in network for network in networks)


class RateLimiter:
    """§9's limiter.

    The client is injected (`01-foundations.md` §2: no module reads the
    environment), which is also what lets the Redis-down path be tested without
    taking a real Redis down.
    """

    def __init__(self, client: Any) -> None:
        self._redis = client

    async def check(self, route: str, buckets: Sequence[Bucket]) -> Refusal | None:
        """Spend one token in every bucket. `None` when all had one.

        Every dimension is consumed even once one has refused, and that is
        `AC-AUTH-09.3`: the counters must move identically for a wrong password
        and a nonexistent account. If this returned at the first empty bucket,
        the *set* of buckets that advanced would depend on which dimension ran
        out first, and an attacker could read account existence out of the
        limiter's own timing. The limiter must not become the oracle that §1's
        enumeration rule closes.
        """
        refusals = await self._consume_all(route, buckets)
        if not refusals:
            return None
        # The longest wait, so a client that respects `Retry-After` comes back
        # once rather than once per dimension.
        worst = max(refusals, key=lambda r: r.retry_after_seconds)
        for refusal in refusals:
            metrics.rate_limited.labels(route=route, dimension=refusal.dimension).inc()
        return worst

    async def guard(self, route: str, buckets: Sequence[Bucket]) -> None:
        """`check`, raising. The fail-closed path, for auth routes.

        `LimiterUnavailable` is left to propagate: `AC-AUTH-09.5` wants
        `POST /auth/login` to answer 503 when Redis is down, and the app's error
        handler turns it into one. An `except` here that allowed the request
        would be an unprotected login endpoint during a Redis outage.
        """
        refusal = await self.check(route, buckets)
        if refusal is None:
            return
        raise RateLimited(
            headers={"Retry-After": str(refusal.retry_after_seconds)},
            details={"retry_after_seconds": refusal.retry_after_seconds},
        )

    async def _consume_all(self, route: str, buckets: Sequence[Bucket]) -> list[Refusal]:
        refusals: list[Refusal] = []
        now_ms = int(clock.now().timestamp() * 1000)
        for bucket in buckets:
            allowed, retry_after_ms = await self._consume(bucket.key(route), bucket.limit, now_ms)
            if not allowed:
                refusals.append(
                    Refusal(
                        dimension=bucket.dimension,
                        # Ceiling, and never zero: a `Retry-After: 0` invites an
                        # immediate retry that is certain to be refused again.
                        retry_after_seconds=max(1, math.ceil(retry_after_ms / 1000)),
                    )
                )
        return refusals

    async def _consume(self, key: str, limit: Limit, now_ms: int) -> tuple[bool, int]:
        """Record this request in `key`'s window and say whether it fits.

        A refused request is *withdrawn* from the log. Leaving it in would mean
        a client that retries faster than the window keeps pushing its own
        unblock time forward and never recovers - the limit would stop being
        "N per window" and become "N, then silence for a window", which locks
        out the impatient legitimate user §9 exists to protect.
        """
        floor = now_ms - limit.window_ms
        # Unique per request: two requests in the same millisecond must be two
        # members, or the second silently overwrites the first and the window
        # under-counts.
        member = f"{now_ms}-{uuid.uuid4().hex}"
        try:
            pipe = self._redis.pipeline(transaction=True)
            pipe.zremrangebyscore(key, 0, floor)
            pipe.zadd(key, {member: now_ms})
            pipe.zcard(key)
            # Expire after a full window of silence. A key whose entries have
            # all aged out says nothing, so keeping it would hold memory for
            # every address that ever authenticated.
            pipe.pexpire(key, limit.window_ms)
            results = await pipe.execute()
            count = int(results[2])
            if count <= limit.count:
                return True, 0
            await self._redis.zrem(key, member)
            oldest = await self._redis.zrange(key, 0, 0, withscores=True)
        except Exception as exc:  # noqa: BLE001 - every client raises its own family
            # The reason goes to the log, not to the response. `AppError`
            # renders `message` into problem+json, and a client-side rate limit
            # failure must not hand out a connection string or a host name.
            logger.warning("rate limiter unavailable", exc_info=exc)
            raise LimiterUnavailable() from exc

        if not oldest:
            # Everything aged out between the refusal and this read. The window
            # is open again, so the shortest honest answer is "try now".
            return False, 0
        oldest_ms = int(oldest[0][1])
        return False, max(0, oldest_ms + limit.window_ms - now_ms)


# -- the policy --------------------------------------------------------------
#
# §9's R1 table, in one place, so "what is the limit on password reset" has a
# single answer that is read rather than remembered.
#
# The windows below are durations, not limits. `AC-AUTH-09.6` forbids a numeric
# literal *for a limit* in the limiter, and every capacity here arrives through
# `Limits`; naming the two window lengths is what keeps the table legible.

_MINUTE = 60
_HOUR = 60 * _MINUTE


class Limits(Protocol):
    """The `RATE_*` half of `Settings`, structurally.

    A Protocol rather than an import: no other module under `app/core/` imports
    `app.core.config`, and the reason is `01-foundations.md` §2 - configuration
    is instantiated once and injected, so a core primitive that reached for
    `Settings` itself would be the exception that makes the rule untestable.
    `Settings` satisfies this by having the attributes.
    """

    RATE_LOGIN_PER_MIN_IP: int
    RATE_LOGIN_PER_HOUR_IP: int
    RATE_LOGIN_PER_MIN_EMAIL: int
    RATE_LOGIN_PER_HOUR_EMAIL: int
    RATE_REGISTER_PER_HOUR_IP: int
    RATE_RESET_PER_HOUR_IP: int
    RATE_RESET_PER_HOUR_EMAIL: int
    RATE_VERIFY_RESEND_PER_HOUR_ACCOUNT: int
    RATE_REFRESH_PER_MIN_IP: int


def login_buckets(limits: Limits, *, ip: str, email: str) -> tuple[Bucket, ...]:
    """§9: login 10/min and 60/hour per IP, 5/min and 20/hour per email.

    The email is hashed by `identifier`, so a caller cannot accidentally put a
    raw address into a Redis key.
    """
    subject = identifier(email)
    return (
        Bucket("ip", ip, Limit(limits.RATE_LOGIN_PER_MIN_IP, _MINUTE)),
        Bucket("ip", ip, Limit(limits.RATE_LOGIN_PER_HOUR_IP, _HOUR)),
        Bucket("email", subject, Limit(limits.RATE_LOGIN_PER_MIN_EMAIL, _MINUTE)),
        Bucket("email", subject, Limit(limits.RATE_LOGIN_PER_HOUR_EMAIL, _HOUR)),
    )


def register_buckets(limits: Limits, *, ip: str) -> tuple[Bucket, ...]:
    """§9: registration 5/hour per IP.

    One dimension, because there is no account to count against yet - the
    address being registered is by definition not one we have.
    """
    return (Bucket("ip", ip, Limit(limits.RATE_REGISTER_PER_HOUR_IP, _HOUR)),)


def reset_buckets(limits: Limits, *, ip: str, email: str) -> tuple[Bucket, ...]:
    """§9: reset request 10/hour per IP, 3/hour per email.

    The email dimension is the email-bombing control: without it, a single
    address can be mailed a reset link ten times an hour from each of many IPs.
    """
    return (
        Bucket("ip", ip, Limit(limits.RATE_RESET_PER_HOUR_IP, _HOUR)),
        Bucket("email", identifier(email), Limit(limits.RATE_RESET_PER_HOUR_EMAIL, _HOUR)),
    )


def verify_resend_buckets(limits: Limits, *, account_id: str) -> tuple[Bucket, ...]:
    """§9: verification resend 3/hour per account.

    Keyed by account id, not by address: the account is known by the time a
    resend can be asked for, and an id is already non-personal.
    """
    return (
        Bucket(
            "account",
            account_id,
            Limit(limits.RATE_VERIFY_RESEND_PER_HOUR_ACCOUNT, _HOUR),
        ),
    )


def refresh_buckets(limits: Limits, *, ip: str) -> tuple[Bucket, ...]:
    """§9: refresh 30/min per IP."""
    return (Bucket("ip", ip, Limit(limits.RATE_REFRESH_PER_MIN_IP, _MINUTE)),)


__all__ = [
    "Bucket",
    "Limit",
    "Limits",
    "LimiterUnavailable",
    "RateLimited",
    "RateLimiter",
    "Refusal",
    "client_ip",
    "identifier",
    "login_buckets",
    "parse_cidrs",
    "refresh_buckets",
    "register_buckets",
    "reset_buckets",
    "verify_resend_buckets",
]
