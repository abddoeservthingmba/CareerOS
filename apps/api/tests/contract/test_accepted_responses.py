"""T-FOUND-11.1 - every `202` says where to look next.

`AC-FOUND-11.1`: "Every `202` response validates against the `AcceptedResponse`
schema and both URLs return 200 for the owner."

`01-foundations.md` §11: "Every `202 Accepted` response body is `{task_id,
status, status_url, events_url}`. Both URLs must work."

**Both** is the load-bearing word. A `202` whose `events_url` streams beautifully
and whose `status_url` 404s looks correct in every manual test - the developer
watching it is using the stream - and leaves every client that cannot use SSE
unable to finish the flow at all (`AC-FOUND-11.2`). The two URLs are derived from
one path in `core.sse.accepted` for exactly that reason: a route cannot ship one
working and one not without changing the function that builds both.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.sse import AcceptedResponse, OperationStore, Status, accepted

OWNER = "01J000000000000000000OWNER"
STRANGER = "01J0000000000000000STRANGE"
TASK = "01J00000000000000000TASK01"
BASE = "/api/v1/applications/01J0000000000000000APP/pack"


# -- the schema ---------------------------------------------------------------


def test_the_body_is_the_four_fields_the_specification_names():
    """§11's shape, exactly."""
    assert set(AcceptedResponse.model_fields) == {
        "task_id",
        "status",
        "status_url",
        "events_url",
    }


def test_an_extra_field_is_refused():
    """`extra="forbid"`. A route that added `progress` here would be a fifth
    field clients start depending on, and §11's shape would quietly become
    whatever the first route happened to send."""
    with pytest.raises(ValidationError):
        AcceptedResponse(
            task_id=TASK,
            status_url=f"{BASE}/{TASK}",
            events_url=f"{BASE}/{TASK}/events",
            progress=0,  # type: ignore[call-arg]
        )


def test_a_missing_url_is_refused():
    with pytest.raises(ValidationError):
        AcceptedResponse.model_validate({"task_id": TASK, "status_url": f"{BASE}/{TASK}"})


def test_the_body_is_frozen():
    """One object, handed to the response. A route that mutated it after
    building would produce a body that disagrees with what it logged."""
    body = accepted(TASK, BASE)
    with pytest.raises(ValidationError):
        body.task_id = "something else"


def test_both_urls_are_derived_from_one_path():
    """The reason `AC-FOUND-11.1`'s "both" can be relied on."""
    body = accepted(TASK, BASE)
    assert body.status_url == f"{BASE}/{TASK}"
    assert body.events_url == f"{BASE}/{TASK}/events"
    assert body.events_url.startswith(body.status_url)


def test_a_trailing_slash_does_not_produce_a_double_slash():
    body = accepted(TASK, f"{BASE}/")
    assert "//" not in body.status_url.removeprefix("http://")
    assert body.status_url == f"{BASE}/{TASK}"


def test_the_initial_status_is_queued():
    """Not `running`: the `202` is returned before the worker has picked the job
    up, and claiming otherwise makes a stuck queue look like a stuck task."""
    assert accepted(TASK, BASE).status is Status.QUEUED


# -- both URLs, against a running app ----------------------------------------


@pytest.fixture
def app(settings_factory) -> FastAPI:
    """A route triple in the shape §11 prescribes: `POST` returning `202`, a
    status `GET`, and an events `GET`.

    Built here rather than imported, because the first real one lands with
    `RES-01` in P2. What is asserted is the contract every such triple has to
    satisfy - written now so the first implementation is measured against it,
    not the other way round.
    """
    from app.main import create_app

    application = create_app(settings_factory())
    store = OperationStore()
    application.state.operations = store

    @application.post(f"{BASE}", status_code=202, include_in_schema=False)
    async def start() -> dict[str, Any]:
        store.start(TASK, OWNER)
        return accepted(TASK, BASE).model_dump(mode="json")

    @application.get(f"{BASE}/{{task_id}}", include_in_schema=False)
    async def status(task_id: str) -> dict[str, Any]:
        state = store.get(task_id, OWNER)
        if state is None:
            from app.core.errors import NotFound

            raise NotFound()
        return state.snapshot()

    @application.get(f"{BASE}/{{task_id}}/events", include_in_schema=False)
    async def events(task_id: str) -> Any:
        from app.core.errors import NotFound
        from app.core.sse import event_stream, sse_response

        state = store.get(task_id, OWNER)
        if state is None:
            raise NotFound()
        queue = store.subscribe(task_id)
        return sse_response(
            event_stream(state, queue, lifetime=__import__("datetime").timedelta(0))
        )

    return application


def test_the_202_body_validates(app: FastAPI):
    """AC-FOUND-11.1, first half."""
    client = TestClient(app)
    response = client.post(BASE)

    assert response.status_code == 202
    body = AcceptedResponse.model_validate(response.json())
    assert body.task_id == TASK


def test_the_status_url_returns_200_for_the_owner(app: FastAPI):
    """AC-FOUND-11.1, second half - the URL that is easy to leave broken."""
    client = TestClient(app)
    body = AcceptedResponse.model_validate(client.post(BASE).json())

    status = client.get(body.status_url)

    assert status.status_code == 200
    assert status.json()["task_id"] == TASK


def test_the_events_url_returns_200_for_the_owner(app: FastAPI):
    client = TestClient(app)
    body = AcceptedResponse.model_validate(client.post(BASE).json())

    with client.stream("GET", body.events_url) as stream:
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")


def test_the_status_body_carries_what_a_poller_needs(app: FastAPI):
    """`AC-FOUND-11.2` depends on this: a poller must be able to learn
    everything a streamer learns, or the fallback is not one."""
    client = TestClient(app)
    body = AcceptedResponse.model_validate(client.post(BASE).json())

    snapshot = client.get(body.status_url).json()

    assert set(snapshot) == {
        "task_id",
        "status",
        "stage",
        "progress",
        "detail",
        "at",
        "terminal",
    }


def test_an_unknown_task_id_is_404_not_500(app: FastAPI):
    client = TestClient(app)
    assert client.get(f"{BASE}/01J00000000000000NOSUCH").status_code == 404


def test_the_202_is_not_a_200(app: FastAPI):
    """A `200` would tell a client the work is done. It is not - that is the
    whole reason for the two URLs."""
    assert TestClient(app).post(BASE).status_code == 202
