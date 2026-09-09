"""Metrics - `FOUND-14`, `OPS-04` §4.2.

`01-foundations.md` §14: "`/metrics` in Prometheus format, protected by
`METRICS_TOKEN`. Required metrics: request latency histogram by route and
status; queue depth by queue; task duration and outcome by task; connector run
outcome by connector; AI tokens and cost by feature and model; reminders sent by
type and channel."

`15-infra-and-ops.md` §4.2 names seven families and, for each, the question it
exists to answer. That framing is the whole discipline here: a metric nobody has
a question for is a time series that costs money to store and is never looked
at, and a question nobody has a metric for is an outage discovered by a user.

**Labels are bounded, deliberately.** `route` is the *template* -
`/api/v1/applications/{id}/pack` - never the resolved path. A label whose values
are user ids is a cardinality explosion that takes the monitoring system down,
and it is also a list of every id in the system, readable by anyone with a
dashboard.

**The token is not decoration.** `/metrics` describes the shape of the system:
which routes exist, how much AI spend there is, how many reminders go out. It is
the reconnaissance step of an attack and the competitive-intelligence feed of a
rival, in one endpoint. 401 without a valid one (`AC-FOUND-14.3`).

Some of these are written by code that does not exist yet - no connector runs,
no AI call, no reminder. They are declared here anyway, because a metric that
appears the day the feature ships is a metric with no history on the day the
feature first misbehaves, and `AC-FOUND-14.3` says all seven families are
exposed.
"""

from __future__ import annotations

import hmac
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from app.core.errors import ErrorCode

#: Its own registry rather than the process-global default. Two apps in one test
#: session would otherwise raise on duplicate registration, and - worse - a
#: metric registered by an imported library would appear in ours.
REGISTRY = CollectorRegistry()

#: `15-infra-and-ops.md` §4.2's latency buckets. Chosen around the budgets that
#: matter rather than the library default: the interesting questions are "is the
#: feed under 300 ms" and "is anything over 2 s", and the default buckets answer
#: neither precisely.
LATENCY_BUCKETS = (0.01, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "Is the API meeting its latency budget",
    labelnames=("route", "status"),
    buckets=LATENCY_BUCKETS,
    registry=REGISTRY,
)

queue_depth = Gauge(
    "queue_depth",
    "Is the worker keeping up",
    labelnames=("queue",),
    registry=REGISTRY,
)

task_duration_seconds = Histogram(
    "task_duration_seconds",
    "Which background job is slow or failing",
    labelnames=("task", "outcome"),
    buckets=LATENCY_BUCKETS,
    registry=REGISTRY,
)

connector_run = Counter(
    "connector_run",
    "Is each source still delivering",
    labelnames=("connector", "outcome"),
    registry=REGISTRY,
)

connector_items = Counter(
    "connector_items",
    "How much each source delivered",
    labelnames=("connector", "kind"),
    registry=REGISTRY,
)

ai_tokens = Counter(
    "ai_tokens",
    "What is the spend, by feature",
    labelnames=("feature", "model", "kind"),
    registry=REGISTRY,
)

ai_cost_usd = Counter(
    "ai_cost_usd",
    "What is the spend, by feature",
    labelnames=("feature",),
    registry=REGISTRY,
)

ai_budget_state = Gauge(
    "ai_budget_state",
    "Are users being degraded right now",
    labelnames=("feature",),
    registry=REGISTRY,
)

reminders_sent = Counter(
    "reminders_sent",
    "Is the last clause of the exit sentence actually working",
    labelnames=("type", "channel", "outcome"),
    registry=REGISTRY,
)

email_sent = Counter(
    "email_sent",
    "Transactional email delivery, by template and outcome (FOUND-16)",
    labelnames=("template", "outcome"),
    registry=REGISTRY,
)

