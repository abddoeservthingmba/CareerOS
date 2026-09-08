"""T-FOUND-14.2 - one id, on every line and in the response.

`AC-FOUND-14.2`: "Every log line emitted during a request contains the same
`request_id` as the response header."

This is the field that makes a support question answerable. A user reports "it
failed at about two o'clock"; the error screen showed them a request id; that id
selects every line the request produced, across every module it touched. Without
it the same question is answered by reading timestamps and guessing, and the
guess is wrong whenever two users hit the same bug in the same minute.

It is bound once, in the middleware, and read by a structlog processor from a
`contextvar`. The alternative - threading it through every call - is a parameter
that gets dropped in the one function written in a hurry, which is reliably the
function that later fails.

**The inbound header is validated, not trusted** (§14: "accepting an inbound
`X-Request-ID` if it is a valid UUID"). It is echoed into every log line, so an
unvalidated one writes arbitrary text - newlines included - into the aggregator,
and lets a caller poison correlation by sending one id with every request.
"""

from __future__ import annotations

import io
import logging
import uuid
from typing import Any

import pytest
import structlog
from fastapi.testclient import TestClient

from app.core import logging as app_logging
from app.core.errors import NotFound
from app.main import create_app, valid_request_id


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every line the application emits, as the dict a renderer would receive.

    Captured *after* the whole processor chain, through a second
    `ProcessorFormatter` on the root logger. Two reasons for doing it this way
    rather than by reading the chain earlier:

    * the correlation fields and the redaction are both processors, so a capture
      taken before them would assert about a line that never existed;
    * lines from libraries that never heard of structlog reach the same handler,
      so this sees what a log aggregator would see rather than only what our own
      code emits.

    Installed by wrapping `configure`, because `create_app` calls it and resets
    the root logger's handlers - a handler added before that would be discarded.
    """
    lines: list[dict[str, Any]] = []
    original = app_logging.configure

    def record(_logger: Any, _name: str, event: Any) -> str:
        lines.append({k: v for k, v in dict(event).items() if not str(k).startswith("_")})
        return ""

    def configure_and_capture(**kwargs: Any) -> None:
        original(**kwargs)
        # `httpx` logs one line per request from inside `TestClient` - the test
        # harness talking to itself, emitted after the response and therefore
        # outside the server's request context. It has no `request_id` and
        # should not: it is not a line the application emitted.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        handler = logging.StreamHandler(io.StringIO())
        handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=record,
                foreign_pre_chain=[
                    structlog.stdlib.add_log_level,
                    structlog.stdlib.add_logger_name,
                    app_logging.add_correlation,
                    app_logging.add_timestamp,
                    app_logging.redact,
                ],
            )
        )
        logging.getLogger().addHandler(handler)

    monkeypatch.setattr(app_logging, "configure", configure_and_capture)
    return lines


# -- the criterion -----------------------------------------------------------


def test_every_line_carries_the_responses_request_id(captured, settings_factory):
    """AC-FOUND-14.2.

    Both kinds of line: one written through structlog and one through the
    standard library, because a third-party line that skipped the correlation
    would be the one you needed during the incident.
    """
    app = create_app(settings_factory())

    @app.get("/_test/logs", include_in_schema=False)
    async def emits() -> dict[str, str]:
        app_logging.get_logger("app.test").info("first line")
        app_logging.get_logger("app.test").info("second line", stage="middle")
        logging.getLogger("third.party").warning("a standard-library line")
        return {"ok": "true"}

    response = TestClient(app).get("/_test/logs")
    header = response.headers["X-Request-ID"]

    assert len(captured) >= 3, "the request produced no log lines"
    assert {line.get("request_id") for line in captured} == {header}


def test_two_requests_do_not_share_an_id(captured, settings_factory):
    """The point of the field. If both requests logged the same id, a support
    query would return two users' lines and answer neither question."""
    app = create_app(settings_factory())

    @app.get("/_test/one", include_in_schema=False)
    async def one() -> dict[str, str]:
        app_logging.get_logger("app.test").info("a line")
        return {}

    client = TestClient(app)
    first = client.get("/_test/one").headers["X-Request-ID"]
    second = client.get("/_test/one").headers["X-Request-ID"]

    assert first != second
    assert {line.get("request_id") for line in captured} == {first, second}


def test_the_id_does_not_leak_into_the_next_request(captured, settings_factory):
    """The contextvar is cleared when the request ends. Otherwise a background
    task or a later request inherits an id that belongs to somebody else, which
    is worse than no id: it is a wrong answer that looks right."""
    app = create_app(settings_factory())

    @app.get("/_test/one", include_in_schema=False)
    async def one() -> dict[str, str]:
        return {}

    TestClient(app).get("/_test/one")

    assert app_logging.current_request_id() == ""


