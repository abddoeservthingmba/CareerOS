"""Structured logging - `FOUND-14`.

`01-foundations.md` §14: "Every log line is a queryable JSON object correlated to
a request, and no line contains a secret or a person's data."

Two properties, and they pull in opposite directions. A line has to carry enough
to answer "what happened to this user's pack at 14:03" without carrying anything
that would make the log a copy of the user table.

The resolution is the same one the whole product uses for identity: **an id, not
a person**. `user_id` is in every authenticated line; the address that user signs
in with is in none of them. A support question starts from a `request_id` the
user was shown in an error, resolves to a `user_id`, and everything after that
is joinable - without a single line that means anything to someone who has only
the logs.

**`request_id` is bound once and follows automatically.** A `contextvar`, set by
the middleware, read by a structlog processor. The alternative - passing it down
through every call - is a parameter that gets dropped in the one function that
was written in a hurry, which is the function that eventually fails.

**JSON everywhere except local.** A human reading a terminal wants columns; a
log aggregator wants objects, and a "human-readable" line in production is a
line that has to be parsed with a regular expression six months later.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

import structlog

from app.core import clock
from app.core.redaction import scrub_event

#: Set by the request-id middleware and by the worker at the top of each task,
#: read by every line emitted underneath. A contextvar rather than a parameter,
#: because a parameter is a thing the one hurried function forgets.
_request_id: ContextVar[str] = ContextVar("request_id", default="")
_user_id: ContextVar[str] = ContextVar("user_id", default="")
_module: ContextVar[str] = ContextVar("module", default="")


def bind_request(request_id: str = "", user_id: str = "", module: str = "") -> None:
    """Attach the correlation fields for everything logged from here on."""
    if request_id:
        _request_id.set(request_id)
    if user_id:
        _user_id.set(user_id)
    if module:
        _module.set(module)


def clear_request() -> None:
    _request_id.set("")
    _user_id.set("")
    _module.set("")


def current_request_id() -> str:
    return _request_id.get()


def add_correlation(
    _logger: Any, _name: str, event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """`AC-FOUND-14.2` - every line carries the request it belongs to.

    Empty fields are dropped rather than written as `""`: a `user_id` of empty
    string in an aggregator is a value people filter on by accident, and an
    unauthenticated request genuinely has none.
    """
    for key, holder in (("request_id", _request_id), ("user_id", _user_id), ("module", _module)):
        value = holder.get()
        if value and key not in event:
            event[key] = value
    return event


def add_timestamp(
    _logger: Any, _name: str, event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """HR-10 - UTC, from `core.clock`, so a frozen-clock test sees frozen logs."""
    event.setdefault("at", clock.now().isoformat())
    return event


def redact(_logger: Any, _name: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """`AC-FOUND-14.1` - the last thing that happens before a line is rendered.

    Last on purpose. A redaction step in the middle of the chain can be undone
    by a later processor that adds a field, and the processor that adds fields
    is usually the one somebody wrote to help with debugging.
    """
    return scrub_event(dict(event))


def configure(*, environment: str = "local", level: str = "INFO") -> None:
    """Install the processor chain.

    Called once from the app factory and once from the worker's startup. Safe to
    call twice - structlog replaces its configuration - which matters because a
    test that builds two apps should not end up with two chains.
    """
    pretty = environment == "local"
    threshold = logging.getLevelNamesMapping().get(level, logging.INFO)

    # Everything a structlog line passes through before it is rendered. The
    # order is load-bearing twice: `format_exc_info` runs *before* `redact`, so
    # a traceback's own text is scrubbed like anything else - a traceback
    # carries every frame's arguments, which is how a password reaches a log
    # without anyone writing `logger.info(password)`; and `redact` runs last, so
    # a processor added later to help with debugging cannot re-introduce a field
    # after it has been cleaned.
    shared: list[Any] = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        add_correlation,
        add_timestamp,
        redact,
    ]

    renderer: Any = (
        structlog.dev.ConsoleRenderer(colors=False)
        if pretty
        else structlog.processors.JSONRenderer(sort_keys=True)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            add_correlation,
            add_timestamp,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            redact,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(threshold),
        # Through the standard library rather than straight to stdout, so that
        # structlog's lines and uvicorn's and pymongo's leave by one path. Two
        # paths means two chances to render, and only one of them redacts.
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=renderer,
            # Applied to records from libraries that never heard of structlog,
            # so a third-party line cannot bypass the redaction.
            foreign_pre_chain=shared,
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(threshold)


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)


__all__ = [
    "add_correlation",
    "add_timestamp",
    "bind_request",
    "clear_request",
    "configure",
    "current_request_id",
    "get_logger",
    "redact",
]