#: `AUTH-09`'s named output: "a `rate_limited` metric by route".
#:
#: Labelled by dimension as well, because the operational question is never
#: just "are we shedding requests" - it is whether the account dimension is
#: firing (someone is being targeted) or the IP dimension (one source is
#: sweeping), and those want different responses.
#: The name comes from the enum member rather than a string literal, and not
#: only to satisfy `AC-FOUND-12.4`'s no-bare-code rule: the metric and the error
#: code are the same fact seen from two sides. A refused request increments this
#: and answers `rate_limited`, so if one is ever renamed the other has to move
#: with it, and this makes that automatic instead of a grep.
rate_limited = Counter(
    ErrorCode.RATE_LIMITED.value,
    "Requests refused by the limiter, by route and dimension (AUTH-09)",
    labelnames=("route", "dimension"),
    registry=REGISTRY,
)

#: `AC-AUTH-01.3` names this one: with the breach service returning 503,
#: "registration succeeds and `breach_check_unavailable` is incremented".
#:
#: Unlabelled, and that is on purpose. The only question it answers is "are we
#: currently registering people without checking their passwords", which is a
#: yes-or-no about one third party. A label would invite putting the prefix on
#: it, and five hex characters of a SHA-1 next to a timestamp is a narrowing
#: hint about a specific password.
breach_check_unavailable = Counter(
    "breach_check_unavailable",
    "Registrations allowed without a breach check, because the service was down (AUTH-01)",
    registry=REGISTRY,
)

#: The seven `OPS-04` §4.2 names, as families. `AC-FOUND-14.3` requires all of
#: them to be exposed, so the list is here rather than in the test - a test that
#: kept its own copy would be asserting against itself.
REQUIRED_FAMILIES: tuple[str, ...] = (
    "http_request_duration_seconds",
    "queue_depth",
    "task_duration_seconds",
    "connector_run",
    "ai_tokens",
    "ai_budget_state",
    "reminders_sent",
)


def render() -> bytes:
    """The Prometheus exposition text."""
    return generate_latest(REGISTRY)


def content_type() -> str:
    """The Prometheus text exposition type, matching `generate_latest`.

    Not the OpenMetrics one: the two constants look interchangeable and are not,
    and a scraper told it is receiving OpenMetrics while being handed Prometheus
    text rejects the payload with a parse error that names neither format.
    """
    return CONTENT_TYPE_LATEST


def token_matches(presented: str, configured: str) -> bool:
    """`AC-FOUND-14.3` - a constant-time comparison, and no blank-token bypass.

    An unset `METRICS_TOKEN` denies everything rather than allowing it. The
    other way round, a deployment that forgot the variable would publish its
    whole shape to the internet and look perfectly healthy doing it.
    """
    if not configured:
        return False
    return hmac.compare_digest(presented, configured)


def route_label(request: Any) -> str:
    """The route *template*, never the resolved path.

    `/api/v1/applications/{id}/pack`, not `/api/v1/applications/01J.../pack`.
    A label whose values are ids is a cardinality explosion that takes the
    monitoring system down - and, before it does, a complete list of every id in
    the system readable by anyone with a dashboard login.
    """
    matched = request.scope.get("route")
    path = getattr(matched, "path", None)
    return str(path or "unmatched")


def observe_request(route: str, status: int, seconds: float) -> None:
    http_request_duration_seconds.labels(route=route, status=str(status)).observe(seconds)


def observe_task(task: str, outcome: str, seconds: float) -> None:
    task_duration_seconds.labels(task=task, outcome=outcome).observe(seconds)


def set_queue_depth(queue: str, depth: int) -> None:
    queue_depth.labels(queue=queue).set(depth)


__all__ = [
    "LATENCY_BUCKETS",
    "REGISTRY",
    "REQUIRED_FAMILIES",
    "ai_budget_state",
    "ai_cost_usd",
    "ai_tokens",
    "connector_items",
    "connector_run",
    "content_type",
    "email_sent",
    "http_request_duration_seconds",
    "observe_request",
    "observe_task",
    "queue_depth",
    "reminders_sent",
    "render",
    "route_label",
    "set_queue_depth",
    "task_duration_seconds",
    "token_matches",
]
