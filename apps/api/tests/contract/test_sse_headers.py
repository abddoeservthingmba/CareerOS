"""T-FOUND-11.5 - buffering off, on every SSE route.

`AC-FOUND-11.5`: "Responses on SSE routes carry `Cache-Control: no-cache` and
`X-Accel-Buffering: no`."

`01-foundations.md` §11: "Behind Cloudflare, buffering must be disabled for
these routes."

A buffering proxy does not break a stream. It *delays* it: the events are
collected, and delivered in one lump when the connection closes. Everything
still arrives, correctly, in order - at the end. So the feature works in
development, works behind no proxy, works in the demo, and in production the
progress bar sits at zero for ninety seconds and then jumps to done. Nothing
logs an error, because nothing went wrong.

Two headers, and neither is optional:

* `Cache-Control: no-cache` stops an intermediary caching the response - a
  cached `text/event-stream` is one user's pack progress served to the next
  request for the same URL;
* `X-Accel-Buffering: no` is what nginx and Cloudflare read to turn buffering
  off for this response specifically.

They are set in `core.sse.SSE_HEADERS` and applied by `sse_response`, so a route
gets them by using the helper. The tests below assert both the constant and the
helper, because a route that built its own `EventSourceResponse` would satisfy
neither and look identical in review.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.sse import SSE_HEADERS, AcceptedResponse, sse_response
from tests.long_operation_app import BASE, OWNER, build_app

REQUIRED = {"cache-control": "no-cache", "x-accel-buffering": "no"}


@pytest.fixture
def client(settings_factory) -> TestClient:
    return build_client(settings_factory)


def build_client(settings_factory: Any) -> TestClient:
    # A zero lifetime so every stream opened here ends immediately: the subject
    # is the headers, and the response's headers are complete before its first
    # byte of body.
    return TestClient(build_app(settings_factory(), lifetime=timedelta(0)))


# -- the constant ------------------------------------------------------------


def test_the_required_headers_are_declared():
    """§11 names both."""
    assert SSE_HEADERS["Cache-Control"] == "no-cache"
    assert SSE_HEADERS["X-Accel-Buffering"] == "no"


def test_the_declaration_is_a_copy_per_response():
    """`sse_response` copies rather than sharing, so a route that mutated its
    own headers cannot change every other route's."""
    first = sse_response(_nothing())
    first.headers["X-Accel-Buffering"] = "yes"

    assert SSE_HEADERS["X-Accel-Buffering"] == "no"
    assert sse_response(_nothing()).headers["x-accel-buffering"] == "no"


async def _nothing() -> AsyncIterator[dict[str, Any]]:
    return
    yield {}  # pragma: no cover - unreachable, and required to make this a generator


# -- the response ------------------------------------------------------------


def test_the_helper_attaches_both_headers():
    response = sse_response(_nothing())

    for name, value in REQUIRED.items():
        assert response.headers[name] == value


def test_the_helper_sends_the_event_stream_content_type():
    """Without it a browser treats the body as text and `EventSource` refuses
    it - which looks like "SSE is not supported here"."""
    assert sse_response(_nothing()).media_type == "text/event-stream"


def test_the_helper_keeps_the_connection_open():
    """A `Connection: close` on a stream is a stream that delivers its first
    event and stops."""
    assert sse_response(_nothing()).headers["connection"] == "keep-alive"


# -- over the wire -----------------------------------------------------------


def test_an_sse_route_carries_both_headers(client: TestClient):
    """AC-FOUND-11.5, through the route rather than the helper.

    The helper being right and the route using it are two facts, and only the
    second one is what a proxy sees.
    """
    body = AcceptedResponse.model_validate(client.post(BASE, headers={"X-Test-User": OWNER}).json())

    with client.stream("GET", body.events_url, headers={"X-Test-User": OWNER}) as stream:
        for name, value in REQUIRED.items():
            assert stream.headers[name] == value, f"{name} is {stream.headers.get(name)!r}"


def test_the_sse_route_is_not_cached(client: TestClient):
    """A cached `text/event-stream` is one user's progress served to the next
    request for the same URL - and the URL contains a task id, so the next
    request is plausibly a different user's retry of a shared link."""
    body = AcceptedResponse.model_validate(client.post(BASE, headers={"X-Test-User": OWNER}).json())

    with client.stream("GET", body.events_url, headers={"X-Test-User": OWNER}) as stream:
        cache_control = stream.headers["cache-control"]

    assert "no-cache" in cache_control
    assert "max-age" not in cache_control


def test_the_content_type_is_event_stream_over_the_wire(client: TestClient):
    body = AcceptedResponse.model_validate(client.post(BASE, headers={"X-Test-User": OWNER}).json())

    with client.stream("GET", body.events_url, headers={"X-Test-User": OWNER}) as stream:
        assert stream.headers["content-type"].startswith("text/event-stream")


def test_the_poll_route_is_not_given_streaming_headers(client: TestClient):
    """`X-Accel-Buffering: no` on a plain JSON GET would disable buffering for a
    response that benefits from it, and would suggest the rule is decoration
    rather than a fix for a specific failure."""
    body = AcceptedResponse.model_validate(client.post(BASE, headers={"X-Test-User": OWNER}).json())

    response = client.get(body.status_url, headers={"X-Test-User": OWNER})

    assert response.headers["content-type"].startswith("application/json")
    assert "x-accel-buffering" not in response.headers


def test_a_404_on_an_sse_route_is_json_not_a_stream(client: TestClient):
    """`AC-FOUND-11.3`'s refusal happens before the stream starts, so it is an
    ordinary problem document - and a client parsing it as SSE would hang."""
    response = client.get(f"{BASE}/01J00000000000000NOSUCH/events", headers={"X-Test-User": OWNER})

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "x-accel-buffering" not in response.headers


def test_every_sse_route_in_the_app_uses_the_helper(client: TestClient):
    """The contract this file exists for.

    Asserted over every route whose response class is `EventSourceResponse`, so
    a second streaming route added later is covered without anyone remembering
    to add it here. Today there is one; the resume pipeline (`RES-01`) and pack
    generation (`APPLY-02`) join it in P2 and P4.
    """
    from sse_starlette.sse import EventSourceResponse

    streaming = [
        route
        for route in client.app.routes  # type: ignore[attr-defined]
        if getattr(route, "response_class", None) is EventSourceResponse
        or str(getattr(route, "path", "")).endswith("/events")
    ]
    assert streaming, "no SSE route was found, so this file asserts nothing"

    body = AcceptedResponse.model_validate(client.post(BASE, headers={"X-Test-User": OWNER}).json())
    for route in streaming:
        url = str(route.path).replace("{task_id}", body.task_id)
        with client.stream("GET", url, headers={"X-Test-User": OWNER}) as stream:
            for name, value in REQUIRED.items():
                assert stream.headers[name] == value, f"{url} is missing {name}"
