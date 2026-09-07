"""Budgets, caching and degradation - `AI-03`.

`05-ai-layer.md` §3: "A runaway loop, a viral signup, or a badly-tuned top-N
cannot produce a surprise bill, and hitting a cap degrades the product in a way
that is specified per feature rather than improvised."

The second half of that sentence is the harder half, and it is what the
degradation matrix in `docs/spec/ai-budget.yaml` exists for. A cap that is only
a cap turns every AI feature into a 500 on the day it trips, which is a worse
product than one that never had the feature. Every one of the ten features
therefore has a written answer to four questions: what it does instead, what the
user sees, what is recorded, and how it recovers.

**The order of the checks is fixed** (§3.1): user, then feature, then global.
First failure wins, so a denial always has one unambiguous reason. The order is
not arbitrary - an abusive account should be stopped before it is allowed to
exhaust a shared budget, and a single feature's runaway should be attributed to
that feature rather than reported as a global outage.

**The pre-call check uses an estimate; the post-call record uses actuals.** The
estimate is deliberately pessimistic on output - it assumes the model produces
its maximum - so a single large call cannot overshoot a cap it was under when it
started. The actual replaces the estimate once the call returns.

**The cache is checked before the budget** (§3.1). A cache hit is free, so
denying one would save nothing and cost a user their result. It is what keeps
job enrichment and match rationale serving everyone during a cap breach, which
is the economics that makes those features affordable at all.

**Rate limits are not cost caps.** A per-provider token bucket at the provider's
requests-per-minute limit *queues* and retries; it never rejects. A burst of 200
enrichments drains slowly. Failing them would turn a provider's throttle into
our outage.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.ai.base import Feature
from app.ai.usage import DenyReason
from app.core import clock, metrics

logger = logging.getLogger("app.ai.budget")

#: `docs/spec/ai-budget.yaml` - normative, and the thing that parametrizes the
#: degradation tests. Read rather than transcribed: a matrix in a spec file and
#: a dict in a module are two copies of one contract.
MATRIX_FILE = Path(__file__).resolve().parents[4] / "docs" / "spec" / "ai-budget.yaml"

#: §3.1's states. `soft` is not a denial - it is a warning that the day is
#: going to end badly, delivered while there is still time to look.
SOFT_THRESHOLD_PCT = 80


class BudgetState(StrEnum):
    OK = "ok"
    SOFT = "soft"
    HARD = "hard"


#: The gauge `OPS-04` §4.2 exposes, as a number, because a gauge cannot hold a
#: string. Ordered by severity so a dashboard can threshold on it.
STATE_VALUE = {BudgetState.OK: 0, BudgetState.SOFT: 1, BudgetState.HARD: 2}


class AIBudgetExceeded(Exception):
    """Raised before the provider is contacted (`AC-AI-03.2`).

    Carries the reason and the reset, because every caller needs both: the
    reason to record in `ai_usage.deny_reason`, and the reset to put in a
    `Retry-After` or to tell the user when to come back.
    """

    def __init__(self, feature: Feature | str, reason: DenyReason, resets_at: datetime) -> None:
        super().__init__(f"{feature} denied by the {reason} cap until {resets_at.isoformat()}")
        self.feature = str(feature)
        self.reason = reason
        self.resets_at = resets_at

    @property
    def retry_after_seconds(self) -> int:
        """`AC-AI-03.11` - seconds until the UTC reset, never negative."""
        return max(0, int((self.resets_at - clock.now()).total_seconds()))


# -- the day boundary --------------------------------------------------------


def utc_day(at: datetime | None = None) -> date:
    """The day every counter is keyed to.

    UTC, not the user's timezone (HR-10). A cap that reset at local midnight
    would reset at a different instant for each user, and the *global* cap
    cannot be in ten timezones at once.
    """
    return (at or clock.now()).astimezone(UTC).date()


def next_reset(at: datetime | None = None) -> datetime:
    """00:00 UTC tomorrow. §3.1: "Recovery is automatic at the next UTC day
    boundary. No feature requires a manual reset"."""
    moment = (at or clock.now()).astimezone(UTC)
    return datetime.combine(moment.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)


