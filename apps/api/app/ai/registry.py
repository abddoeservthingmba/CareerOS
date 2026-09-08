"""Feature -> provider resolution - `AI-02`.

`05-ai-layer.md` §2: "Change which model serves a feature by changing
configuration, with no code edit and no redeploy of a feature module."

Three properties, each with a criterion behind it:

* **Providers are constructed once at startup and injected.** An adapter never
  reads the environment (`AC-AI-05.4`), so its credential arrives here.
* **Resolution fails at startup, not at first call** (`AC-AI-02.5`). A feature
  whose provider is unconfigured must break the boot, not the first user who
  uploads a resume at 2am.
* **Changing the embedding model is a migration, not a config flip**
  (`AC-AI-02.4`). The registry refuses to start when the configured embedding
  model differs from the one recorded in `system_state`, unless
  `AI_EMBEDDING_MIGRATION=allow`, which also enqueues a re-embedding.

`gemini.py` is `AI-05`'s deliverable and registers itself here when it lands;
until then `gemini` resolves to a stub that refuses, so nothing silently falls
back to a different model.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.ai.base import EmbeddingProvider, Feature, LLMProvider
from app.ai.fake import FakeEmbedder, FakeLLM
from app.ai.stubs import AnthropicProvider, OpenAIProvider
from app.core.config import Settings

if TYPE_CHECKING:
    from app.ai.gemini import GeminiProvider
    from app.ai.ollama import OllamaProvider


class RegistryError(RuntimeError):
    """A configuration problem that must stop the boot."""


class EmbeddingMigrationRequired(RegistryError):
    """`AC-AI-02.4`: the configured embedding model is not the stored one.

    Switching requires re-embedding every profile and job, so this refuses to
    start rather than quietly comparing vectors from two different models.
    """


# The per-feature override variable each feature reads, where one exists.
# `05-ai-layer.md` §2 names three; the rest fall through to the default.
FEATURE_OVERRIDES: dict[Feature, str] = {
    Feature.RESUME_EXTRACT: "AI_PROVIDER_RESUME_EXTRACT",
    Feature.MATCH_RATIONALE: "AI_PROVIDER_MATCH_RATIONALE",
    Feature.PACK_GENERATE: "AI_PROVIDER_PACK_GENERATE",
}

LLMFactory = Callable[[Settings], LLMProvider]
EmbedderFactory = Callable[[Settings], EmbeddingProvider]


def _fake_llm(_: Settings) -> LLMProvider:
    return FakeLLM()


def _ollama(settings: Settings) -> OllamaProvider:
    """The local-development provider (ADR-011).

    Constructed here, once, at startup - like every other adapter. It takes no
    credential, so there is nothing to inject beyond the model ids and the base
    URL, both of which are configuration (`AC-AI-02.2`).

    The HTTP transport is attached separately by `main.py`, which is the one
    place allowed to own a client: an adapter that built its own would be an
    adapter with a path to the network that startup validation never saw.
    """
    from app.ai.ollama import OllamaProvider

    return OllamaProvider(
        model_fast=settings.OLLAMA_MODEL_FAST,
        model_quality=settings.OLLAMA_MODEL_QUALITY,
        embedding_model=settings.OLLAMA_EMBEDDING_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        app_env=settings.APP_ENV.value,
    )


def _gemini(settings: Settings) -> GeminiProvider:
    """`AI-05`'s adapter. One credential, injected, and no way to find another."""
    from app.ai.gemini import GeminiProvider

    return GeminiProvider(
        settings.GEMINI_API_KEY.get_secret_value(),
        model_fast=settings.GEMINI_MODEL_FAST,
        model_quality=settings.GEMINI_MODEL_QUALITY,
        embedding_model=settings.GEMINI_EMBEDDING_MODEL,
        base_url=settings.GEMINI_BASE_URL,
    )


def _fake_embedder(_: Settings) -> EmbeddingProvider:
    return FakeEmbedder()


