"""T-FOUND-11.3 - a stream is a read, authorised like any other.

`AC-FOUND-11.3`: "A stream for a resource owned by another user returns 404 and
emits no events."

Both halves matter, and the second one is the one a naive implementation gets
wrong. A stream that answers 200 and then sends nothing has already told the
caller the id exists; a stream that answers 200 and sends one `queued` event
before noticing has told them more than that. The check has to happen before the
response starts, because once a `text/event-stream` has begun there is no status
code left to change.

**404, not 403** (`02-auth-and-account.md` §6). A 403 distinguishes "not yours"
from "not there", which turns an id-addressed endpoint into an enumeration
oracle: try ids, and the ones that answer 403 exist. That the resource in
question is only a progress bar does not help - the id is a pack id, and knowing
that a given pack id is real is knowing something about someone's job search.

The same answer for the poll route, for the same reason. A fallback that leaked
what the stream refused to would be worse than no fallback, because nobody would
be looking at it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.sse import AcceptedResponse, OperationStore, Status
from tests.long_operation_app import BASE, OWNER, STRANGER, build_app


@pytest.fixture
def client(settings_factory) -> TestClient:
    # A zero lifetime, so the one test that opens a stream as the owner gets a
    # response that ends rather than one that runs for ten minutes. Every other
    # test here is refused before the stream starts, which is the point.
    return TestClient(build_app(settings_factory(), lifetime=timedelta(0)))


def start(client: TestClient, user: str = OWNER) -> AcceptedResponse:
    return AcceptedResponse.model_validate(client.post(BASE, headers={"X-Test-User": user}).json())


def as_user(user: str) -> dict[str, str]:
    return {"X-Test-User": user}


# -- the stream --------------------------------------------------------------


def test_a_strangers_stream_is_404(client: TestClient):
    """AC-FOUND-11.3, first half."""
    body = start(client, OWNER)

    response = client.get(body.events_url, headers=as_user(STRANGER))

    assert response.status_code == 404


def test_a_strangers_stream_emits_no_events(client: TestClient):
    """AC-FOUND-11.3, second half.

    A 200 followed by silence would already have confirmed the id. This asserts
    the refusal happens before the response starts.
    """
    body = start(client, OWNER)
    store: OperationStore = client.app.state.operations  # type: ignore[attr-defined]
    store.advance(body.task_id, "generating", 50, Status.RUNNING, "drafting")

    response = client.get(body.events_url, headers=as_user(STRANGER))

    assert response.status_code == 404
    assert "event:" not in response.text
    assert "generating" not in response.text
    assert "drafting" not in response.text


def test_the_refusal_is_404_and_not_403(client: TestClient):
    """`02-auth-and-account.md` §6. A 403 tells the caller the id is real, which
    is the difference between a wall and a directory."""
    body = start(client, OWNER)
    assert client.get(body.events_url, headers=as_user(STRANGER)).status_code == 404


def test_an_unknown_task_and_someone_elses_task_answer_identically(client: TestClient):
    """The property that makes the 404 worth anything.

    If they differed in status, body or timing, the endpoint would still be an
    oracle - just a subtler one.
    """
    body = start(client, OWNER)

    mine_but_not_mine = client.get(body.events_url, headers=as_user(STRANGER))
    never_existed = client.get(f"{BASE}/01J00000000000000NOSUCH/events", headers=as_user(STRANGER))

    assert mine_but_not_mine.status_code == never_existed.status_code == 404
    assert mine_but_not_mine.json()["title"] == never_existed.json()["title"]
    assert mine_but_not_mine.json()["detail"] == never_existed.json()["detail"]


def test_the_owner_can_open_their_own_stream(client: TestClient):
    """The control. A route that 404'd for everyone would pass every assertion
    above and ship a feature nobody can use."""
    body = start(client, OWNER)

    # Opened with `stream`, not `get`: reading an SSE body to completion through
    # `TestClient` waits on `sse-starlette`'s ping task, which outlives the
    # generator. The status and the content type are what this test is about;
    # the stream's own behaviour is `test_sse_lifecycle.py`'s.
    with client.stream("GET", body.events_url, headers=as_user(OWNER)) as stream:
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")


# -- the poll route, which must not be the softer door -----------------------


def test_a_strangers_status_url_is_404(client: TestClient):
    """`AC-FOUND-11.2` makes `status_url` a full substitute for the stream, so
    an ownership check on one and not the other is a hole with a sign on it."""
    body = start(client, OWNER)

    response = client.get(body.status_url, headers=as_user(STRANGER))

    assert response.status_code == 404


def test_a_strangers_status_url_leaks_no_progress(client: TestClient):
    body = start(client, OWNER)
    store: OperationStore = client.app.state.operations  # type: ignore[attr-defined]
    store.advance(body.task_id, "checking", 75, Status.RUNNING, "fabrication scan")

    response = client.get(body.status_url, headers=as_user(STRANGER))

    assert response.status_code == 404
    assert "checking" not in response.text
    assert "fabrication scan" not in response.text


def test_the_owner_can_poll_their_own_status(client: TestClient):
    body = start(client, OWNER)
    assert client.get(body.status_url, headers=as_user(OWNER)).status_code == 200


# -- the store, where the rule actually lives --------------------------------


def test_the_store_refuses_a_mismatched_owner():
    """Enforced once, below the routes, so a fourth route on the same operation
    cannot forget it."""
    store = OperationStore()
    store.start("01J0TASK", OWNER)

    assert store.get("01J0TASK", OWNER) is not None
    assert store.get("01J0TASK", STRANGER) is None


def test_the_store_answers_the_same_for_absent_and_not_yours():
    store = OperationStore()
    store.start("01J0TASK", OWNER)

    assert store.get("01J0TASK", STRANGER) is store.get("01J0MISSING", STRANGER) is None


def test_two_users_operations_do_not_collide():
    """Two operations, two owners, one store. Each sees exactly their own."""
    store = OperationStore()
    store.start("01J0MINE", OWNER)
    store.start("01J0THEIRS", STRANGER)

    assert store.get("01J0MINE", OWNER) is not None
    assert store.get("01J0THEIRS", OWNER) is None
    assert store.get("01J0THEIRS", STRANGER) is not None
    assert store.get("01J0MINE", STRANGER) is None


def test_advancing_an_unknown_task_is_a_no_op_not_a_crash():
    """A worker reporting progress for an operation that has been cleaned up
    should not take the worker down with it."""
    store = OperationStore()
    assert store.advance("01J0MISSING", "generating", 10, Status.RUNNING) is None


def test_the_event_body_carries_no_owner_id(client: TestClient):
    """A stream is scoped to one resource; the events it sends should not repeat
    who owns it. There is exactly one reader and they already know."""
    body = start(client, OWNER)
    store: OperationStore = client.app.state.operations  # type: ignore[attr-defined]
    event = store.advance(body.task_id, "gathering", 0, Status.RUNNING)

    assert event is not None
    payload: dict[str, Any] = event.model_dump()
    assert "owner_id" not in payload
    assert OWNER not in event.model_dump_json()
