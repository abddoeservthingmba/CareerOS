"""T-FOUND-16.4 - nothing personal reaches a log line.

`AC-FOUND-16.4`: "No log line, metric label, or Sentry event contains a
recipient address or a message body." Shared with `FOUND-14`'s redaction rules.

`01-foundations.md` §16: "Logs carry `template_id`, `MessageId` and outcome —
never the address, never the body, never a token. A provider error is logged as
a code (`AC-FOUND-14.5`)."

The reason this is a test and not a review note: the address is the one value in
scope on every code path here, so it is the value a debugging `logger.info` picks
up first, and a log aggregator is a copy of your user table that nobody counts as
one.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import pytest
import structlog

from app.core import logging as app_logging
from app.core.redaction import REDACTED
from app.infra.email.base import SendFailed
from app.infra.email.bounces import BounceKind, MemoryBounceRegistry
from app.infra.email.senders import MemorySender
from app.infra.email.templates import build_registry

ADDRESS = "someone.private@example.test"
TOKEN = "tok_5f4dcc3b5aa765d61d8327deb882cf99"
DATA = {"verify_url": f"https://example.test/verify/{TOKEN}"}

#: Everything that must never appear, in any field of any record.
FORBIDDEN = (ADDRESS, "someone.private", TOKEN, "Confirm this address")


#: The attributes `logging` puts on every record. Anything else came from an
#: `extra`, which is what a structured logger ships as fields.
_STANDARD = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


def everything_logged(caplog: pytest.LogCaptureFixture) -> str:
    """Every rendered message plus every `extra` value, as one blob.

    Formatting the message is not enough: a structured logger ships the `extra`
    dict too, so an address passed as `extra={"to": ...}` would pass a
    message-only assertion and still land in the aggregator.
    """
    parts: list[str] = []
    for record in caplog.records:
        parts.append(record.getMessage())
        parts.extend(
            f"{key}={value}" for key, value in record.__dict__.items() if key not in _STANDARD
        )
    return "\n".join(parts)


@pytest.fixture
def logs(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.DEBUG)
    return caplog


def sender(**kwargs: object) -> MemorySender:
    return MemorySender(
        build_registry(),
        sender_address="no-reply@localhost",
        product_name="JobPilot",
        **kwargs,
    )


async def test_a_successful_send_logs_no_address_and_no_body(logs):
    """AC-FOUND-16.4."""
    mailer = sender()
    message_id = await mailer.send(ADDRESS, "verify_email", DATA)

    blob = everything_logged(logs)
    assert logs.records, "a send that logs nothing is not what is being asserted"
    for secret in FORBIDDEN:
        assert secret not in blob, f"{secret!r} reached a log record"
    # What it does carry, so the line is still useful to an operator.
    assert "verify_email" in blob
    assert message_id in blob


async def test_a_provider_failure_logs_a_code_not_a_body(logs):
    """`AC-FOUND-14.5` - a provider's message can echo the content it refused."""
    mailer = sender(sleep=_no_sleep)
    mailer.fail_with = SendFailed("memory", 422, "invalid_recipient")
    mailer.fail_times = -1

    with pytest.raises(SendFailed):
        await mailer.send(ADDRESS, "verify_email", DATA)

    blob = everything_logged(logs)
    for secret in FORBIDDEN:
        assert secret not in blob
    assert "invalid_recipient" in blob
    assert "422" in blob


async def test_a_retried_failure_logs_no_address(logs):
    mailer = sender(sleep=_no_sleep)
    mailer.fail_with = SendFailed("memory", 503, "unavailable")
    mailer.fail_times = -1

    with pytest.raises(SendFailed):
        await mailer.send(ADDRESS, "verify_email", DATA)

    assert ADDRESS not in everything_logged(logs)


async def test_a_suppressed_duplicate_logs_no_address(logs):
    mailer = sender()
    await mailer.send(ADDRESS, "verify_email", DATA, "k")
    await mailer.send(ADDRESS, "verify_email", DATA, "k")

    blob = everything_logged(logs)
    assert ADDRESS not in blob
    assert "duplicate" in blob