LLM_FACTORIES: dict[str, LLMFactory] = {
    "fake": _fake_llm,
    "gemini": _gemini,
    "ollama": _ollama,
    "openai": lambda _: OpenAIProvider(),
    "anthropic": lambda _: AnthropicProvider(),
}

EMBEDDER_FACTORIES: dict[str, EmbedderFactory] = {
    "fake": _fake_embedder,
    "gemini": _gemini,
    "ollama": _ollama,
}


def register_llm(name: str, factory: LLMFactory) -> None:
    """Used by `ai/gemini.py` (`AI-05`) to add the real adapter."""
    LLM_FACTORIES[name] = factory


def register_embedder(name: str, factory: EmbedderFactory) -> None:
    EMBEDDER_FACTORIES[name] = factory


@dataclass(frozen=True)
class Registry:
    """Every provider the process will use, built once."""

    by_feature: Mapping[Feature, LLMProvider]
    embedder: EmbeddingProvider
    embedding_model: str

    def llm(self, feature: Feature) -> LLMProvider:
        try:
            return self.by_feature[feature]
        except KeyError as exc:  # pragma: no cover - build() covers every member
            raise RegistryError(f"no provider resolved for {feature}") from exc


def _provider_name(settings: Settings, feature: Feature) -> str:
    override_field = FEATURE_OVERRIDES.get(feature)
    if override_field:
        override = str(getattr(settings, override_field, "") or "").strip()
        if override:
            return override
    return settings.AI_PROVIDER_DEFAULT.strip()


def build(settings: Settings, stored_embedding_model: str | None = None) -> Registry:
    """Resolve every feature at startup.

    `AC-AI-02.5`: a feature with no override and no default configured raises
    here, not at first call.
    """
    default = settings.AI_PROVIDER_DEFAULT.strip()
    if not default:
        raise RegistryError("AI_PROVIDER_DEFAULT is not set; every feature would be unresolvable")

    by_feature: dict[Feature, LLMProvider] = {}
    built: dict[str, LLMProvider] = {}
    for feature in Feature:
        if feature.value.startswith("embed_"):
            continue
        name = _provider_name(settings, feature)
        if name not in LLM_FACTORIES:
            raise RegistryError(
                f"{feature.value} resolves to provider {name!r}, which is not registered; "
                f"known providers: {sorted(LLM_FACTORIES)}"
            )
        # One instance per provider, shared across the features it serves.
        if name not in built:
            built[name] = LLM_FACTORIES[name](settings)
        by_feature[feature] = built[name]

    embedding_name = settings.AI_EMBEDDING_PROVIDER.strip()
    if embedding_name not in EMBEDDER_FACTORIES:
        raise RegistryError(
            f"AI_EMBEDDING_PROVIDER is {embedding_name!r}, which is not registered; "
            f"known embedding providers: {sorted(EMBEDDER_FACTORIES)}"
        )
    embedder = EMBEDDER_FACTORIES[embedding_name](settings)

    _guard_embedding_model(settings, embedder.model, stored_embedding_model)

    return Registry(by_feature=by_feature, embedder=embedder, embedding_model=embedder.model)


def _guard_embedding_model(settings: Settings, configured: str, stored: str | None) -> None:
    """`AC-AI-02.4` - a changed embedding model stops the boot unless allowed."""
    if stored is None or stored == configured:
        return
    if settings.AI_EMBEDDING_MIGRATION == "allow":
        return
    raise EmbeddingMigrationRequired(
        f"the stored embedding model is {stored!r} but {configured!r} is configured. "
        "Every profile and job embedding would have to be recomputed. Set "
        "AI_EMBEDDING_MIGRATION=allow to start and enqueue ai.reembed_all."
    )


def migration_requested(settings: Settings, configured: str, stored: str | None) -> bool:
    """True when the boot should enqueue `ai.reembed_all` (`AC-AI-02.4`)."""
    return (
        settings.AI_EMBEDDING_MIGRATION == "allow" and stored is not None and stored != configured
    )