def global_key(day: date) -> str:
    return f"ai:spend:global:{day.isoformat()}"


def feature_key(feature: Feature | str, day: date) -> str:
    return f"ai:spend:feature:{feature}:{day.isoformat()}"


def user_key(user_id: str, day: date) -> str:
    return f"ai:calls:user:{user_id}:{day.isoformat()}"


# -- the counters ------------------------------------------------------------


class Counters:
    """The three Redis counters §3.1 names, behind one object.

    In-process by default so the whole of `AI-03` is testable without a Redis,
    and backed by one when a client is supplied. The keys are the same either
    way, which is what makes the memory implementation a stand-in rather than a
    different design.
    """

    def __init__(self, redis: Any = None) -> None:
        self._redis = redis
        self._spend: dict[str, Decimal] = {}
        self._calls: dict[str, int] = {}

    async def spend(self, key: str) -> Decimal:
        if self._redis is None:
            return self._spend.get(key, Decimal(0))
        raw = await self._redis.get(key)
        return Decimal(raw.decode() if isinstance(raw, bytes) else raw) if raw else Decimal(0)

    async def add_spend(self, key: str, amount: Decimal, ttl: timedelta) -> Decimal:
        if self._redis is None:
            self._spend[key] = self._spend.get(key, Decimal(0)) + amount
            return self._spend[key]
        # Stored as a string: Redis' own INCRBYFLOAT is binary floating point,
        # and a day of fractional-cent additions in float drifts far enough to
        # move a cap.
        current = await self.spend(key) + amount
        await self._redis.set(key, str(current), px=int(ttl.total_seconds() * 1000))
        return current

    async def calls(self, key: str) -> int:
        if self._redis is None:
            return self._calls.get(key, 0)
        raw = await self._redis.get(key)
        return int(raw) if raw else 0

    async def add_call(self, key: str, ttl: timedelta) -> int:
        if self._redis is None:
            self._calls[key] = self._calls.get(key, 0) + 1
            return self._calls[key]
        count = int(await self._redis.incr(key))
        if count == 1:
            await self._redis.pexpire(key, int(ttl.total_seconds() * 1000))
        return count


@dataclass(frozen=True)
class Caps:
    """§3.1's caps, from config.

    `per_feature` is optional per feature, which is why it is a mapping rather
    than a number: most features have no cap of their own and are bound by the
    global one.
    """

    global_usd: Decimal
    user_daily_calls: int
    per_feature_usd: Mapping[str, Decimal] = field(default_factory=dict)

    def for_feature(self, feature: Feature | str) -> Decimal | None:
        return self.per_feature_usd.get(str(feature))


@dataclass(frozen=True)
class Decision:
    """What the pre-call check concluded, and why."""

    allowed: bool
    reason: DenyReason | None = None
    state: BudgetState = BudgetState.OK
    resets_at: datetime | None = None

    def raise_if_denied(self, feature: Feature | str) -> None:
        if self.allowed:
            return
        assert self.reason is not None and self.resets_at is not None
        raise AIBudgetExceeded(feature, self.reason, self.resets_at)


