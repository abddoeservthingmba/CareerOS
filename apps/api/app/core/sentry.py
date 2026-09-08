"""Error reporting - `FOUND-14`.

`01-foundations.md` §14: "Sentry for API, web, and mobile, with `before_send`
applying the same redaction list."

Sentry is the hardest of the three sinks to keep clean, and the reason is worth
stating: **an exception report carries the local variables of every frame**.
Nobody writes `logger.info(password)`, but a `ValueError` raised three frames
below a login handler carries that handler's arguments up with it, and by
default they are all serialised and uploaded.

So `before_send` is not a formality. It is the only thing between a stack trace
and a vendor's search index, and it runs on data nobody chose to include.

Four things it does, in order:

1. **Drops the request body entirely** (`AC-FOUND-14.4`). There is no version of
   a request body that is safe to keep: it is a password on `/auth/login`, a
   resume on `/profile/resumes`, and a cover letter everywhere else.
2. **Redacts the user to an id.** `user.id` stays, because that is what makes an
   error report actionable; `user.email` and `user.ip_address` go.
3. **Scrubs every frame's locals** with the same list the logs use.
4. **Scrubs the message and the exception value**, because the leak that
   actually happens is an address interpolated into an error string.

The list is `core.redaction`'s, shared with the log processor. Two lists would
disagree, and the one that disagreed would be whichever had been updated less
recently.
"""

from __future__ import annotations

from typing import Any

from app.core.redaction import REDACTED, scrub, scrub_text

#: Kept on the event because they identify *where* rather than *who*.
SAFE_USER_FIELDS = ("id",)


def before_send(event: dict[str, Any], _hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """`AC-FOUND-14.4` - the last thing that runs before an event leaves.

    Returns the event rather than `None`: dropping the report entirely would
    protect the data and lose the error, and an unreported 500 is a user stuck
    on a screen nobody knows about.
    """
    event = dict(event)

    request = event.get("request")
    if isinstance(request, dict):
        event["request"] = _scrub_request(request)

    user = event.get("user")
    if isinstance(user, dict):
        event["user"] = _scrub_user(user)

    if "extra" in event:
        event["extra"] = scrub(event["extra"])
    if "contexts" in event:
        event["contexts"] = scrub(event["contexts"])
    if "breadcrumbs" in event:
        event["breadcrumbs"] = scrub(event["breadcrumbs"])
    if isinstance(event.get("message"), str):
        event["message"] = scrub_text(event["message"])

    if isinstance(event.get("exception"), dict):
        event["exception"] = _scrub_exception(event["exception"])

    return event


def _scrub_request(request: dict[str, Any]) -> dict[str, Any]:
    """The body goes; the shape stays.

    Method, URL and status are what make a report locatable. The body is never
    safe: a password on `/auth/login`, a resume on `/profile/resumes`, a cover
    letter everywhere else.
    """
    cleaned = dict(request)
    cleaned.pop("data", None)
    cleaned.pop("body", None)
    if isinstance(cleaned.get("headers"), dict):
        cleaned["headers"] = scrub(cleaned["headers"])
    if isinstance(cleaned.get("cookies"), dict):
        cleaned["cookies"] = REDACTED
    if isinstance(cleaned.get("query_string"), str):
        cleaned["query_string"] = scrub_text(cleaned["query_string"])
    if isinstance(cleaned.get("url"), str):
        cleaned["url"] = scrub_text(cleaned["url"])
    return cleaned


def _scrub_user(user: dict[str, Any]) -> dict[str, Any]:
    """An id, not a person.

    `user.id` is what makes an error report actionable - it joins to the logs,
    which join to the request. Everything else about the user is a copy of the
    user table in a vendor's search index.
    """
    return {key: user[key] for key in SAFE_USER_FIELDS if key in user}


def _scrub_exception(exception: dict[str, Any]) -> dict[str, Any]:
    """Every frame's locals, and the exception's own text.

    This is the part that matters. A `ValueError` raised below a login handler
    carries that handler's arguments in `frame.vars`, and nobody chose to put
    them there.
    """
    cleaned = dict(exception)
    values = cleaned.get("values")
    if not isinstance(values, list):
        return cleaned

    scrubbed_values = []
    for entry in values:
        if not isinstance(entry, dict):
            scrubbed_values.append(entry)
            continue
        item = dict(entry)
        if isinstance(item.get("value"), str):
            item["value"] = scrub_text(item["value"])
        stacktrace = item.get("stacktrace")
        if isinstance(stacktrace, dict) and isinstance(stacktrace.get("frames"), list):
            item["stacktrace"] = {
                **stacktrace,
                "frames": [
                    {**frame, "vars": scrub(frame.get("vars", {}))}
                    if isinstance(frame, dict)
                    else frame
                    for frame in stacktrace["frames"]
                ],
            }
        scrubbed_values.append(item)
    cleaned["values"] = scrubbed_values
    return cleaned


def configure(dsn: str, environment: str, release: str = "") -> bool:
    """Install Sentry, or do nothing and say so.

    Returns whether it was installed. An unset DSN is the normal state locally
    and in tests, and treating it as an error would mean either a noisy startup
    or a `try/except` around every call site.

    `send_default_pii=False` is belt to `before_send`'s braces: it stops the SDK
    collecting the address in the first place, so a future `before_send` bug
    fails safe rather than open.
    """
    if not dsn:
        return False

    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release or None,
        before_send=before_send,  # type: ignore[arg-type]
        # Never. The SDK's own idea of "personally identifiable information"
        # includes the address and the IP, and not collecting them is stronger
        # than removing them afterwards.
        send_default_pii=False,
        # A sample rather than everything: traces are for finding the shape of a
        # latency problem, and 100% of them costs money to learn nothing extra.
        traces_sample_rate=0.1,
        max_request_body_size="never",
    )
    return True


__all__ = ["SAFE_USER_FIELDS", "before_send", "configure"]
