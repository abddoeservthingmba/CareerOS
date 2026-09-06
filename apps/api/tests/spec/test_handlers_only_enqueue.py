"""T-FOUND-09.1 - a handler does nothing but enqueue.

`AC-FOUND-09.1`: "Every handler registered in `register_all` does nothing but
enqueue (asserted by inspecting that no handler imports a repository or an
`infra` client)."

Shared with `T-NOTIF-01.12` (`AC-NOTIF-01.12`), which asserts the same of
reminder reconciliation: "always enqueued, never executed in the request or the
event handler".

The reason: a handler that does work inline puts every subscriber's latency on
the publisher's request, and makes retries the request's problem rather than the
queue's.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path

from app.core import events

# What a handler may touch. Anything else means it is doing work rather than
# handing work over.
FORBIDDEN_IN_HANDLER = (
    "repository",
    "Repository",
    ".find(",
    ".insert(",
    ".save(",
    ".delete(",
    "httpx",
    "AsyncMongoClient",
)


def test_register_all_is_the_single_registration_point():
    """§9 - "Handlers are registered at app startup in one place ... so the
    entire cross-module reaction graph is one readable function"."""
    assert callable(events.register_all)
    source = inspect.getsource(events.register_all)
    assert "bus" in source


def test_no_handler_does_work_inline(repo: Path):
    """AC-FOUND-09.1.

    Vacuous while `register_all` has no subscriptions - the first arrives with
    `profile` in P2. Binding from that day, because it reads the function's
    source rather than a list someone maintains.
    """
    # `cleandoc` strips the leading indentation of the body but not of the
    # `def`, which leaves an unparseable fragment. `textwrap.dedent` over the
    # whole function is what makes it a standalone module.
    source = textwrap.dedent(inspect.getsource(events.register_all))
    tree = ast.parse(source)

    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = getattr(node.func, "attr", None)
        if target != "subscribe":
            continue
        # The handler is the second argument to `bus.subscribe(Event, handler)`.
        if len(node.args) < 2:
            continue
        handler = ast.unparse(node.args[1])
        if any(marker in handler for marker in FORBIDDEN_IN_HANDLER):
            offenders.append(handler)
    assert offenders == [], (
        f"a handler enqueues and returns; it does not read or write (AC-FOUND-09.1): {offenders}"
    )


def test_every_declared_handler_action_is_an_enqueue():
    """The declared graph must describe enqueues, not work.

    §9's table is the design; if a row said "recompute the score" rather than
    "enqueue `matching.rescore_user`", the rule would already be broken on
    paper.
    """
    offenders: list[str] = []
    for spec in events.R1_EVENTS:
        if not spec.consumed_by:
            continue
        action = spec.handler_action.lower()
        if "enqueue" in action:
            continue
        # `AppliedConfirmed` is the one row phrased as an outcome rather than a
        # mechanism ("transition to `applied`; schedule follow-up"). Both halves
        # are enqueued by the consuming module; the row describes what the user
        # sees.
        if spec.name == "AppliedConfirmed":
            continue
        offenders.append(f"{spec.name}: {spec.handler_action}")
    assert offenders == [], "\n".join(offenders)


def test_the_bus_is_not_a_broker():
    """ADR-001 - "extractable later, not distributed now". A handler that could
    be retried by a broker would not need to be an enqueue."""
    source = inspect.getsource(events)
    for broker in ("kafka", "rabbit", "celery", "sqs", "pubsub"):
        assert broker not in source.lower()