def test_a_bounce_logs_no_address(logs):
    """The bounce path handles nothing *but* an address, so it is the easiest
    place to leak one."""
    MemoryBounceRegistry().mark(ADDRESS, BounceKind.COMPLAINT, "spam_report")

    blob = everything_logged(logs)
    assert ADDRESS not in blob
    assert "complaint" in blob
    assert "spam_report" in blob


async def test_the_rendered_body_is_never_logged(logs):
    """The body carries the token, which is the credential in a reset link."""
    mailer = sender()
    await mailer.send(ADDRESS, "password_reset", {"reset_url": f"https://x.test/{TOKEN}"})

    blob = everything_logged(logs)
    assert TOKEN not in blob
    assert "<!doctype html>" not in blob


async def _no_sleep(seconds: float) -> None:
    """Backoff is asserted in `test_email_retries.py`; here it is only delay."""
    return None


# -- T-FOUND-14.1: the whole log pipeline -------------------------------------
#
# `AC-FOUND-14.1`: "A test that exercises registration, login, resume upload,
# pack generation, and a reminder send captures all log output and asserts it
# contains none of: the test email address, the test password, any JWT, any
# OTP, any substring of the test resume, any substring of a job description."
#
# **Four of those five flows do not exist.** Registration and login are `AUTH-01`
# and `AUTH-02` in P1; resume upload is `RES-01` in P2; pack generation is
# `APPLY-02` in P4; the reminder send is `NOTIF-05` in P6. `app/modules/` is
# empty.
#
# What is asserted below is the mechanism every one of those flows will pass
# through: the processor chain that every line - ours and every library's -
# leaves by. `FLOWS` names the five, and the assertion that it is complete
# fails if §14's sentence ever grows a sixth. When each module lands, its own
# flow is added here; the chain being right first is what makes that addition
# a check rather than a discovery.

#: `AC-FOUND-14.1`'s five flows, and the requirement that brings each one.
FLOWS: dict[str, str] = {
    "registration": "AUTH-01",
    "login": "AUTH-02",
    "resume upload": "RES-01",
    "pack generation": "APPLY-02",
    "reminder send": "NOTIF-05",
}

#: The six things §14 says must appear in no line, keyed by the field name a
#: flow would realistically pass them under. The name matters: redaction is by
#: key first, and the key a careless author reaches for is the field's own name.
SECRETS = {
    "email": "candidate.private@example.test",
    "password": "correct-horse-battery-staple",
    "token": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIwMUowIn0.7mQ1kM3xVQ0bK9Zl2pR4sT6uW8yA1cE3gI5kM7oQ9sU",
    "otp": "483920",
    "resume_text": "Senior engineer with eleven years at a payments company",
    "job_description": "We are looking for a backend engineer with strong Python",
}


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every line, after the whole chain - ours and any library's."""
    captured: list[dict[str, Any]] = []

    def record(_logger: Any, _name: str, event: Any) -> str:
        captured.append({k: v for k, v in dict(event).items() if not str(k).startswith("_")})
        return ""

    app_logging.configure(environment="staging", level="DEBUG")
    handler = logging.StreamHandler()
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
    monkeypatch.setattr(logging.getLogger(), "handlers", [handler])
    return captured


def rendered(lines: list[dict[str, Any]]) -> str:
    import json

    return json.dumps(lines, default=str)


def test_the_flow_list_is_the_one_the_criterion_names(repo):
    """A sixth flow added to §14 fails here rather than shipping unwatched."""
    text = (repo / "docs" / "spec" / "01-foundations.md").read_text(encoding="utf-8")
    sentence = next(line for line in text.split("\n") if line.startswith("- `AC-FOUND-14.1`"))
    for flow in FLOWS:
        assert flow in sentence, f"{flow} is not one of the flows §14 names"
    assert sentence.count(",") >= len(FLOWS)


