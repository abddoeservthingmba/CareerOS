"""T-FOUND-02.2 - secrets never appear in a repr or a log line.

`AC-FOUND-02.2`: "`repr(settings)` and any log line containing settings show
`**********` for every `SecretStr`."

Settings reach crash reports, `/debug` pages and structured logs by accident far
more often than by design, which is why this is a criterion rather than a
convention.
"""

from __future__ import annotations

import json
import logging

from pydantic import SecretStr

from app.core.config import Settings

from .test_config_failfast import COMPLETE_ENV, build

# Distinctive values, so a leak is unambiguous rather than a substring accident.
SECRET_VALUES = {
    "SECRET_KEY": "SECRETKEY-canary-" + "x" * 20,
    "REFRESH_PEPPER": "PEPPER-canary-" + "y" * 20,
    "MONGODB_URI": "mongodb://user:MONGOPASSWORD-canary@host/db",
    "REDIS_URL": "redis://:REDISPASSWORD-canary@host:6379",
    "R2_SECRET_ACCESS_KEY": "R2SECRET-canary",
    "R2_ACCESS_KEY_ID": "R2KEYID-canary",
    "GEMINI_API_KEY": "GEMINIKEY-canary",
    "RESEND_API_KEY": "RESENDKEY-canary",
    "GOOGLE_OAUTH_CLIENT_SECRET": "OAUTHSECRET-canary",
    "METRICS_TOKEN": "METRICSTOKEN-canary",
    "ADZUNA_APP_KEY": "ADZUNAKEY-canary",
    "SENTRY_DSN": "https://SENTRYDSN-canary@sentry.io/1",
}


def loaded() -> Settings:
    return build({**COMPLETE_ENV, **SECRET_VALUES})


def test_every_secret_field_is_a_secret_str():
    """The property the redaction relies on. A new credential typed as `str`
    would pass the repr test today and leak the first time it is set."""
    settings = loaded()
    for name in SECRET_VALUES:
        assert isinstance(getattr(settings, name), SecretStr), (
            f"{name} holds a credential and must be a SecretStr"
        )


def test_repr_reveals_no_secret():
    """AC-FOUND-02.2."""
    text = repr(loaded())
    for name, value in SECRET_VALUES.items():
        assert value not in text, f"{name} leaked into repr(settings)"
    assert "**********" in text


def test_str_reveals_no_secret():
    text = str(loaded())
    for name, value in SECRET_VALUES.items():
        assert value not in text, f"{name} leaked into str(settings)"


def test_model_dump_reveals_no_secret():
    """The shape that reaches a JSON log line or a Sentry context."""
    dumped = loaded().model_dump()
    text = json.dumps(dumped, default=str)
    for name, value in SECRET_VALUES.items():
        assert value not in text, f"{name} leaked into model_dump()"


def test_a_log_line_carrying_settings_reveals_no_secret(caplog):
    """AC-FOUND-02.2 - "any log line containing settings"."""
    settings = loaded()
    with caplog.at_level(logging.INFO):
        logging.getLogger("boot").info("settings=%s", settings)
        logging.getLogger("boot").info("settings=%r", settings)
    captured = caplog.text
    for name, value in SECRET_VALUES.items():
        assert value not in captured, f"{name} leaked into a log line"


def test_the_secret_is_still_reachable_deliberately():
    """Redaction must not make the value unusable - only hard to leak."""
    settings = loaded()
    assert settings.SECRET_KEY.get_secret_value() == SECRET_VALUES["SECRET_KEY"]


def test_a_non_secret_field_is_visible():
    """The counter-case: if everything were redacted the test above would pass
    for the wrong reason."""
    assert "JobPilot" in repr(loaded())
