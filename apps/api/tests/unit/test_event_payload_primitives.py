"""T-FOUND-09.3 - an event carries ids and primitives only.

`AC-FOUND-09.3`: "Publishing an event with a non-primitive field raises at
construction."

`01-foundations.md` §9: "carrying **IDs and primitives only** - no documents, no
nested aggregates". Two reasons, both practical: a document put on an event is
already stale by the time the handler reads it, and a nested aggregate is a
second definition of a shape `17-data-model.md` owns.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from app.core.events import Event, NonPrimitivePayload


class JobsIngested(Event):
    name = "JobsIngested"
    connector: str
    job_ids: list[str]


class Loose(Event):
    name = "JobExpired"
    job_id: str
    payload: object = None


class Nested(BaseModel):
    title: str


def test_primitives_are_accepted():
    event = JobsIngested(connector="adzuna", job_ids=["01A", "01B"])
    assert event.connector == "adzuna"
    assert event.job_ids == ["01A", "01B"]


def test_a_list_of_ids_is_accepted():
    """`JobsIngested{connector, job_ids}` is the shape §9 declares."""
    assert JobsIngested(connector="remotive", job_ids=[]).job_ids == []


def test_a_nested_model_raises():
    """AC-FOUND-09.3 - a document on an event is a stale document."""
    with pytest.raises(NonPrimitivePayload, match="ids and primitives only"):
        Loose(job_id="01JOB", payload=Nested(title="Senior Backend Engineer"))


def test_a_dict_raises():
    """A dict is how a document arrives when someone works around the rule."""
    with pytest.raises(NonPrimitivePayload):
        Loose(job_id="01JOB", payload={"title": "Senior Backend Engineer"})


def test_a_datetime_raises():
    """Deliberate. §9 says primitives; an instant travels as an ISO string or an
    epoch, so the handler cannot be handed a naive value that HR-10 forbids."""
    with pytest.raises(NonPrimitivePayload):
        Loose(job_id="01JOB", payload=datetime(2026, 9, 6, tzinfo=UTC))


def test_a_list_of_models_raises():
    with pytest.raises(NonPrimitivePayload):
        Loose(job_id="01JOB", payload=[Nested(title="a"), Nested(title="b")])


def test_none_is_a_primitive():
    assert Loose(job_id="01JOB", payload=None).payload is None


def test_numbers_and_booleans_are_primitives():
    assert Loose(job_id="01JOB", payload=42).payload == 42
    assert Loose(job_id="01JOB", payload=1.5).payload == 1.5
    assert Loose(job_id="01JOB", payload=True).payload is True


def test_the_error_says_why():
    """A rule that raises without explaining gets worked around."""
    with pytest.raises(NonPrimitivePayload) as caught:
        Loose(job_id="01JOB", payload={"a": 1})
    message = str(caught.value)
    assert "stale copy" in message
    assert "01-foundations.md §9" in message
