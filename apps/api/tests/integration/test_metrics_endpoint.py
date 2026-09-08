"""T-FOUND-14.3 - `/metrics`, behind a token, with all seven families.

`AC-FOUND-14.3`: "`/metrics` without a valid token returns 401; with one, it
exposes all seven required metric families."

**Why a token at all**, for an endpoint that publishes no user data. Because it
publishes the *shape* of the system: which routes exist and how often they are
called, how much is being spent on AI and on what, how many reminders go out and
whether they are failing. That is the reconnaissance step of an attack and a
competitor's intelligence feed, in one unauthenticated GET. It costs one header
to close.

**Why all seven, before six of them have anything to write.** `15-infra-and-ops.md`
§4.2 names each family alongside the question it answers, and a family that
appears the day its feature ships is a family with no history on the day that
feature first misbehaves. An alert on "queue depth over 1,000 for 10 minutes"
needs the series to have existed before the incident.

**Why the labels are bounded.** `route` is the template, never the resolved
path. A label whose values are ids is a cardinality explosion that takes the
monitoring system down - and, on the way, a complete list of every id in the
system readable by anyone with a dashboard login.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core import metrics
from app.main import create_app

TOKEN = "a-metrics-token-for-tests"


@pytest.fixture
def client(settings_factory) -> TestClient:
    return TestClient(create_app(settings_factory(METRICS_TOKEN=TOKEN)))


def authorised(client: TestClient) -> str:
    body: str = client.get("/metrics", headers={"X-Metrics-Token": TOKEN}).text
    return body


# -- the token ---------------------------------------------------------------


def test_no_token_is_401(client: TestClient):
    """AC-FOUND-14.3, first half."""
    assert client.get("/metrics").status_code == 401


def test_a_wrong_token_is_401(client: TestClient):
    assert client.get("/metrics", headers={"X-Metrics-Token": "wrong"}).status_code == 401


def test_a_prefix_of_the_token_is_401(client: TestClient):
    """Compared in constant time and in full. A prefix match would turn the
    endpoint into an oracle that yields the token one character at a time."""
    assert client.get("/metrics", headers={"X-Metrics-Token": TOKEN[:-1]}).status_code == 401


def test_the_right_token_is_200(client: TestClient):
    assert client.get("/metrics", headers={"X-Metrics-Token": TOKEN}).status_code == 200


def test_an_unconfigured_token_denies_everything(settings_factory):
    """A deployment that forgot the variable must not publish its whole shape to
    the internet and look healthy doing it.

    Fail-closed, like `FOUND-16`'s bounce webhook: the failure mode of the other
    choice is invisible until someone finds the endpoint.
    """
    client = TestClient(create_app(settings_factory(METRICS_TOKEN="")))

    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"X-Metrics-Token": ""}).status_code == 401


def test_the_comparison_is_constant_time():
    """Asserted at the function, because a timing property cannot be asserted
    over HTTP without a flaky benchmark."""
    import inspect

    source = inspect.getsource(metrics.token_matches)
    assert "compare_digest" in source
    assert not metrics.token_matches("anything", "")
    assert not metrics.token_matches("", "configured")
    assert metrics.token_matches("same", "same")


# -- the seven families ------------------------------------------------------


def test_all_seven_required_families_are_exposed(client: TestClient):
    """AC-FOUND-14.3, second half."""
    body = authorised(client)
    missing = [family for family in metrics.REQUIRED_FAMILIES if family not in body]

    assert missing == [], f"these families are not exposed: {missing}"


def test_the_required_list_is_the_one_the_spec_names(repo):
    """`15-infra-and-ops.md` §4.2's table, transcribed once.

    Read from the module rather than restated in the test: a test carrying its
    own copy would be asserting against itself.
    """
    text = (repo / "docs" / "spec" / "15-infra-and-ops.md").read_text(encoding="utf-8")
    section = text.split("### 4.2 The required metrics", 1)[1].split("### 4.3", 1)[0]
    for family in metrics.REQUIRED_FAMILIES:
        assert family in section, f"{family} is not in §4.2's table"
    assert "Seven families" in section
    assert len(metrics.REQUIRED_FAMILIES) == 7


def test_the_exposition_is_prometheus_format(client: TestClient):
    response = client.get("/metrics", headers={"X-Metrics-Token": TOKEN})

    assert "text/plain" in response.headers["content-type"]
    assert "# HELP" in response.text
    assert "# TYPE" in response.text


def test_every_family_carries_the_question_it_answers(client: TestClient):
    """§4.2 names each family alongside a question. A `HELP` line that repeated
    the metric name would make the table's discipline invisible in the place an
    operator actually reads."""
    body = authorised(client)
    for family in metrics.REQUIRED_FAMILIES:
        # Prometheus renders a counter as `<name>_total`, so the exposed name is
        # not always the declared one. Accepting either is the format's rule
        # rather than a looser assertion.
        prefixes = (f"# HELP {family} ", f"# HELP {family}_total ")
        help_line = next((line for line in body.split("\n") if line.startswith(prefixes)), "")
        assert help_line, f"{family} has no HELP line"
        description = help_line.split(" ", 3)[3].strip()
        assert len(description) > 15, f"{family}: {description!r} says nothing"
        assert family not in description


# -- what gets recorded ------------------------------------------------------


def test_a_request_is_observed_in_the_latency_histogram(client: TestClient):
    """The middleware sees every request and its final status, so the histogram
    covers the ones that ended in an exception handler too."""
    client.get("/healthz")
    body = authorised(client)

    assert 'http_request_duration_seconds_count{route="/healthz",status="200"}' in body


def test_a_failed_request_is_observed_too(settings_factory):
    """The requests worth measuring are disproportionately the failing ones. A
    histogram that only saw successes would show a latency budget being met
    while every error timed out."""
    from app.core.errors import NotFound

    app = create_app(settings_factory(METRICS_TOKEN=TOKEN))

    @app.get("/api/v1/_test/fail", include_in_schema=False)
    async def fail() -> dict[str, str]:
        raise NotFound()

    client = TestClient(app)
    client.get("/api/v1/_test/fail")

    assert 'status="404"' in authorised(client)


def test_the_route_label_is_the_template_not_the_path(settings_factory):
    """A label whose values are ids is a cardinality explosion, and a list of
    every id in the system."""
    app = create_app(settings_factory(METRICS_TOKEN=TOKEN))

    @app.get("/api/v1/_test/{item_id}", include_in_schema=False)
    async def item(item_id: str) -> dict[str, str]:
        return {"id": item_id}

    client = TestClient(app)
    client.get("/api/v1/_test/01J000000000000000000001")
    client.get("/api/v1/_test/01J000000000000000000002")
    body = authorised(client)

    assert 'route="/api/v1/_test/{item_id}"' in body
    assert "01J000000000000000000001" not in body
    assert "01J000000000000000000002" not in body


def test_an_unmatched_path_does_not_create_a_label_per_url(client: TestClient):
    """A scanner hitting a thousand random URLs must not create a thousand time
    series - which is a denial of service against the monitoring system that
    anyone can perform."""
    for path in ("/nope", "/also-nope", "/wp-admin"):
        client.get(path)
    body = authorised(client)

    assert 'route="unmatched"' in body
    assert "wp-admin" not in body


def test_the_metrics_endpoint_is_not_in_the_generated_clients(client: TestClient):
    """`AC-FOUND-13.5`. `/metrics` is for a scrape job, which is not an API
    consumer - and putting it in the contract would make its body subject to
    §13's breaking-change rule."""
    assert "/metrics" not in client.get("/openapi.json").json()["paths"]


def test_no_metric_label_carries_a_user_id(client: TestClient):
    """§14's redaction rule applies to span and metric labels too. A `user_id`
    label is both a cardinality problem and a list of everyone."""
    client.get("/healthz")
    body = authorised(client)

    assert "user_id=" not in body
    assert "email=" not in body
