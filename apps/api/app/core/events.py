"""In-process domain events - `FOUND-09`.

`01-foundations.md` §9: "Let modules react to each other without importing each
other, and make the reaction graph readable in one file."

Five constraints, and the failure each removes:

* **Events carry IDs and primitives only.** A document in an event is a
  document that has already gone stale by the time the handler reads it, and a
  nested aggregate is a second definition of a shape `17-data-model.md` owns.
  Enforced at construction (`AC-FOUND-09.3`), not by review.
* **A handler must not do work inline. It enqueues and returns**
  (`AC-FOUND-09.1`). This keeps the publisher's latency independent of how many
  subscribers exist, and makes retries the queue's problem rather than the
  request's.
* **A handler exception is logged and swallowed** (`AC-FOUND-09.2`). A
  notification failing must not roll back the application status change that
  caused it.
* **Handlers are registered in one place**, `register_all`, so the whole
  cross-module reaction graph is one readable function.
* **Events are not a log.** Audit facts go to `audit_log` (`09-apply.md` §6)
  explicitly. Nothing here is persisted.

`docs/events.md` is generated from `R1_EVENTS` below (`AC-FOUND-09.5`), so the
table in §9 and the code cannot drift.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, model_validator

logger = logging.getLogger("app.events")

# What an event field may hold. `17-data-model.md` owns every shape more
# complex than these; an event references one by id.
PRIMITIVES = (str, int, float, bool, type(None))


class NonPrimitivePayload(TypeError):
    """An event field held something other than an id or a primitive.

    `01-foundations.md` §9: events carry "**IDs and primitives only** - no
    documents, no nested aggregates".
    """


class UnregisteredEvent(KeyError):
    """An event was published that `R1_EVENTS` does not declare.

    The reaction graph is meant to be readable in one place; an event that is
    not in it is invisible there.
    """


class Event(BaseModel):
    """The base every domain event inherits.

    Frozen, past-tense, and validated to carry nothing but primitives.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Set by each subclass to the name used in `R1_EVENTS`.
    name: ClassVar[str] = ""

    @model_validator(mode="after")
    def _primitives_only(self) -> Event:
        for field, value in self:
            if isinstance(value, PRIMITIVES):
                continue
            if isinstance(value, (list, tuple)) and all(
                isinstance(item, PRIMITIVES) for item in value
            ):
                continue
            raise NonPrimitivePayload(
                f"{type(self).__name__}.{field} is {type(value).__name__}; an event "
                "carries ids and primitives only, so a handler reads the current "
                "document rather than a stale copy (01-foundations.md §9)"
            )
        return self


@dataclass(frozen=True)
class EventSpec:
    """One row of §9's R1 event table."""

    name: str
    published_by: str
    consumed_by: tuple[str, ...]
    handler_action: str
    fields: tuple[str, ...]


# `01-foundations.md` §9, "R1 event set", transcribed. `docs/events.md` is
# generated from this and `tests/spec/test_events_doc.py` compares the two.
R1_EVENTS: tuple[EventSpec, ...] = (
    EventSpec(
        "ProfileUpdated",
        "profile",
        ("matching",),
        "enqueue `matching.rescore_user` (debounced 60 s)",
        ("user_id", "profile_version", "changed_paths"),
    ),
    EventSpec(
        "ProfileConfirmed",
        "profile",
        (),
        "(R2: completeness recompute)",
        ("user_id",),
    ),
    EventSpec(
        "ResumeExtracted",
        "resume",
        ("profile",),
        "enqueue `profile.stage_extraction`",
        ("user_id", "resume_id"),
    ),
    EventSpec(
        "JobsIngested",
        "jobs",
        ("matching",),
        "enqueue `matching.score_new_jobs`",
        ("connector", "job_ids"),
    ),
    EventSpec(
        "JobExpired",
        "jobs",
        ("tracker",),
        "enqueue `tracker.flag_expired_listing`",
        ("job_id",),
    ),
    EventSpec(
        "ApplicationStatusChanged",
        "tracker",
        ("notifications",),
        "enqueue `notifications.reconcile_reminders`",
        ("application_id", "user_id", "from_status", "to_status"),
    ),
    EventSpec(
        "PackApproved",
        "apply",
        ("tracker",),
        "enqueue `tracker.append_timeline`",
        ("user_id", "application_id", "pack_id", "content_hash"),
    ),
    EventSpec(
        "AppliedConfirmed",
        "apply",
        ("tracker", "notifications"),
        "transition to `applied`; schedule follow-up",
        ("user_id", "application_id", "applied_at"),
    ),
    # The two auth events. `02-auth-and-account.md` §8 named auth as their
    # publisher and `AUTH-01`'s Outputs required `UserRegistered` while §9's
    # table listed neither, so `publish` rejected a name the specification
    # demanded - `AUTH-01` was unbuildable until §9 gained these rows.
    #
    # No consumer in R1, and declared anyway: the point of this table is that
    # the reaction graph is readable in one file, and "nothing happens when
    # someone registers" is better read as an answer than inferred from an
    # absence.
    EventSpec(
        "UserRegistered",
        "auth",
        (),
        "none in R1",
        ("user_id",),
    ),
    # Handler action is **none** deliberately. A deletion that relied on an
    # in-process handler would be lost on a restart between the request and the
    # sweep, so `AUTH-07`'s cron reads `users.status` and
    # `deletion_requested_at`. This event notifies; it is never the mechanism.
    EventSpec(
        "UserDeletionRequested",
        "auth",
        (),
        "none in R1; `AUTH-07`'s cron scans `users`",
        ("user_id", "requested_at"),
    ),
)

