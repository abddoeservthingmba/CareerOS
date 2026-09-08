"""T-FOUND-02.1 - startup validation is fail-fast (`01-foundations.md` §2).

`AC-FOUND-02.1`: "Booting with a required variable unset exits non-zero within
5 s and stderr contains the variable name." Parametrized over every required
field, as the Tests list requires.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest
from pydantic import ValidationError

from app.core.config import Settings

# A complete, valid environment. Every test below removes exactly one key from
# it, so "required" is asserted rather than assumed.
COMPLETE_ENV: dict[str, str] = {
    "APP_ENV": "local",
    "PRODUCT_NAME": "JobPilot",
    "API_BASE_URL": "http://localhost:8000",
    "WEB_ORIGIN": "http://localhost:5173",
    "SECRET_KEY": "s" * 32,
    "JWT_PRIVATE_KEY_PEM": "-----BEGIN PRIVATE KEY-----",
    "JWT_PUBLIC_KEY_PEM": "-----BEGIN PUBLIC KEY-----",
    "JWT_ISSUER": "jobpilot",
    "JWT_AUDIENCE": "jobpilot-api",
    "REFRESH_PEPPER": "p" * 32,
    "MONGODB_URI": "mongodb://localhost:27017",
    "MONGODB_DB": "jobpilot",
    "REDIS_URL": "redis://localhost:6379",
    "R2_ACCOUNT_ID": "account",
    "R2_ACCESS_KEY_ID": "key",
    "R2_SECRET_ACCESS_KEY": "secret",
    "R2_BUCKET": "jobpilot-local",
    "R2_PUBLIC_BASE_URL": "http://localhost:9000",
    "CONNECTOR_USER_AGENT": "JobPilot/1.0 (+http://localhost/about)",
    "EMAIL_FROM": "no-reply@localhost",
    "METRICS_TOKEN": "metrics",
}

REQUIRED_FIELDS = sorted(COMPLETE_ENV)


def build(env: dict[str, str]) -> Settings:
    """Construct `Settings` from `env` and nothing else.

    `pydantic-settings` reads `os.environ` as well as the keywords, and the test
    session loads the repository's `.env` so the integration suite can reach
    MongoDB. Without clearing the environment first, removing a key from `env`
    would silently fall back to the real one and every "this variable is
    required" assertion would pass for the wrong reason.
    """
    with mock.patch.dict(os.environ, {}, clear=True):
        return Settings(**env)  # type: ignore[arg-type]


def test_a_complete_environment_boots():
    settings = build(COMPLETE_ENV)
    assert settings.PRODUCT_NAME == "JobPilot"
    assert settings.ACCESS_TOKEN_TTL_MIN == 15


@pytest.mark.parametrize("missing", REQUIRED_FIELDS)
def test_every_required_variable_is_required(missing: str):
    """AC-FOUND-02.1 - and the message names the variable."""
    env = {k: v for k, v in COMPLETE_ENV.items() if k != missing}
    with pytest.raises(ValidationError) as caught:
        build(env)
    assert missing in str(caught.value), f"the failure for a missing {missing} must name it"


def test_no_default_silently_disables_a_feature():
    """§2 - "Never a default that silently disables a feature".

    The optional fields are exactly the credentials for providers that are not
    reachable yet, plus tuning values with a stated default. None of them is a
    switch that turns a built feature off; those are `FLAG_*`.
    """
    optional = {name for name, field in Settings.model_fields.items() if not field.is_required()}
    unexpected = optional - {
        # Provider credentials - absent until that provider is configured.
        "GEMINI_API_KEY",
        "GEMINI_MODEL_FAST",
        "GEMINI_MODEL_QUALITY",
        "GEMINI_EMBEDDING_MODEL",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        # ADR-011's local adapter. Its model ids are configuration for the same
        # reason Gemini's are (`AC-AI-02.2`); the base URL defaults to this
        # machine and is host-validated, so an unset value is the correct one.
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL_FAST",
        "OLLAMA_MODEL_QUALITY",
        "OLLAMA_EMBEDDING_MODEL",
        # `AC-AI-05.7` - the allowlisted default is the value production wants,
        # and anything else fails the boot rather than being silently accepted.
        "GEMINI_BASE_URL",
        "ADZUNA_APP_ID",
        "ADZUNA_APP_KEY",
        "RESEND_API_KEY",
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "SENTRY_DSN",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        # Provider selection, with a documented default.
        "AI_PROVIDER_DEFAULT",
        "AI_EMBEDDING_PROVIDER",
        "AI_PROVIDER_RESUME_EXTRACT",
        "AI_PROVIDER_MATCH_RATIONALE",
        "AI_PROVIDER_PACK_GENERATE",
        "AI_EMBEDDING_MIGRATION",
        "EMAIL_PROVIDER",
        "LOG_LEVEL",
        # Tuning, all with a stated default in `15-infra-and-ops.md` §5.
        "ACCESS_TOKEN_TTL_MIN",
        "REFRESH_TOKEN_TTL_DAYS",
        "AI_DAILY_COST_CAP_USD",
        "AI_USER_DAILY_CALLS",
        "AI_RATIONALE_TOP_N",
        "AI_CACHE_TTL_DAYS",
        "INGEST_MAX_QUERIES_PER_RUN",
        "INGEST_DEFAULT_CRON",
        "RATE_LOGIN_PER_MIN_IP",
        "RATE_LOGIN_PER_MIN_EMAIL",
        "RATE_GENERAL_PER_MIN_USER",
        "AI_PROVIDER_RPM",
        # `05-ai-layer.md` §3.1's optional per-feature caps. Zero means "no cap
        # of its own", not "no spending allowed": the feature is bound by the
        # global cap, which is not optional. Reading zero the other way would
        # deny every feature the moment a variable was left unset, which is the
        # state every deployment starts in.
        *(n for n in Settings.model_fields if n.startswith("AI_FEATURE_CAP_USD__")),
        "SMTP_HOST",
        "SMTP_PORT",
        # `AC-FOUND-16.6`'s webhook fails **closed** without this, so a blank
        # value disables nothing silently: it returns 503 and says why.
        "EMAIL_WEBHOOK_SECRET",
        # `05-ai-layer.md` §5.4 (D5). Optional but not silent: the default is
        # `free`, which is the *more* disclosing of the two positions, and
        # `AC-AI-05.8` fails the build if the copy and this value disagree. A
        # required field here would break every local boot to state the default.
        "AI_CONSENT_TIER",
        # Flags, which are switches on purpose.
        *(n for n in Settings.model_fields if n.startswith("FLAG_")),
    }
    assert unexpected == set(), f"new optional settings need a reason: {sorted(unexpected)}"


def test_an_unknown_variable_is_refused():
    """`extra="forbid"` - a typo in a deploy's environment fails the boot rather
    than being ignored."""
    with pytest.raises(ValidationError):
        build({**COMPLETE_ENV, "MONGO_URI": "mongodb://typo"})


def test_a_short_secret_is_refused():
    with pytest.raises(ValidationError, match="32"):
        build({**COMPLETE_ENV, "SECRET_KEY": "short"})


def test_a_blank_product_name_is_refused():
    with pytest.raises(ValidationError):
        build({**COMPLETE_ENV, "PRODUCT_NAME": "   "})


def test_an_invalid_environment_name_is_refused():
    with pytest.raises(ValidationError):
        build({**COMPLETE_ENV, "APP_ENV": "production"})


def test_settings_are_frozen():
    """Instantiated once in the app factory and injected; nothing mutates it."""
    settings = build(COMPLETE_ENV)
    with pytest.raises(ValidationError):
        settings.PRODUCT_NAME = "Something Else"