class Budget:
    """The pre-call check and the post-call record.

    One object rather than free functions, because the counters and the caps
    have to agree about which day it is and which Redis they are talking to, and
    threading both through every call site is how they stop agreeing.
    """

    def __init__(self, caps: Caps, counters: Counters | None = None) -> None:
        self.caps = caps
        self.counters = counters or Counters()
        #: `AC-AI-03.9` - "`soft` raises exactly one alert per day per feature".
        self._alerted: set[tuple[str, date]] = set()

    # -- §3.1's fixed order --------------------------------------------------

    async def check(
        self,
        feature: Feature | str,
        *,
        estimate_usd: Decimal,
        user_id: str | None = None,
    ) -> Decision:
        """The three caps, in order, first failure wins.

        The order is the criterion (`AC-AI-03.7`): with all three breached the
        reason is `user`; with feature and global breached, `feature`; with only
        global, `global`.
        """
        day = utc_day()
        resets = next_reset()

        if user_id is not None and self.caps.user_daily_calls > 0:
            used = await self.counters.calls(user_key(user_id, day))
            if used >= self.caps.user_daily_calls:
                return self._deny(feature, DenyReason.USER, resets)

        feature_cap = self.caps.for_feature(feature)
        if feature_cap is not None and feature_cap > 0:
            spent = await self.counters.spend(feature_key(feature, day))
            if spent + estimate_usd > feature_cap:
                return self._deny(feature, DenyReason.FEATURE, resets)

        if self.caps.global_usd > 0:
            spent = await self.counters.spend(global_key(day))
            if spent + estimate_usd > self.caps.global_usd:
                return self._deny(feature, DenyReason.GLOBAL, resets)

        state = await self.state(feature)
        self._maybe_alert(feature, state, day)
        return Decision(allowed=True, state=state, resets_at=resets)

    def _deny(self, feature: Feature | str, reason: DenyReason, resets: datetime) -> Decision:
        metrics.ai_budget_state.labels(feature=str(feature)).set(STATE_VALUE[BudgetState.HARD])
        logger.warning(
            "ai call denied by a budget cap",
            extra={"feature": str(feature), "deny_reason": str(reason)},
        )
        return Decision(allowed=False, reason=reason, state=BudgetState.HARD, resets_at=resets)

    # -- §3.1's states -------------------------------------------------------

    async def state(self, feature: Feature | str) -> BudgetState:
        """`ok`, `soft` or `hard`, against whichever cap binds this feature.

        The binding cap is the feature's own if it has one, otherwise the
        global. Reporting against the global cap for a feature with a tighter
        one of its own would say `ok` right up to the moment that feature stops
        working.
        """
        day = utc_day()
        cap = self.caps.for_feature(feature)
        spent = (
            await self.counters.spend(feature_key(feature, day))
            if cap is not None and cap > 0
            else await self.counters.spend(global_key(day))
        )
        if cap is None or cap <= 0:
            cap = self.caps.global_usd
        if cap <= 0:
            return BudgetState.OK

        used_pct = (spent / cap) * 100
        if used_pct >= 100:
            return BudgetState.HARD
        if used_pct >= SOFT_THRESHOLD_PCT:
            return BudgetState.SOFT
        return BudgetState.OK

    def _maybe_alert(self, feature: Feature | str, state: BudgetState, day: date) -> None:
        metrics.ai_budget_state.labels(feature=str(feature)).set(STATE_VALUE[state])
        if state is not BudgetState.SOFT:
            return
        marker = (str(feature), day)
        if marker in self._alerted:
            return
        self._alerted.add(marker)
        logger.warning(
            "ai spend is above the soft threshold",
            extra={"feature": str(feature), "threshold_pct": SOFT_THRESHOLD_PCT},
        )

    def alerts_raised(self, feature: Feature | str | None = None) -> int:
        if feature is None:
            return len(self._alerted)
        return sum(1 for name, _ in self._alerted if name == str(feature))

    # -- the post-call record ------------------------------------------------

    async def record_actual(
        self,
        feature: Feature | str,
        *,
        cost_usd: Decimal | None,
        user_id: str | None = None,
    ) -> None:
        """§3.1: "Actual spend replaces the estimate in the counter after the
        call returns."

        An unpriced call adds nothing to the spend counters - there is nothing
        to add - but still counts against the user's call cap, which is a count
        rather than a cost and is exactly the protection that still works when
        the price is unknown.
        """
        day = utc_day()
        ttl = next_reset() - clock.now() + timedelta(hours=1)

        if user_id is not None:
            await self.counters.add_call(user_key(user_id, day), ttl)
        if cost_usd is None:
            return
        await self.counters.add_spend(global_key(day), cost_usd, ttl)
        await self.counters.add_spend(feature_key(feature, day), cost_usd, ttl)