EVENTS_BY_NAME = {spec.name: spec for spec in R1_EVENTS}

Handler = Callable[[Event], None]


class EventBus:
    """Synchronous in-process pub/sub. Not a broker (ADR-001).

    "extractable later, not distributed now" - so this is deliberately the
    smallest thing that supports the reaction graph.
    """

    def __init__(self, *, strict: bool = True) -> None:
        self._handlers: dict[str, list[Handler]] = {}
        self._strict = strict

    def subscribe(self, event: type[Event] | str, handler: Handler) -> None:
        name = event if isinstance(event, str) else event.name
        if self._strict and name not in EVENTS_BY_NAME:
            raise UnregisteredEvent(
                f"{name} is not in R1_EVENTS; add it there so the reaction graph "
                "stays readable in one place"
            )
        self._handlers.setdefault(name, []).append(handler)

    def handlers_for(self, name: str) -> Sequence[Handler]:
        return tuple(self._handlers.get(name, ()))

    def publish(self, event: Event, *, request_id: str = "") -> None:
        """Deliver to every handler. A handler that raises does not reach the caller.

        `AC-FOUND-09.2`: "A handler exception is logged and swallowed; it never
        fails the publisher's transaction."
        """
        name = type(event).name or type(event).__name__
        if self._strict and name not in EVENTS_BY_NAME:
            raise UnregisteredEvent(f"{name} is not in R1_EVENTS")

        for handler in self._handlers.get(name, ()):
            try:
                handler(event)
            except Exception:
                logger.exception(
                    "event handler failed",
                    extra={
                        "event": name,
                        "request_id": request_id,
                        "handler": getattr(handler, "__qualname__", repr(handler)),
                    },
                )


def register_all(bus: EventBus) -> EventBus:
    """The entire cross-module reaction graph, in one readable function.

    `01-foundations.md` §9: "Handlers are registered at app startup in one
    place." Each subscription arrives with the module that consumes the event -
    `profile` subscribes to `ResumeExtracted` in P2, `matching` to
    `JobsIngested` in P4 - so this grows down the phase order rather than being
    written speculatively.
    """
    return bus


EVENTS_DOC_HEADER = """# Domain events — generated from `app/core/events.py`

Do not edit. Regenerate with `make events-doc`.

`01-foundations.md` §9. A handler does nothing but enqueue; it never does work
inline, and an exception in one never reaches the publisher.

| Event | Published by | Consumed by | Handler action |
|---|---|---|---|
"""


def render_events_doc() -> str:
    """`AC-FOUND-09.5` - `docs/events.md` is generated and matches the table."""
    rows = []
    for spec in R1_EVENTS:
        fields = ", ".join(spec.fields)
        consumed = ", ".join(spec.consumed_by) if spec.consumed_by else "—"
        rows.append(
            f"| `{spec.name}{{{fields}}}` | {spec.published_by} | {consumed} | "
            f"{spec.handler_action} |"
        )
    return EVENTS_DOC_HEADER + "\n".join(rows) + "\n"


def payload_fields(name: str) -> tuple[str, ...]:
    return EVENTS_BY_NAME[name].fields


__all__ = [
    "R1_EVENTS",
    "Event",
    "EventBus",
    "EventSpec",
    "NonPrimitivePayload",
    "UnregisteredEvent",
    "payload_fields",
    "register_all",
    "render_events_doc",
]
