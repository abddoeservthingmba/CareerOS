"""T-AI-02.1 - per-feature provider routing (`05-ai-layer.md` §2)."""

from __future__ import annotations

import pytest

from app.ai.base import Feature
from app.ai.fake import FakeLLM
from app.ai.registry import RegistryError, build
from app.ai.stubs import OpenAIProvider

from ..unit.test_config_failfast import COMPLETE_ENV
from ..unit.test_config_failfast import build as settings_for

LLM_FEATURES = [f for f in Feature if not f.value.startswith("embed_")]


def env(**overrides: str):
    return settings_for(
        {
            **COMPLETE_ENV,
            "AI_PROVIDER_DEFAULT": "fake",
            "AI_EMBEDDING_PROVIDER": "fake",
            **overrides,
        }
    )


def test_a_per_feature_override_routes_only_that_feature():
    """AC-AI-02.1 - "routes only that feature to the fake provider; every other
    feature still resolves to the default"."""
    registry = build(env(AI_PROVIDER_DEFAULT="openai", AI_PROVIDER_MATCH_RATIONALE="fake"))

    assert isinstance(registry.llm(Feature.MATCH_RATIONALE), FakeLLM)
    for feature in LLM_FEATURES:
        if feature is Feature.MATCH_RATIONALE:
            continue
        assert isinstance(registry.llm(feature), OpenAIProvider), feature


def test_every_llm_feature_resolves():
    registry = build(env())
    for feature in LLM_FEATURES:
        assert registry.llm(feature) is not None


def test_one_instance_is_shared_across_the_features_it_serves():
    """Providers are constructed once at startup and injected (§2), so a
    per-provider rate limiter and its token bucket are shared."""
    registry = build(env())
    instances = {id(registry.llm(f)) for f in LLM_FEATURES}
    assert len(instances) == 1


def test_the_three_documented_overrides_exist():
    """§2 names AI_PROVIDER_RESUME_EXTRACT, _MATCH_RATIONALE and _PACK_GENERATE."""
    for feature, expected in (
        (Feature.RESUME_EXTRACT, "AI_PROVIDER_RESUME_EXTRACT"),
        (Feature.MATCH_RATIONALE, "AI_PROVIDER_MATCH_RATIONALE"),
        (Feature.PACK_GENERATE, "AI_PROVIDER_PACK_GENERATE"),
    ):
        registry = build(env(AI_PROVIDER_DEFAULT="openai", **{expected: "fake"}))
        assert isinstance(registry.llm(feature), FakeLLM), expected


def test_an_unknown_provider_is_refused():
    with pytest.raises(RegistryError, match="not registered"):
        build(env(AI_PROVIDER_DEFAULT="nonesuch"))


def test_an_unknown_embedding_provider_is_refused():
    with pytest.raises(RegistryError, match="embedding"):
        build(env(AI_EMBEDDING_PROVIDER="nonesuch"))


def test_the_embedder_is_resolved_separately_from_the_llm():
    registry = build(env(AI_PROVIDER_DEFAULT="openai", AI_EMBEDDING_PROVIDER="fake"))
    assert registry.embedder.name == "fake"
    assert registry.embedding_model