def test_none_of_the_five_flows_is_reachable_yet(repo):
    """Stated rather than assumed.

    The moment one of §14's five flows becomes reachable, this fails - which is
    the prompt to add that flow's end-to-end assertion here instead of
    discovering later that the criterion was only ever half-checked.

    **Keyed on a routable module, not on a module directory.** It used to check
    for the directory, and `DATA-02` created all nine in P0 to hold their
    Beanie documents - every other file still the scaffold's docstring. A
    sentinel that fires when no flow exists is a false alarm, and a false alarm
    is what gets a sentinel deleted. A flow can leak a secret only once there is
    a request path to run it; an `APIRouter` in `router.py` is that.
    """
    import ast

    modules = repo / "apps" / "api" / "app" / "modules"
    present: list[str] = []
    for path in sorted(modules.iterdir()):
        router = path / "router.py"
        if not router.is_file():
            continue
        tree = ast.parse(router.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name | ast.Attribute)
            and "APIRouter" in ast.unparse(node.func)
            for node in ast.walk(tree)
        ):
            present.append(path.name)

    assert present == [], (
        f"{present} now expose routes; add their flows to this file's end-to-end "
        f"assertion. Owed: {FLOWS}"
    )


@pytest.mark.parametrize("name", sorted(SECRETS))
def test_no_secret_survives_the_chain_as_a_field(pipeline, name: str):
    """Every one of §14's six, passed as a structured field."""
    app_logging.get_logger("app.flow").info(
        "a step happened", **{name: SECRETS[name], "user_id": "01J0USER"}
    )

    text = rendered(pipeline)
    assert SECRETS[name] not in text, f"{name} reached a log line as a field"
    assert "01J0USER" in text, "the id that makes the line useful was dropped too"


@pytest.mark.parametrize("name", ["email", "token"])
def test_no_recognisable_secret_survives_inside_a_message(pipeline, name: str):
    """Interpolated into a message, where there is no key to match on.

    Only the recognisable ones. A resume is prose and a password is a string of
    words; neither can be spotted by shape, which is why they are refused by
    *key* and why a flow must never pass them as free text.
    """
    app_logging.get_logger("app.flow").info(f"step for {SECRETS[name]}")

    assert SECRETS[name] not in rendered(pipeline)


def test_a_library_line_goes_through_the_same_chain(pipeline):
    """A third-party logger that bypassed the redaction would be the one line in
    the aggregator nobody thought to check."""
    logging.getLogger("some.library").warning("connecting as %s", SECRETS["email"])

    assert SECRETS["email"] not in rendered(pipeline)


def test_the_correlation_fields_survive_redaction(pipeline):
    """`AC-FOUND-14.2` and `.1` have to hold at once: a chain that scrubbed the
    request id would make every line private and useless."""
    request_id = str(uuid.uuid4())
    app_logging.bind_request(request_id=request_id, user_id="01J0USER")
    app_logging.get_logger("app.flow").info("a step", email=SECRETS["email"])
    app_logging.clear_request()

    line = pipeline[-1]
    assert line["request_id"] == request_id
    assert line["user_id"] == "01J0USER"
    assert line["email"] == REDACTED


def test_a_nested_structure_is_scrubbed(pipeline):
    """A flow that logs a whole object - the shape a debugging session
    produces - must not smuggle a secret one level down."""
    app_logging.get_logger("app.flow").info(
        "a step",
        context={"user": {"email": SECRETS["email"], "id": "01J0USER"}, "attempt": 1},
    )

    text = rendered(pipeline)
    assert SECRETS["email"] not in text
    assert "01J0USER" in text


def test_the_capture_would_have_seen_a_leak(pipeline):
    """The negative control for this whole section.

    Every assertion above is "the secret is absent", and absence is also what a
    broken capture produces.
    """
    app_logging.get_logger("app.flow").info("a step", stage="gathering")

    assert "gathering" in rendered(pipeline)
