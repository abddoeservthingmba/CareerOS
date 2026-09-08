"""Usage accounting and provenance - `AI-04`.

`05-ai-layer.md` §4: "Every model call is attributable to a feature, a user, a
model, and a cost; every artifact a model produced can be traced to the exact
prompt and model that produced it (HR-9)."

**Every call writes exactly one row.** Success, failure, repair, cache hit,
budget denial - all six outcomes. A feature that quietly does nothing is
indistinguishable from a bug, and a denial that writes no row is a cost saving
nobody can see and a degradation nobody can explain to the user who noticed it.

**The write cannot fail the feature.** §4: "It is fire-and-forget with a bounded
in-process buffer flushed by the worker; a full buffer drops rows and increments
a counter rather than blocking." The order of harms is explicit: losing an
accounting row is bad, and failing a user's pack generation because the
accounting database hiccuped is worse. So the buffer is bounded, the drop is
counted, and the counter is what tells an operator the books are incomplete.

**`est_cost_usd` is a float here, and only here.** `shared/money.py`'s rule is
that money is a minor-unit integer, because a salary that drifts by a cent is a
bug. This field is not money the product owes anyone: it is an estimate in
fractions of a cent - a single 800-token call costs about $0.0002 - and cents
cannot hold it. `17-data-model.md` §2.12 writes it as a float for that reason.
The `Decimal` arithmetic happens in `pricing.py`; the float is the last step.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import Field
from pymongo import ASCENDING, IndexModel

from app.ai.base import Feature
from app.core import clock, metrics
from app.core.documents import BaseDoc

#: §3's TTL and §5's retention table, as one number. 400 days rather than 395
#: so a "last 13 months" query has a full final month rather than a partial one
#: - a monthly cost chart whose oldest bar is two-thirds of a month looks like a
#: drop in spend.
USAGE_RETENTION_DAYS = 400

logger = logging.getLogger("app.ai.usage")


class Outcome(StrEnum):
    """`17-data-model.md` §2.12's six.

    "needed for `12-admin.md` §2 and to know whether repair retries are eating
    the budget. **There is no stored `cached` boolean**: v2.0 had both, and two
    fields that can disagree about one fact eventually will."
    """

    OK = "ok"
    INVALID_JSON = "invalid_json"
    REPAIRED = "repaired"
    PROVIDER_ERROR = "provider_error"
    BUDGET_DENIED = "budget_denied"
    CACHE_HIT = "cache_hit"

    @property
    def cached(self) -> bool:
        """Derived, never stored (`17-data-model.md` §2.12, finding F5)."""
        return self is Outcome.CACHE_HIT

    @property
    def contacted_provider(self) -> bool:
        """Whether this outcome means money was actually spent."""
        return self in (Outcome.OK, Outcome.REPAIRED, Outcome.INVALID_JSON, Outcome.PROVIDER_ERROR)


class DenyReason(StrEnum):
    """Which cap refused, in `05-ai-layer.md` §3.1's fixed precedence.

    One unambiguous reason per denial: "an abusive account should be stopped
    before it is allowed to exhaust a shared budget, and a single feature's
    runaway should be attributed to that feature rather than reported as a
    global outage."
    """

    USER = "user"
    FEATURE = "feature"
    GLOBAL = "global"


class AiUsage(BaseDoc):
    """`17-data-model.md` §2.12, field for field.

    Not a `UserOwnedDoc`: a row exists for calls with no user - a job
    enrichment serves everyone who sees the job - and `user_id` is nullable
    here for exactly that reason.
    """

    at: datetime = Field(default_factory=clock.now)
    provider: str
    model: str
    feature: str
    user_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    #: `None` when the model is unpriced (`AC-AI-04.3`). Never zero for an
    #: unknown price: zero says "this was free", which is a claim.
    est_cost_usd: float | None = None
    latency_ms: int = 0
    outcome: Outcome
    prompt_version: str | None = None
    deny_reason: DenyReason | None = None

    class Settings:
        name = "ai_usage"
        indexes = [
            # §3 lists `at` twice for this collection - once "plain | daily
            # aggregation" and once "TTL 400 d | 13-month retention". Mongo
            # cannot hold two indexes on one key pattern, and it does not need
            # to: a TTL index *is* an ordinary single-field index that
            # additionally expires, so one declaration serves both rows. Two
            # would be a `IndexOptionsConflict` at boot.
            IndexModel(
                [("at", ASCENDING)],
                name="at_ttl",
                expireAfterSeconds=USAGE_RETENTION_DAYS * 86_400,
            ),
            # Per-feature cost, which is what `12-admin.md` §2's dashboard and
            # `AI-03`'s cap arithmetic both read.
            IndexModel([("feature", ASCENDING), ("at", ASCENDING)], name="feature_at"),
        ]


def build_row(
    *,
    provider: str,
    model: str,
    feature: Feature | str,
    outcome: Outcome,
    user_id: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    est_cost_usd: Decimal | None = None,
    latency_ms: int = 0,
    prompt_version: str | None = None,
    deny_reason: DenyReason | None = None,
) -> dict[str, Any]:
    """One row, as a plain dict.

    A dict rather than the `Document`, so the buffer can be filled before Beanie
    is initialised and so a test can read a row without a database. The document
    is what the flush writes.
    """
    if outcome is Outcome.BUDGET_DENIED and deny_reason is None:
        raise ValueError(
            "a budget denial must name which cap refused; `deny_reason` is what "
            "makes a denial explainable rather than a mystery outage"
        )
    if outcome is not Outcome.BUDGET_DENIED and deny_reason is not None:
        raise ValueError(f"{outcome} is not a denial, so it has no deny_reason")

    return {
        "at": clock.now(),
        "provider": provider,
        "model": model,
        "feature": str(feature),
        "user_id": user_id,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "est_cost_usd": None if est_cost_usd is None else float(est_cost_usd),
        "latency_ms": latency_ms,
        "outcome": outcome,
        "prompt_version": prompt_version,
        "deny_reason": deny_reason,
    }


class UsageRecorder:
    """The bounded, fire-and-forget buffer §4 describes.

    Bounded because the alternative is an unbounded one, and an unbounded buffer
    in front of a database that has stopped answering is how a memory limit gets
    hit during an incident that was previously only an accounting problem.

    Dropping is counted, not silent. `dropped` is what tells an operator the
    books are incomplete for a window - which is a different and much less
    alarming statement than "spend fell off a cliff".
    """

    def __init__(self, capacity: int = 10_000) -> None:
        self._buffer: deque[dict[str, Any]] = deque()
        self._capacity = capacity
        self.dropped = 0

    def record(self, row: dict[str, Any]) -> None:
        """Never raises. That is the entire contract (`AC-AI-04.4`)."""
        try:
            self._observe(row)
            if len(self._buffer) >= self._capacity:
                self.dropped += 1
                logger.warning(
                    "ai_usage buffer is full; dropping a row",
                    extra={"feature": row.get("feature"), "dropped": self.dropped},
                )
                return
            self._buffer.append(row)
        except Exception:  # noqa: BLE001 - accounting must never fail a feature
            self.dropped += 1
            logger.exception("could not buffer an ai_usage row")

    def _observe(self, row: dict[str, Any]) -> None:
        """The metric families `OPS-04` §4.2 names, from the same row.

        Written here rather than at each call site, so a feature added later
        cannot report usage without reporting cost.
        """
        feature = str(row.get("feature", ""))
        model = str(row.get("model", ""))
        if row.get("input_tokens"):
            metrics.ai_tokens.labels(feature=feature, model=model, kind="input").inc(
                int(row["input_tokens"])
            )
        if row.get("output_tokens"):
            metrics.ai_tokens.labels(feature=feature, model=model, kind="output").inc(
                int(row["output_tokens"])
            )
        cost = row.get("est_cost_usd")
        if cost:
            metrics.ai_cost_usd.labels(feature=feature).inc(float(cost))

    def pending(self) -> int:
        return len(self._buffer)

    def drain(self) -> list[dict[str, Any]]:
        """Take everything buffered. The worker's flush calls this."""
        taken = list(self._buffer)
        self._buffer.clear()
        return taken

    async def flush(self) -> int:
        """Write the buffer to `ai_usage`.

        A failure puts nothing back: rows that could not be written are counted
        as dropped rather than retried forever, because a retry loop in front of
        a database that is down is the thing that turns an accounting outage
        into an application outage.
        """
        rows = self.drain()
        if not rows:
            return 0
        try:
            await AiUsage.insert_many([AiUsage(**row) for row in rows])
        except Exception:  # noqa: BLE001 - same rule as `record`
            self.dropped += len(rows)
            logger.exception("could not flush ai_usage rows", extra={"count": len(rows)})
            return 0
        return len(rows)


#: The process-wide recorder. One per process, like the metric registry, so a
#: feature does not have to be handed an accounting object to be accountable.
RECORDER = UsageRecorder()


def record(**kwargs: Any) -> dict[str, Any]:
    """Build and buffer one row. The call every feature makes."""
    row = build_row(**kwargs)
    RECORDER.record(row)
    return row


def total_cost(rows: Iterable[dict[str, Any]]) -> Decimal:
    """`AC-AI-04.5` - what the admin dashboard shows for a day.

    Unpriced rows contribute nothing to the sum and are counted separately by
    `pricing.unpriced_count`. Treating `None` as zero here would make the total
    look complete when it is not.
    """
    return sum(
        (Decimal(str(row["est_cost_usd"])) for row in rows if row.get("est_cost_usd")),
        Decimal(0),
    )


__all__ = [
    "RECORDER",
    "AiUsage",
    "DenyReason",
    "Outcome",
    "UsageRecorder",
    "build_row",
    "record",
    "total_cost",
]
