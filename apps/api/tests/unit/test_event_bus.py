"""T-FOUND-09.2 - the bus (`01-foundations.md` §9).

`AC-FOUND-09.2`: "A handler that raises does not propagate to the publisher,
and the error is logged with the event name and `request_id`."

The reason this matters: a notification failing must not roll back the
application status change that caused it.
"""

from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

from app.core.events import Event, EventBus, UnregisteredEvent


class JobExpired(Event):
    name = "JobExpired"
    job_id: str


class ResumeExtracted(Event):
    name = "ResumeExtracted"
    user_id: str
    resume_id: str


def test_a_handler_receives_the_event():
    bus = EventBus()
    seen: list[Event] = []
    bus.subscribe(JobExpired, seen.append)

    bus.publish(JobExpired(job_id="01JOB"))

    assert len(seen) == 1
    assert isinstance(seen[0], JobExpired)
    assert seen[0].job_id == "01JOB"


def test_every_handler_runs():
    bus = EventBus()
    calls: list[str] = []
    bus.subscribe(JobExpired, lambda _: calls.append("first"))
    bus.subscribe(JobExpired, lambda _: calls.append("second"))

    bus.publish(JobExpired(job_id="01JOB"))

    assert calls == ["first", "second"]


def test_a_raising_handler_does_not_reach_the_publisher(caplog):
    """AC-FOUND-09.2."""
    bus = EventBus()
    reached: list[str] = []

    def explodes(_: Event) -> None:
        raise RuntimeError("the notification provider is down")

    bus.subscribe(JobExpired, explodes)
    bus.subscribe(JobExpired, lambda _: reached.append("still ran"))

    with caplog.at_level(logging.ERROR, logger="app.events"):
        bus.publish(JobExpired(job_id="01JOB"), request_id="01REQ")

    # The publisher's transaction is untouched, and the later handler still ran.
    assert reached == ["still ran"]
    assert "event handler failed" in caplog.text
    assert "the notification provider is down" in caplog.text


def test_the_failure_is_logged_with_the_event_and_request_id(caplog):
    """AC-FOUND-09.2 - "logged with the event name and `request_id`"."""
    bus = EventBus()
    bus.subscribe(JobExpired, lambda _: (_ for _ in ()).throw(RuntimeError("boom")))

    with caplog.at_level(logging.ERROR, logger="app.events"):
        bus.publish(JobExpired(job_id="01JOB"), request_id="01REQUEST")

    record = next(r for r in caplog.records if r.message == "event handler failed")
    assert record.event == "JobExpired"
    assert record.request_id == "01REQUEST"
    assert record.exc_info is not None, "the traceback is what makes the log useful"


def test_publishing_with_no_subscriber_is_fine():
    """Most events have one consumer; `ProfileConfirmed` has none in R1."""
    EventBus().publish(JobExpired(job_id="01JOB"))


def test_an_unregistered_event_cannot_be_published():
    """§9 - the reaction graph is readable in one file, so an event outside it
    would be invisible there."""

    class Improvised(Event):
        name = "Improvised"
        thing: str

    bus = EventBus()
    with pytest.raises(UnregisteredEvent):
        bus.publish(Improvised(thing="x"))
    with pytest.raises(UnregisteredEvent):
        bus.subscribe("Improvised", lambda _: None)


def test_events_are_frozen():
    """A handler that could mutate the event would change what later handlers
    see, which makes the order of `register_all` load-bearing."""
    event = ResumeExtracted(user_id="01USER", resume_id="01RESUME")
    with pytest.raises(ValidationError):
        event.user_id = "someone else"


def test_an_unknown_field_is_refused():
    with pytest.raises(ValidationError):
        ResumeExtracted(user_id="01USER", resume_id="01RESUME", extra="surprise")  # type: ignore[call-arg]


def test_handlers_for_reports_the_wiring():
    """`register_all` is meant to be readable; so is what it produced."""
    bus = EventBus()
    handler = list.append
    bus.subscribe(JobExpired, handler)  # type: ignore[arg-type]
    assert len(bus.handlers_for("JobExpired")) == 1
    assert bus.handlers_for("PackApproved") == ()
