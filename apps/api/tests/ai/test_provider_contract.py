"""T-AI-02.3 - every adapter satisfies the same contract.

`AC-AI-02.3`, as amended by ADR-011: "All five adapters pass the same contract
suite; the **two** stubs pass by raising `ProviderNotConfigured` where a real
call would occur."

`05-ai-layer.md` §2 says why the stubs are in the suite at all: "so that the
protocol cannot drift into being Gemini-shaped". That argument got materially
stronger with ADR-011. Three stubs sharing one base class agreed with each other
by construction, which is weak evidence of anything; `gemini` and `ollama` were
written separately against the protocol, and two implementations that actually
*answer* are what makes "provider-neutral" a claim rather than a hope. A
protocol only one implementation can satisfy looks fine until the second one
arrives.

Each adapter is built by a factory rather than by calling the class, because two
of them legitimately need construction arguments - model ids, which are
configuration (`AC-AI-02.2`). A suite that could only exercise zero-argument
adapters would have quietly excluded both real ones.
"""

from __future__ import annotations

import inspect
from typing import Any

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
from app.ai.gemini import GeminiProvider
from app.ai.ollama import OllamaProvider
from app.ai.registry import LLM_FACTORIES
from app.ai.stubs import STUBS, AnthropicProvider, OpenAIProvider

#: `AC-AI-02.2` - a model id is configuration. These are the shapes each
#: provider uses, supplied so the adapter can be constructed at all. No call is
#: made against them.
GEMINI_MODELS: dict[str, Any] = {
    "model_fast": "gemini-3.5-flash-lite",
    "model_quality": "gemini-3.8-flash",
    "embedding_model": "gemini-embedding-001",
}
OLLAMA_MODELS: dict[str, Any] = {
    "model_fast": "llama3.2:3b",
    "model_quality": "qwen2.5:7b",
    "embedding_model": "nomic-embed-text",
}

#: The two that raise. ADR-011 moved `ollama` out of this tuple.
STUB_FACTORIES = (
    ("openai", OpenAIProvider),
    ("anthropic", AnthropicProvider),
)

#: All five, as `(name, factory)`. The two real adapters get no transport here,
#: so a call against them raises `ProviderNotConfigured` for a *different*
#: reason than a stub does - which the tests below distinguish rather than
#: conflate.
ALL_FACTORIES = (
    ("fake", FakeLLM),
    ("gemini", lambda: GeminiProvider("a-test-key", **GEMINI_MODELS)),
    ("ollama", lambda: OllamaProvider(**OLLAMA_MODELS)),
    *STUB_FACTORIES,
)


class Tiny(BaseModel):
    name: str


def request() -> LLMRequest:
    return LLMRequest(
        feature=Feature.RESUME_EXTRACT,
        system="Extract.",
        prompt_version="resume_extract/v1",
    )


# -- the protocol, over all five ---------------------------------------------


@pytest.mark.parametrize(("name", "factory"), ALL_FACTORIES, ids=[n for n, _ in ALL_FACTORIES])
def test_every_adapter_satisfies_the_llm_protocol(name, factory):
    """AC-AI-02.3 - structurally, before any call is made."""
    instance = factory()

    assert isinstance(instance, LLMProvider)
    assert instance.name == name


@pytest.mark.parametrize(("name", "factory"), ALL_FACTORIES, ids=[n for n, _ in ALL_FACTORIES])
def test_every_adapter_has_the_same_complete_signature(name, factory):
    """The drift this guards against: an adapter growing a Gemini-shaped
    parameter that no other provider could satisfy.

    Load-bearing now rather than nearly free. The stubs inherit one base class
    and agreed by construction; these two were written separately, and this is
    what catches the first to grow a parameter the other cannot supply.
    """
    adapter = type(factory())

    for method in ("complete", "complete_json", "stream"):
        assert hasattr(adapter, method), f"{adapter.__name__} lacks {method}"
    assert list(inspect.signature(adapter.complete).parameters) == ["self", "req"]


@pytest.mark.parametrize(("name", "factory"), ALL_FACTORIES, ids=[n for n, _ in ALL_FACTORIES])
def test_every_adapter_has_the_same_complete_json_signature(name, factory):
    """The same drift from the other side: a request and a schema, and nothing
    a single provider happens to support."""
    adapter = type(factory())

    assert list(inspect.signature(adapter.complete_json).parameters) == ["self", "req", "schema"]