def test_a_failing_request_still_correlates(captured, settings_factory):
    """The request that most needs the id is the one that failed. A middleware
    that bound the id after the handler would lose exactly those."""
    app = create_app(settings_factory())

    @app.get("/_test/raises", include_in_schema=False)
    async def raises() -> dict[str, str]:
        app_logging.get_logger("app.test").info("before the failure")
        raise NotFound()

    response = TestClient(app).get("/_test/raises")

    assert response.status_code == 404
    header = response.headers["X-Request-ID"]
    assert header
    assert header in {line.get("request_id") for line in captured}


def test_the_problem_body_carries_the_same_id(settings_factory):
    """`FOUND-12`'s problem document names `request_id`, and it has to be the
    same one - it is what the user is asked to quote."""
    app = create_app(settings_factory())

    @app.get("/_test/raises", include_in_schema=False)
    async def raises() -> dict[str, str]:
        raise NotFound()

    response = TestClient(app).get("/_test/raises")

    assert response.json()["request_id"] == response.headers["X-Request-ID"]


# -- the inbound header ------------------------------------------------------


def test_a_valid_inbound_uuid_is_adopted(settings_factory):
    """A request that crossed a gateway already has an id, and inventing a
    second one breaks the trace at the boundary."""
    client = TestClient(create_app(settings_factory()))
    incoming = str(uuid.uuid4())

    response = client.get("/healthz", headers={"X-Request-ID": incoming})

    assert response.headers["X-Request-ID"] == incoming


@pytest.mark.parametrize(
    "value",
    [
        "not-a-uuid",
        "",
        "   ",
        "'; DROP TABLE users; --",
        "01J0000000000000000000ULID",
        "x" * 500,
    ],
)
def test_an_invalid_inbound_id_is_replaced(settings_factory, value: str):
    """§14: "if it is a valid UUID, else generating one"."""
    client = TestClient(create_app(settings_factory()))

    response = client.get("/healthz", headers={"X-Request-ID": value})
    assigned = response.headers["X-Request-ID"]

    assert assigned != value
    assert valid_request_id(assigned)


def test_a_header_containing_a_newline_never_reaches_a_log_line(settings_factory):
    """The case that matters most, kept separate because it is a different
    failure: an id echoed unvalidated into a line-oriented log format lets a
    caller write their own log entries.

    Asserted at the validator rather than over HTTP, because a well-behaved HTTP
    stack rejects the header before the application sees it - and the validator
    is what protects the paths that are not HTTP.
    """
    assert not valid_request_id("a\nfabricated: log line")
    assert not valid_request_id("f47ac10b-58cc-4372-a567-0e02b2c3d479\ninjected")


def test_the_validator_accepts_only_uuids():
    assert valid_request_id(str(uuid.uuid4()))
    assert valid_request_id("f47ac10b-58cc-4372-a567-0e02b2c3d479")
    assert not valid_request_id("f47ac10b58cc4372a5670e02b2c3d47")
    assert not valid_request_id("")
    assert not valid_request_id("null")


def test_a_generated_id_is_a_uuid(settings_factory):
    """§14 says the generated one is a UUID too, so a downstream service that
    validates the header the same way accepts what we send it."""
    client = TestClient(create_app(settings_factory()))
    assert valid_request_id(client.get("/healthz").headers["X-Request-ID"])


# -- the binding itself ------------------------------------------------------


def test_binding_outside_a_request_is_possible():
    """The worker binds the same field at the top of each task, so a task's
    lines correlate to the request that enqueued it."""
    app_logging.bind_request(request_id="f47ac10b-58cc-4372-a567-0e02b2c3d479")
    assert app_logging.current_request_id() == "f47ac10b-58cc-4372-a567-0e02b2c3d479"
    app_logging.clear_request()
    assert app_logging.current_request_id() == ""


def test_the_correlation_processor_adds_nothing_when_unbound():
    """An empty `user_id` written as `""` is a value people filter on by
    accident, and an unauthenticated request genuinely has none."""
    app_logging.clear_request()
    event: dict[str, Any] = {"event": "something"}

    assert app_logging.add_correlation(None, "info", event) == {"event": "something"}


def test_the_correlation_processor_does_not_overwrite_an_explicit_field():
    """A line that names a *different* user - an admin acting on someone - must
    keep the one it was given."""
    app_logging.bind_request(request_id="f47ac10b-58cc-4372-a567-0e02b2c3d479", user_id="A")
    event = app_logging.add_correlation(None, "info", {"event": "x", "user_id": "B"})
    app_logging.clear_request()

    assert event["user_id"] == "B"
    assert event["request_id"] == "f47ac10b-58cc-4372-a567-0e02b2c3d479"
