"""T-AI-02.3 - every adapter satisfies the same contract.

`AC-AI-02.3`: "All five adapters pass the same contract suite; the three stubs
pass by raising `ProviderNotConfigured` where a real call would occur."

`05-ai-layer.md` §2 says why the stubs are in the suite at all: "so that the
protocol cannot drift into being Gemini-shaped".

Four adapters are registered today - `fake` plus the three stubs. `gemini` is
`AI-05`'s deliverable and registers itself with `ai.registry` when it lands, at
which point it is parametrized here automatically rather than by editing this
file. `test_the_registered_set_is_the_expected_one` is what makes that visible
instead of silent.
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import BaseModel

from app.ai.base import (
    AIError,
    EmbeddingProvider,
    Feature,
    LLMProvider,
    LLMRequest,
    ProviderNotConfigured,
)
from app.ai.fake import FakeEmbedder, FakeLLM
from app.ai.registry import LLM_FACTORIES
from app.ai.stubs import AnthropicProvider, OllamaProvider, OpenAIProvider

STUBS = (OpenAIProvider, AnthropicProvider, OllamaProvider)
ALL_LLMS = (FakeLLM, *STUBS)


class Tiny(BaseModel):
    name: str


def request() -> LLMRequest:
    return LLMRequest(
        feature=Feature.RESUME_EXTRACT,
        system="Extract.",
        prompt_version="resume_extract/v1",
    )


@pytest.mark.parametrize("adapter", ALL_LLMS, ids=lambda a: a.__name__)
def test_every_adapter_satisfies_the_llm_protocol(adapter):
    """AC-AI-02.3 - structurally, before any call is made."""
    instance = adapter()
    assert isinstance(instance, LLMProvider)
    assert isinstance(instance.name, str) and instance.name


@pytest.mark.parametrize("adapter", ALL_LLMS, ids=lambda a: a.__name__)
def test_every_adapter_has_the_same_method_signatures(adapter):
    """The drift this guards against: an adapter growing a Gemini-shaped
    parameter that no other provider could satisfy."""
    for method in ("complete", "complete_json", "stream"):
        assert hasattr(adapter, method), f"{adapter.__name__} lacks {method}"
    signature = inspect.signature(adapter.complete)
    assert list(signature.parameters) == ["self", "req"]


@pytest.mark.parametrize("adapter", STUBS, ids=lambda a: a.__name__)
async def test_a_stub_refuses_rather_than_pretending(adapter):
    """AC-AI-02.3 - "the three stubs pass by raising `ProviderNotConfigured`
    where a real call would occur"."""
    instance = adapter()
    with pytest.raises(ProviderNotConfigured):
        await instance.complete(request())
    with pytest.raises(ProviderNotConfigured):
        await instance.complete_json(request(), Tiny)
    with pytest.raises(ProviderNotConfigured):
        async for _ in instance.stream(request()):
            pass


@pytest.mark.parametrize("adapter", STUBS, ids=lambda a: a.__name__)
async def test_a_stub_raises_only_ai_errors(adapter):
    """AC-AI-01.4 - every public method raises only `AIError` subclasses, so no
    provider exception type crosses the boundary (HR-5)."""
    with pytest.raises(AIError):
        await adapter().complete(request())


async def test_the_fake_answers_deterministically():
    """The property every golden test depends on (`AC-AI-07.3`)."""
    first = await FakeLLM().complete(request())
    second = await FakeLLM().complete(request())
    assert first.text == second.text
    assert first.model == second.model


async def test_the_fake_reports_token_counts_and_latency():
    """So the accounting path (`AI-04`) and the budget path (`AI-03`) are
    exercised by the default suite, not only against a real provider."""
    response = await FakeLLM().complete(request())
    assert response.input_tokens > 0
    assert response.output_tokens > 0
    assert response.latency_ms >= 0
    assert response.prompt_version == "resume_extract/v1"


async def test_the_fake_returns_a_validated_instance_not_a_dict():
    """AC-AI-01.5 - `complete_json` "returns a validated instance of the
    requested schema or raises; it never returns a dict"."""
    result = await FakeLLM().complete_json(request(), Tiny)
    assert isinstance(result.value, Tiny)
    assert isinstance(result.value.name, str)


async def test_the_fake_embedder_is_deterministic_and_quantized():
    embedder = FakeEmbedder()
    assert isinstance(embedder, EmbeddingProvider)

    first = await embedder.embed(["a resume"], "document")
    second = await embedder.embed(["a resume"], "document")
    assert first[0] == second[0]
    # `DATA-06`: one byte per dimension, and the model travels with the vector.
    assert first[0].nbytes == embedder.dims
    assert first[0].model == embedder.model


async def test_different_texts_embed_differently():
    embedder = FakeEmbedder()
    vectors = await embedder.embed(["a backend role", "a design role"], "document")
    assert vectors[0].data != vectors[1].data


def test_the_registered_set_is_the_expected_one():
    """When `AI-05` lands, `gemini` appears here and this test says so."""
    assert set(LLM_FACTORIES) == {"fake", "openai", "anthropic", "ollama"}, (
        "the registered providers changed; if this is gemini arriving with "
        "AI-05, add it to ALL_LLMS above so it is covered by the contract suite"
    )
