"""T-FOUND-02.5 - flag resolution with a frozen clock.

`AC-FOUND-02.5`: "A DB override for a flag takes effect within 30 s without a
restart, and removing it reverts to the env value."

Shared with `T-ADMIN-03.2`.

The `feature_flags` collection is owned by `admin` and declared by `DATA-02`,
so the store is injected here as a fake. What is under test is the *resolution
rule* - DB override beats env beats code default, cached 30 s - which is the
part every module depends on and the part that is wrong if it is wrong. The
Mongo-backed store is asserted against a real database by
`tests/integration/test_admin_flags.py` when `ADMIN-03` lands in P4.
"""

from __future__ import annotations

import pytest

from app.core.config import FlagResolver, UnknownFlag

from ..unit.test_config_failfast import COMPLETE_ENV, build


class FakeStore:
    """A `feature_flags` collection whose contents a test can change."""

    def __init__(self, values: dict[str, bool] | None = None) -> None:
        self.values = dict(values or {})
        self.reads = 0

    def overrides(self) -> dict[str, bool]:
        self.reads += 1
        return dict(self.values)


class FrozenClock:
    """A monotonic source the test advances by hand."""

    def __init__(self) -> None:
        self.seconds = 0.0

    def __call__(self) -> float:
        return self.seconds

    def advance(self, by: float) -> None:
        self.seconds += by


@pytest.fixture
def settings():
    return build(COMPLETE_ENV)


def test_the_code_default_applies_with_no_override(settings):
    resolver = FlagResolver(settings, FakeStore(), FrozenClock())
    # `README.md` §1 Call 1: off in production at R1.
    assert resolver.get("llm_rationale_enabled") is False
    assert resolver.get("job_enrichment_enabled") is True


def test_the_env_value_beats_the_code_default():
    settings = build({**COMPLETE_ENV, "FLAG_LLM_RATIONALE_ENABLED": "true"})
    resolver = FlagResolver(settings, FakeStore(), FrozenClock())
    assert resolver.get("llm_rationale_enabled") is True


def test_a_db_override_beats_the_env_value():
    settings = build({**COMPLETE_ENV, "FLAG_LLM_RATIONALE_ENABLED": "true"})
    resolver = FlagResolver(settings, FakeStore({"llm_rationale_enabled": False}), FrozenClock())
    assert resolver.get("llm_rationale_enabled") is False


def test_an_override_takes_effect_within_thirty_seconds(settings):
    """AC-FOUND-02.5, first half."""
    store = FakeStore()
    clock = FrozenClock()
    resolver = FlagResolver(settings, store, clock)

    assert resolver.get("digest_enabled") is False

    store.values["digest_enabled"] = True
    # Inside the cache window the old value still stands - that is the cache
    # doing its job, not a bug.
    clock.advance(29)
    assert resolver.get("digest_enabled") is False

    clock.advance(2)  # 31 s
    assert resolver.get("digest_enabled") is True


def test_removing_an_override_reverts_to_the_env_value(settings):
    """AC-FOUND-02.5, second half."""
    store = FakeStore({"digest_enabled": True})
    clock = FrozenClock()
    resolver = FlagResolver(settings, store, clock)
    assert resolver.get("digest_enabled") is True

    del store.values["digest_enabled"]
    clock.advance(31)
    assert resolver.get("digest_enabled") is False


def test_the_store_is_read_once_per_window(settings):
    """A flag read on every request must not become a query on every request."""
    store = FakeStore()
    clock = FrozenClock()
    resolver = FlagResolver(settings, store, clock)

    for _ in range(50):
        resolver.get("signup_enabled")
    assert store.reads == 1

    clock.advance(31)
    resolver.get("signup_enabled")
    assert store.reads == 2


def test_an_unknown_flag_is_rejected(settings):
    """AC-ADMIN-03.3 - a typo cannot silently do nothing."""
    resolver = FlagResolver(settings, FakeStore(), FrozenClock())
    with pytest.raises(UnknownFlag):
        resolver.get("llm_rationale_enbaled")


def test_resolved_reports_where_each_value_came_from(settings):
    """AC-ADMIN-03.1 / AC-FOUND-15.9 - the admin view shows the source."""
    resolver = FlagResolver(settings, FakeStore({"ocr_enabled": True}), FrozenClock())
    resolved = resolver.resolved()

    assert resolved["ocr_enabled"] == (True, "db")
    assert resolved["signup_enabled"] == (True, "env-or-default")
    assert set(resolved) == set(settings.flag_keys)


def test_the_r1_flag_set_is_the_one_admin_03_names(settings):
    assert settings.flag_keys == (
        "digest_enabled",
        "extension_apply_enabled",
        "ingestion_enabled",
        "job_enrichment_enabled",
        "llm_rationale_enabled",
        "ocr_enabled",
        "push_enabled",
        "signup_enabled",
    )
