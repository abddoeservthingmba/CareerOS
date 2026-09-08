"""Typed settings and feature flags - `FOUND-02`.

`01-foundations.md` §2: "One typed settings object, populated only from the
environment, validated at startup, with a committed example that cannot drift
from it."

Four constraints shape this module:

* **One `Settings` class, instantiated once and injected.** No module reads
  `os.environ` - including AI adapters (HR-6) and connectors. `AC-AI-05.4`
  asserts the Gemini adapter has no path to the environment at all, and that is
  only true if every credential arrives by constructor injection from here.
* **Every secret is a `SecretStr`.** `repr(settings)` must not reveal one
  (`AC-FOUND-02.2`), because settings end up in crash reports.
* **Startup validation is fail-fast.** A missing required variable aborts the
  boot naming the variable (`AC-FOUND-02.1`). "Never a default that silently
  disables a feature" - a product that boots with no `SECRET_KEY` and signs
  tokens with an empty string is worse than one that refuses to start.
* **Flags resolve DB -> env -> code default, cached 30 s** (`AC-FOUND-02.5`).

The R2/R3 credentials that `15-infra-and-ops.md` §5 lists with `# R2` / `# R3`
markers - `FIREBASE_SERVICE_ACCOUNT_JSON_B64`, `VAPID_*` - are deliberately
absent here and from `.env.example`. `AC-FOUND-15.6` says an `absent` section
has no flag and no config, and they arrive with `NOTIF-02b` / `NOTIF-02c`. The
R2 *flags* stay, because `ADMIN-03` §3 names them in the R1 flag set.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal, Protocol

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

FLAG_CACHE_SECONDS = 30


class AppEnv(StrEnum):
    LOCAL = "local"
    STAGING = "staging"
    PROD = "prod"


class Settings(BaseSettings):
    """Every variable the API and worker read, and nothing else."""

    model_config = SettingsConfigDict(
        env_file=None,  # the process environment only; compose loads .env
        case_sensitive=True,
        extra="forbid",
        frozen=True,
    )

    # -- core ---------------------------------------------------------------
    APP_ENV: AppEnv
    PRODUCT_NAME: str
    API_BASE_URL: str
    WEB_ORIGIN: str
    SECRET_KEY: SecretStr

    JWT_PRIVATE_KEY_PEM: SecretStr
    JWT_PUBLIC_KEY_PEM: str
    JWT_ISSUER: str
    JWT_AUDIENCE: str
    ACCESS_TOKEN_TTL_MIN: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 30
    REFRESH_PEPPER: SecretStr

    # -- data ---------------------------------------------------------------
    MONGODB_URI: SecretStr
    MONGODB_DB: str
    REDIS_URL: SecretStr

    # -- storage (R2, S3-compatible) ----------------------------------------
    R2_ACCOUNT_ID: str
    R2_ACCESS_KEY_ID: SecretStr
    R2_SECRET_ACCESS_KEY: SecretStr
    R2_BUCKET: str
    R2_PUBLIC_BASE_URL: str

    # -- ai (see 05-ai-layer.md §5 for the isolation rules) -----------------
    AI_PROVIDER_DEFAULT: str = "gemini"
    AI_EMBEDDING_PROVIDER: str = "gemini"
    AI_PROVIDER_RESUME_EXTRACT: str = ""
    AI_PROVIDER_MATCH_RATIONALE: str = ""
    AI_PROVIDER_PACK_GENERATE: str = ""

    GEMINI_API_KEY: SecretStr = SecretStr("")
    # Model identifiers are configuration, never code (`AC-AI-02.2`). Gemini's
    # names and free-tier limits change often enough that a hard-coded one is a
    # scheduled outage.
    GEMINI_MODEL_FAST: str = ""
    GEMINI_MODEL_QUALITY: str = ""
    GEMINI_EMBEDDING_MODEL: str = ""
    # `AC-AI-05.7`: configurable for the record-and-replay tests, and validated
    # against an allowlist at startup - a base URL is a host this product sends
    # resume text to, so a proxy in the middle is an exfiltration target.
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com"

    # `ollama` is the local-development provider (ADR-011). No key: nothing to
    # inject, nothing to leak, and no resume text leaves the machine.
    OLLAMA_MODEL_FAST: str = ""
    OLLAMA_MODEL_QUALITY: str = ""
    OLLAMA_EMBEDDING_MODEL: str = ""

    AI_DAILY_COST_CAP_USD: float = 2.0
    AI_USER_DAILY_CALLS: int = 500
    # `05-ai-layer.md` §3.1: "`AI_FEATURE_CAP_USD__<FEATURE>` (optional, per
    # feature)". Ten explicit fields rather than a prefix scan, because
    # `extra="forbid"` is what makes a typo in a deploy's environment fail the
    # boot (`AC-FOUND-02.1`) - and a scan would have to relax it, turning
    # `AI_FEATURE_CAP_USD__PAKC_GENERATE` into a cap that silently never binds.
    AI_FEATURE_CAP_USD__RESUME_EXTRACT: float = 0
    AI_FEATURE_CAP_USD__RESUME_QUALITY: float = 0
    AI_FEATURE_CAP_USD__JOB_ENRICH: float = 0
    AI_FEATURE_CAP_USD__MATCH_RATIONALE: float = 0
    AI_FEATURE_CAP_USD__PACK_GENERATE: float = 0
    AI_FEATURE_CAP_USD__FOLLOWUP_DRAFT: float = 0
    AI_FEATURE_CAP_USD__ANSWER_SUGGEST: float = 0
    AI_FEATURE_CAP_USD__EMBED_PROFILE: float = 0
    AI_FEATURE_CAP_USD__EMBED_JOB: float = 0
    AI_FEATURE_CAP_USD__EMBED_QUESTION: float = 0

    #: The provider's requests-per-minute limit. §3.1's token bucket queues at
    #: this rate rather than rejecting, so a burst drains instead of failing.
    AI_PROVIDER_RPM: int = 15

    AI_RATIONALE_TOP_N: int = 20
    AI_CACHE_TTL_DAYS: int = 7
    AI_EMBEDDING_MIGRATION: Literal["", "allow"] = ""

    # `05-ai-layer.md` §5.4 (D5). Which provider terms are in force, stated
    # rather than inferred: a paid Gemini key and a free one are the same
    # string, so nothing about the credential reveals which terms apply.
    # `AC-AI-05.8` compares this against the consent copy, so getting it wrong
    # fails the build rather than misleading a user.
    AI_CONSENT_TIER: Literal["free", "paid"] = "free"

    OPENAI_API_KEY: SecretStr = SecretStr("")
    ANTHROPIC_API_KEY: SecretStr = SecretStr("")
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"

    # -- connectors ---------------------------------------------------------
    ADZUNA_APP_ID: SecretStr = SecretStr("")
    ADZUNA_APP_KEY: SecretStr = SecretStr("")
    INGEST_MAX_QUERIES_PER_RUN: int = 40
    INGEST_DEFAULT_CRON: str = "0 */6 * * *"
    CONNECTOR_USER_AGENT: str

    # -- comms --------------------------------------------------------------
    EMAIL_PROVIDER: Literal["resend", "ses", "mailpit"] = "resend"
    RESEND_API_KEY: SecretStr = SecretStr("")
    EMAIL_FROM: str
    # `AC-FOUND-16.6`'s webhook fails closed without this: an unauthenticated
    # bounce endpoint lets anyone stop a chosen user from receiving a password
    # reset, which is an account-takeover step rather than a nuisance.
    EMAIL_WEBHOOK_SECRET: SecretStr = SecretStr("")
    SMTP_HOST: str = "127.0.0.1"
    SMTP_PORT: int = 1025

    # -- oauth (sign-in only - never reachable from the AI path, HR-6) ------
    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: SecretStr = SecretStr("")

    # -- observability ------------------------------------------------------
    SENTRY_DSN: SecretStr = SecretStr("")
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    METRICS_TOKEN: SecretStr

    # -- flags (a DB override beats these; `ADMIN-03` §3) -------------------
    FLAG_LLM_RATIONALE_ENABLED: bool = False
    FLAG_JOB_ENRICHMENT_ENABLED: bool = True
    FLAG_OCR_ENABLED: bool = False
    FLAG_EXTENSION_APPLY_ENABLED: bool = False
    FLAG_DIGEST_ENABLED: bool = False
    FLAG_PUSH_ENABLED: bool = False
    FLAG_SIGNUP_ENABLED: bool = True
    FLAG_INGESTION_ENABLED: bool = True

    # -- limits (config, not literals - `AC-AUTH-09.6`) ---------------------
    RATE_LOGIN_PER_MIN_IP: int = 10
    RATE_LOGIN_PER_MIN_EMAIL: int = 5
    RATE_GENERAL_PER_MIN_USER: int = 300

    @field_validator("PRODUCT_NAME", "CONNECTOR_USER_AGENT", "EMAIL_FROM")
    @classmethod
    def _must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("SECRET_KEY", "REFRESH_PEPPER")
    @classmethod
    def _secret_must_have_length(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("must be at least 32 characters")
        return value

    # -- derived ------------------------------------------------------------

    @property
    def is_production(self) -> bool:
        return self.APP_ENV is AppEnv.PROD

    def flag_default(self, key: str) -> bool:
        """The code/env default for a flag, before any DB override."""
        field = f"FLAG_{key.upper()}"
        if field not in type(self).model_fields:
            raise UnknownFlag(key)
        return bool(getattr(self, field))

    @property
    def flag_keys(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                name.removeprefix("FLAG_").lower()
                for name in type(self).model_fields
                if name.startswith("FLAG_")
            )
        )


class UnknownFlag(KeyError):
    """`AC-ADMIN-03.3`: a flag the code does not know is rejected on write, so a
    typo cannot silently do nothing."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key

    def __str__(self) -> str:
        return f"unknown feature flag {self.key!r}"


