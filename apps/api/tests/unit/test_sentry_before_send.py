"""T-FOUND-14.4 - what leaves for Sentry.

`AC-FOUND-14.4`: "A Sentry event captured in a test has redacted `user.email`
and no request body."

Sentry is the hardest of the three sinks to keep clean, for a reason worth
saying plainly: **an exception report carries the local variables of every
frame**. Nobody writes `logger.info(password)`. What happens is that a
`ValueError` is raised three frames below a login handler, and the SDK
faithfully serialises that handler's arguments on the way up.

So `before_send` is not a formality. It is the only thing between a stack trace
and a vendor's search index, and it operates on data nobody chose to include.

It returns the event rather than dropping it. Dropping would protect the data
and lose the error, and an unreported 500 is a user stuck on a screen nobody
knows about. The report survives; the person in it does not.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.redaction import REDACTED
from app.core.sentry import before_send

EMAIL = "someone.private@example.test"
PASSWORD = "correct-horse-battery-staple"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.9lPPqLNi3xF-Vhqm2xkTBQfVfPqAjRZzRk2q1Q"
RESUME = "Senior engineer with eleven years at a payments company"


def event_with(**overrides: Any) -> dict[str, Any]:
    """A Sentry event of the shape the SDK actually produces."""
    base: dict[str, Any] = {
        "event_id": "0123456789abcdef0123456789abcdef",
        "level": "error",
        "message": "something failed",
        "request": {
            "method": "POST",
            "url": "https://api.example.test/api/v1/auth/login",
            "headers": {"Authorization": f"Bearer {JWT}", "User-Agent": "curl/8"},
            "cookies": {"session": "abc123"},
            "data": {"email": EMAIL, "password": PASSWORD},
            "query_string": f"email={EMAIL}",
        },
        "user": {"id": "01J000000000000000000USER", "email": EMAIL, "ip_address": "203.0.113.9"},
        "extra": {"resume_text": RESUME, "attempt": 2},
        "contexts": {"trace": {"trace_id": "abc"}},
    }
    base.update(overrides)
    return base


def flatten(value: Any) -> str:
    """Everything in the event, as one string.

    Asserting field by field would pass while a value sat somewhere nobody
    thought to look - which is exactly how these leaks happen.
    """
    import json

    return json.dumps(value, default=str)


# -- the criterion -----------------------------------------------------------


def test_the_user_email_is_removed():
    """AC-FOUND-14.4, first half."""
    sent = before_send(event_with())

    assert "email" not in sent["user"]
    assert EMAIL not in flatten(sent)


def test_the_request_body_is_removed():
    """AC-FOUND-14.4, second half.

    There is no version of a request body that is safe to keep: a password on
    `/auth/login`, a resume on `/profile/resumes`, a cover letter everywhere
    else.
    """
    sent = before_send(event_with())

    assert "data" not in sent["request"]
    assert "body" not in sent["request"]
    assert PASSWORD not in flatten(sent)


def test_the_user_id_survives():
    """The control, and the point. An error report with no user is an error
    nobody can act on; `user.id` joins to the logs, which join to the request."""
    sent = before_send(event_with())

    assert sent["user"] == {"id": "01J000000000000000000USER"}


def test_the_ip_address_is_removed():
    """An IP is personal data under GDPR and identifies a household. It is also
    not what makes a stack trace actionable."""
    sent = before_send(event_with())

    assert "ip_address" not in sent["user"]
    assert "203.0.113.9" not in flatten(sent)


def test_the_event_is_still_sent():
    """Dropping the report would protect the data and lose the error, and an
    unreported 500 is a user stuck on a screen nobody knows about."""
    sent = before_send(event_with())

    assert sent["event_id"] == "0123456789abcdef0123456789abcdef"
    assert sent["level"] == "error"


# -- everywhere else a value hides -------------------------------------------


def test_the_authorization_header_is_redacted():
    sent = before_send(event_with())

    assert JWT not in flatten(sent)
    assert sent["request"]["headers"]["Authorization"] == REDACTED
    assert sent["request"]["headers"]["User-Agent"] == "curl/8"


def test_the_cookies_are_redacted():
    """A session cookie in an error report is a session anyone with dashboard
    access can assume."""
    sent = before_send(event_with())

    assert sent["request"]["cookies"] == REDACTED
    assert "abc123" not in flatten(sent)


def test_the_query_string_is_scrubbed():
    """An address in a query string is an address in the URL, which is also in
    the referrer, the access log and the browser history."""
    sent = before_send(event_with())

    assert EMAIL not in sent["request"]["query_string"]


def test_the_url_survives_but_scrubbed():
    """The URL is what makes a report locatable, so it stays - with anything
    recognisable removed from it."""
    sent = before_send(event_with(request={"url": f"https://x.test/reset/{JWT}", "method": "GET"}))

    assert JWT not in sent["request"]["url"]
    assert "https://x.test/reset/" in sent["request"]["url"]


def test_extra_fields_are_scrubbed():
    """`extra` is where a developer puts the thing they were debugging, which is
    reliably the most sensitive value in scope."""
    sent = before_send(event_with())

    assert sent["extra"]["resume_text"] == REDACTED
    assert sent["extra"]["attempt"] == 2
    assert RESUME not in flatten(sent)


def test_the_message_is_scrubbed():
    """The leak that actually happens: an address interpolated into a string,
    where there is no key to match on."""
    sent = before_send(event_with(message=f"no account for {EMAIL}"))

    assert EMAIL not in sent["message"]
    assert "no account for" in sent["message"]


def test_breadcrumbs_are_scrubbed():
    """Breadcrumbs are the last twenty log lines, attached to the event. They
    have been through the log redaction already; going through this one too is
    cheap, and the alternative is trusting that they always will have."""
    sent = before_send(
        event_with(breadcrumbs=[{"message": f"looked up {EMAIL}", "data": {"password": PASSWORD}}])
    )

    assert EMAIL not in flatten(sent["breadcrumbs"])
    assert PASSWORD not in flatten(sent["breadcrumbs"])


# -- the stack trace, which is the hard part ---------------------------------


def exception_event() -> dict[str, Any]:
    """The shape the SDK builds from a real traceback."""
    return {
        "event_id": "f" * 32,
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": f"invalid credentials for {EMAIL}",
                    "stacktrace": {
                        "frames": [
                            {
                                "function": "login",
                                "vars": {
                                    "email": EMAIL,
                                    "password": PASSWORD,
                                    "attempt": 1,
                                },
                            },
                            {
                                "function": "verify",
                                "vars": {"token": JWT, "user_id": "01J0USER"},
                            },
                        ]
                    },
                }
            ]
        },
    }


def test_frame_locals_are_scrubbed():
    """The most important assertion in this file.

    A `ValueError` raised below a login handler carries that handler's arguments
    in `frame.vars`, and nobody chose to put them there.
    """
    sent = before_send(exception_event())
    frames = sent["exception"]["values"][0]["stacktrace"]["frames"]

    assert frames[0]["vars"]["password"] == REDACTED
    assert frames[0]["vars"]["email"] == REDACTED
    assert frames[1]["vars"]["token"] == REDACTED
    assert PASSWORD not in flatten(sent)
    assert JWT not in flatten(sent)


def test_harmless_frame_locals_survive():
    """Scrubbing everything would make the report useless, which is how a
    redaction rule gets switched off."""
    sent = before_send(exception_event())
    frames = sent["exception"]["values"][0]["stacktrace"]["frames"]

    assert frames[0]["vars"]["attempt"] == 1
    assert frames[1]["vars"]["user_id"] == "01J0USER"
    assert frames[0]["function"] == "login"


def test_the_exception_message_is_scrubbed():
    sent = before_send(exception_event())

    assert EMAIL not in sent["exception"]["values"][0]["value"]
    assert "invalid credentials" in sent["exception"]["values"][0]["value"]


def test_the_exception_type_survives():
    sent = before_send(exception_event())

    assert sent["exception"]["values"][0]["type"] == "ValueError"


# -- shapes that must not crash it -------------------------------------------


@pytest.mark.parametrize(
    "event",
    [
        {},
        {"request": None},
        {"user": "not-a-dict"},
        {"exception": {"values": "not-a-list"}},
        {"exception": {"values": [None, 42]}},
        {"exception": {"values": [{"stacktrace": {"frames": ["not-a-frame"]}}]}},
    ],
    ids=["empty", "null-request", "string-user", "string-values", "junk-values", "junk-frame"],
)
def test_a_malformed_event_does_not_raise(event: dict[str, Any]):
    """`before_send` runs inside the SDK's error path. Raising here loses the
    original error *and* produces a second one nobody can see, because the
    reporter is the thing that broke."""
    assert isinstance(before_send(dict(event)), dict)


def test_the_original_event_is_not_mutated():
    """The SDK reuses the event object. Mutating it in place would strip fields
    from anything else holding a reference - including the local breadcrumb
    buffer."""
    original = event_with()
    before_send(original)

    assert original["user"]["email"] == EMAIL
    assert original["request"]["data"]["password"] == PASSWORD


# -- the installation --------------------------------------------------------


def test_no_dsn_means_no_sentry():
    """The normal state locally and in tests. Treating it as an error would mean
    a noisy startup or a `try/except` around every call site."""
    from app.core.sentry import configure

    assert configure("", environment="local") is False


def test_the_sdk_is_told_not_to_collect_pii():
    """Belt to `before_send`'s braces. Not collecting the address is stronger
    than removing it afterwards, so a future bug in this module fails safe."""
    import inspect

    from app.core import sentry

    source = inspect.getsource(sentry.configure)
    assert "send_default_pii=False" in source
    assert 'max_request_body_size="never"' in source