def caps_from_settings(settings: Any) -> Caps:
    """§3.1's caps, read off `Settings`.

    A cap of zero means "no cap of its own", not "no spending allowed" - which
    is why the default is zero and why `check` skips a cap that is not positive.
    The other reading would deny every feature the moment the variable was left
    unset, which is the state every deployment starts in.
    """
    per_feature: dict[str, Decimal] = {}
    for feature in Feature:
        value = getattr(settings, f"AI_FEATURE_CAP_USD__{str(feature).upper()}", 0)
        if value:
            per_feature[str(feature)] = Decimal(str(value))
    return Caps(
        global_usd=Decimal(str(settings.AI_DAILY_COST_CAP_USD)),
        user_daily_calls=int(settings.AI_USER_DAILY_CALLS),
        per_feature_usd=per_feature,
    )


def estimate(
    input_tokens: int,
    max_output_tokens: int,
    input_price_per_million: Decimal,
    output_price_per_million: Decimal,
) -> Decimal:
    """§3.1's pre-call estimate.

    "Estimate = `measured_input_tokens × input_price + max_output_tokens ×
    output_price`, deliberately pessimistic on output so a single large call
    cannot overshoot a cap it was under."

    The pessimism is the design. An estimate based on the *expected* output
    would let one unusually long generation cross a cap that the check had just
    approved, and the overshoot would be discovered by the invoice.
    """
    million = Decimal(1_000_000)
    return (
        Decimal(input_tokens) * input_price_per_million
        + Decimal(max_output_tokens) * output_price_per_million
    ) / million


# -- §3.3's cache ------------------------------------------------------------