class FlagStore(Protocol):
    """The `feature_flags` collection, as the resolver sees it.

    A protocol rather than a Mongo client so the resolution rule is testable
    without a database, and so `admin` owns the collection (`DATA-02`).
    """

    def overrides(self) -> dict[str, bool]: ...


class NoOverrides:
    """The store before `DATA-02` exists, and in any context with no database."""

    def overrides(self) -> dict[str, bool]:
        return {}


class FlagResolver:
    """DB override -> env (`FLAG_*`) -> code default, cached for 30 seconds.

    The cache is what makes `AC-FOUND-02.5` "within 30 s without a restart"
    true in both directions: an override appears within a window, and removing
    it reverts within a window.
    """

    def __init__(
        self,
        settings: Settings,
        store: FlagStore | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        ttl: float = FLAG_CACHE_SECONDS,
    ) -> None:
        self._settings = settings
        self._store = store or NoOverrides()
        self._monotonic = monotonic
        self._ttl = ttl
        self._cache: dict[str, bool] = {}
        self._fetched_at: float | None = None

    def _refresh_if_stale(self) -> None:
        now = self._monotonic()
        if self._fetched_at is None or (now - self._fetched_at) >= self._ttl:
            self._cache = dict(self._store.overrides())
            self._fetched_at = now

    def get(self, key: str) -> bool:
        default = self._settings.flag_default(key)  # raises on an unknown key
        self._refresh_if_stale()
        return self._cache.get(key, default)

    def resolved(self) -> dict[str, tuple[bool, str]]:
        """Every flag with its value and where the value came from.

        `AC-ADMIN-03.1` and `AC-FOUND-15.9`: the admin view shows the source,
        because the commonest flag confusion is an env value silently
        overriding an expectation.
        """
        self._refresh_if_stale()
        out: dict[str, tuple[bool, str]] = {}
        for key in self._settings.flag_keys:
            if key in self._cache:
                out[key] = (self._cache[key], "db")
            else:
                out[key] = (self._settings.flag_default(key), "env-or-default")
        return out

    def invalidate(self) -> None:
        self._fetched_at = None


# The app factory builds these once and injects them (`01-foundations.md` §2).
# `lru_cache` gives a single instance per process without a module-level global
# that tests cannot replace.
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


SettingsDep = Annotated[Settings, Field(description="Injected application settings")]