@pytest.mark.parametrize(("name", "factory"), ALL_FACTORIES, ids=[n for n, _ in ALL_FACTORIES])
async def test_no_adapter_lets_a_foreign_exception_escape(name, factory):
    """AC-AI-01.4 - every public method raises only `AIError` subclasses, so no
    provider exception type crosses the boundary (HR-5).

    Extended from the stubs to all five. `fake` succeeds; the other four raise,
    for two different reasons - a stub because it is unconfigured by design, and
    the real two because no HTTP transport was injected. Both are `AIError`,
    which is the only thing a caller should ever have to handle.
    """
    instance = factory()
    try:
        await instance.complete(request())
    except AIError:
        pass
    except Exception as leaked:  # noqa: BLE001 - catching broadly *is* the check
        raise AssertionError(
            f"{name} raised {type(leaked).__name__}, which is not an AIError; a "
            "provider's own exception type must not cross the boundary"
        ) from leaked


@pytest.mark.parametrize(("name", "factory"), ALL_FACTORIES, ids=[n for n, _ in ALL_FACTORIES])
def test_no_adapter_streams_tokens_in_r1(name, factory):
    """`FOUND-11` streams stage progress, not model output, and no R1 feature
    streams tokens. `fake` is the exception - it exists to be driven by tests -
    so this asserts the two real adapters refuse rather than silently
    buffering, which is what would hide the gap from whoever adds the first
    streaming feature."""
    if name in ("fake", "openai", "anthropic"):
        return
    with pytest.raises(ProviderNotConfigured, match="stream"):
        factory().stream(request())


# -- the two stubs -----------------------------------------------------------


@pytest.mark.parametrize(("name", "factory"), STUB_FACTORIES, ids=[n for n, _ in STUB_FACTORIES])
async def test_a_stub_refuses_rather_than_pretending(name, factory):
    """AC-AI-02.3 - "the two stubs pass by raising `ProviderNotConfigured` where
    a real call would occur"."""
    instance = factory()

    with pytest.raises(ProviderNotConfigured):
        await instance.complete(request())
    with pytest.raises(ProviderNotConfigured):
        await instance.complete_json(request(), Tiny)
    with pytest.raises(ProviderNotConfigured):
        async for _ in instance.stream(request()):
            pass


def test_there_are_exactly_two_stubs():
    """`AC-AI-02.3`, as ADR-011 amended it.

    A third stub reappearing would mean a real adapter had been demoted, which
    is a decision recorded in an ADR - not a refactor.
    """
    assert len(STUBS) == 2
    assert {stub.name for stub in STUBS} == {"openai", "anthropic"}


def test_the_two_real_adapters_are_not_stubs():
    """The point of ADR-011.

    Both still raise `ProviderNotConfigured` in this suite because no transport
    is injected, so the distinction cannot be asserted at the call - it is
    asserted by name instead. By name rather than by identity because mypy can
    prove the identity check statically, which makes it a tautology rather than
    a test.
    """
    stub_names = {stub.name for stub in STUBS}

    assert GeminiProvider.name not in stub_names
    assert OllamaProvider.name not in stub_names


# -- the fake, which every golden test depends on ----------------------------


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


# -- the registry and the suite agree ----------------------------------------


def test_the_registered_set_is_the_expected_one():
    """All five, and the suite covers all five.

    The two sets are compared rather than each written out, so a sixth provider
    registered without being added here fails rather than going untested.
    """
    assert set(LLM_FACTORIES) == {"fake", "gemini", "ollama", "openai", "anthropic"}
    assert {name for name, _ in ALL_FACTORIES} == set(LLM_FACTORIES), (
        "a registered provider is missing from the contract suite"
    )


def test_both_real_adapters_are_embedding_providers_too():
    """`AI-02` resolves one `EmbeddingProvider` from `AI_EMBEDDING_PROVIDER`,
    and both real adapters are candidates for it - so both have to satisfy the
    second protocol as well as the first."""
    from app.ai.registry import EMBEDDER_FACTORIES

    assert {"gemini", "ollama"} <= set(EMBEDDER_FACTORIES)
    assert isinstance(GeminiProvider("k", **GEMINI_MODELS), EmbeddingProvider)
    assert isinstance(OllamaProvider(**OLLAMA_MODELS), EmbeddingProvider)