def cache_key(provider: str, model: str, prompt_version: str, payload: Any) -> str:
    """§3.3: `sha256(provider | model | prompt_version | canonicalized_input)`.

    Canonicalized, because two JSON encodings of one object are one input and a
    cache keyed on raw bytes would miss on every re-serialisation - which is
    every process restart.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    material = "|".join((provider, model, prompt_version, canonical))
    return "ai:cache:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


class ResponseCache:
    """`complete_json` and `embed` results, by content.

    In-process by default, Redis when given a client - the same arrangement as
    `Counters`, for the same reason. Entries expire; §3.3 sets the TTL from
    `AI_CACHE_TTL_DAYS`, default 7.
    """

    def __init__(self, redis: Any = None, ttl: timedelta = timedelta(days=7)) -> None:
        self._redis = redis
        self._ttl = ttl
        self._entries: dict[str, tuple[Any, datetime]] = {}
        self.hits = 0
        self.misses = 0

    async def get(self, key: str) -> Any | None:
        if self._redis is not None:
            raw = await self._redis.get(key)
            if raw is None:
                self.misses += 1
                return None
            self.hits += 1
            return json.loads(raw)

        entry = self._entries.get(key)
        if entry is None:
            self.misses += 1
            return None
        value, expires = entry
        if clock.now() >= expires:
            del self._entries[key]
            self.misses += 1
            return None
        self.hits += 1
        return value

    async def set(self, key: str, value: Any) -> None:
        if self._redis is not None:
            await self._redis.set(
                key, json.dumps(value, default=str), px=int(self._ttl.total_seconds() * 1000)
            )
            return
        self._entries[key] = (value, clock.now() + self._ttl)

    def __len__(self) -> int:
        return len(self._entries)


# -- §3.1's rate limiter -----------------------------------------------------


class TokenBucket:
    """A per-provider requests-per-minute limiter that queues, never rejects.

    §3.1: "A per-provider token bucket at the provider's requests-per-minute
    limit queues and retries rather than rejecting: a burst of 200 enrichments
    drains slowly, it does not fail."

    Rejecting would turn the provider's throttle into our outage, and the caller
    - a background enrichment task - has nothing better to do than wait.
    """

    def __init__(
        self,
        per_minute: int,
        *,
        sleep: Any = None,
        burst: int | None = None,
    ) -> None:
        if per_minute <= 0:
            raise ValueError("a rate limit of zero would queue every call forever")
        self.per_minute = per_minute
        self._interval = 60.0 / per_minute
        self._capacity = burst if burst is not None else per_minute
        self._tokens = float(self._capacity)
        self._updated = clock.now()
        self._sleep = sleep or asyncio.sleep
        self._lock = asyncio.Lock()
        self.waits = 0
        self.waited_seconds = 0.0

    async def acquire(self) -> None:
        """Return when a token is available, having slept if it was not."""
        async with self._lock:
            self._refill()
            if self._tokens < 1:
                delay = (1 - self._tokens) * self._interval
                self.waits += 1
                self.waited_seconds += delay
                await self._sleep(delay)
                self._refill()
                # After sleeping exactly long enough, one token exists even if
                # the clock is frozen - which it is in every test of this.
                self._tokens = max(self._tokens, 1.0)
            self._tokens -= 1

    def _refill(self) -> None:
        now = clock.now()
        elapsed = (now - self._updated).total_seconds()
        if elapsed > 0:
            self._tokens = min(float(self._capacity), self._tokens + elapsed / self._interval)
            self._updated = now


# -- §3.2's degradation matrix -----------------------------------------------


@dataclass(frozen=True)
class Degradation:
    """One row of §3.2, as written in `ai-budget.yaml`."""

    feature: str
    tier: str
    degradation: str
    user_visible: str
    surfaces_error: bool
    recovery: str
    sets: Mapping[str, Any] = field(default_factory=dict)
    http_status: int | None = None
    error_code: str | None = None
    retry_after: str | None = None
    backfill_task: str | None = None
    backfilled: bool = True
    backfill_reason: str = ""
    preserves_user_edits: bool = False
    retry_window_hours: int | None = None


@dataclass(frozen=True)
class Matrix:
    """`ai-budget.yaml`, loaded.

    Loaded rather than transcribed. §3.2's table is normative, and a second copy
    in a module is a second thing to keep true - which is the failure
    `AC-AI-03.12` exists to catch from the other direction.
    """

    features: Mapping[str, Degradation]
    deny_precedence: Sequence[str]
    invariants: Sequence[Mapping[str, str]]

    def __getitem__(self, feature: Feature | str) -> Degradation:
        try:
            return self.features[str(feature)]
        except KeyError as exc:
            raise KeyError(
                f"{feature} has no row in ai-budget.yaml. §3.2 is the complete "
                "contract for what a feature does when it is denied; a feature "
                "without a row would default to an error, which is the one "
                "behaviour the matrix exists to forbid."
            ) from exc


def load_matrix(path: Path = MATRIX_FILE) -> Matrix:
    import yaml

    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    rows: dict[str, Degradation] = {}
    for name, entry in (document.get("features") or {}).items():
        rows[str(name)] = Degradation(
            feature=str(name),
            tier=str(entry["tier"]),
            degradation=str(entry["degradation"]),
            user_visible=str(entry["user_visible"]),
            surfaces_error=bool(entry["surfaces_error"]),
            recovery=str(entry["recovery"]),
            sets=entry.get("sets") or {},
            http_status=entry.get("http_status"),
            error_code=entry.get("error_code"),
            retry_after=entry.get("retry_after"),
            backfill_task=entry.get("backfill_task"),
            backfilled=bool(entry.get("backfilled", True)),
            backfill_reason=str(entry.get("backfill_reason", "")),
            preserves_user_edits=bool(entry.get("preserves_user_edits", False)),
            retry_window_hours=entry.get("retry_window_hours"),
        )
    return Matrix(
        features=rows,
        deny_precedence=list(document.get("deny_precedence") or []),
        invariants=list(document.get("invariants") or []),
    )


MATRIX = load_matrix()


__all__ = [
    "MATRIX",
    "MATRIX_FILE",
    "SOFT_THRESHOLD_PCT",
    "STATE_VALUE",
    "AIBudgetExceeded",
    "Budget",
    "BudgetState",
    "Caps",
    "Counters",
    "Decision",
    "Degradation",
    "Matrix",
    "ResponseCache",
    "TokenBucket",
    "cache_key",
    "caps_from_settings",
    "estimate",
    "feature_key",
    "global_key",
    "load_matrix",
    "next_reset",
    "user_key",
    "utc_day",
]
