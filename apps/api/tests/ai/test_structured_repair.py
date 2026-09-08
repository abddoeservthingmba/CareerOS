"""T-AI-05.6 - one repair, then a refusal.

`AC-AI-05.6`: "Invalid JSON from the provider triggers exactly one repair retry;
a second failure raises `StructuredOutputInvalid` and writes an `ai_usage` row
with `outcome: invalid_json`."

`05-ai-layer.md` §5.2: "pass the JSON schema via the provider's structured-output
facility, then **still** validate with Pydantic, then on failure retry exactly
once with a repair prompt that includes the validation error and the offending
text."

Two words carry the requirement.

**"Still."** A provider's structured-output mode constrains the *shape* and
cannot know a business rule: that a confidence is 0-1, that an employment end
date is not in the future, that a skill is one of ours. Trusting the mode is how
a model's plausible invention becomes a stored fact - and stored facts about
someone's employment history are the thing this product is for.

**"Exactly once."** Not a loop with a limit. A model that could not produce the
schema, when told precisely what was wrong with its last attempt, will not
produce it on the fifth try either - and each attempt is a user's budget and a
user's wait. One retry is the point at which the marginal attempt stops being
worth its cost.

Both adapters are tested here. Ollama's format adherence is *worse* than a
hosted model's, not better, so "still validate" matters more there rather than
less - and if the two adapters disagreed about how many repairs happen, a
provider switch would change how often a feature fails.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel, Field

from app.ai.base import (
    Feature,
    LLMRequest,
    ProviderError,
    ProviderNotConfigured,
    StructuredOutputInvalid,
)
from app.ai.gemini import MAX_REPAIR_ATTEMPTS, GeminiProvider
from app.ai.ollama import OllamaProvider

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


class Extraction(BaseModel):
    """A schema with a rule the provider's format mode cannot know."""

    employer: str
    confidence: float = Field(ge=0.0, le=1.0)


def request() -> LLMRequest:
    return LLMRequest(
        feature=Feature.RESUME_EXTRACT,
        system="Extract the employer.",
        untrusted={"resume_text": "Senior engineer at Acme, 2019-2024."},
        prompt_version="resume_extract/v1",
    )


class Reply:
    """One canned HTTP response."""

    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def json(self) -> dict[str, Any]:
        return self._payload


class ScriptedTransport:
    """Returns a prepared body per call, and records what it was sent.

    A script rather than a mock, because the assertions here are about *how
    many* calls happen and *what the second one says* - and a mock's assertion
    API would let a test pass while the repair prompt was empty.
    """

    def __init__(self, texts: list[str], *, provider: str = "gemini") -> None:
        self._texts = list(texts)
        self._provider = provider
        self.calls: list[dict[str, Any]] = []

    async def post(self, url: str, *, json: dict[str, Any], **_: Any) -> Reply:
        self.calls.append(json)
        text = self._texts[min(len(self.calls) - 1, len(self._texts) - 1)]
        if self._provider == "gemini":
            return Reply(
                {
                    "candidates": [{"content": {"parts": [{"text": text}]}}],
                    "usageMetadata": {"promptTokenCount": 800, "candidatesTokenCount": 40},
                }
            )
        return Reply(
            {
                "message": {"content": text},
                "prompt_eval_count": 800,
                "eval_count": 40,
            }
        )


VALID = json.dumps({"employer": "Acme", "confidence": 0.9})
#: Well-formed JSON, wrong *value*. This is the case a format mode cannot catch,
#: and the reason §5.2 says "still validate".
OUT_OF_RANGE = json.dumps({"employer": "Acme", "confidence": 1.7})
#: Not JSON at all - the classic preamble a model adds when it is being helpful.
NOT_JSON = "Here is the extraction you asked for: {employer: Acme}"


def gemini(texts: list[str]) -> tuple[GeminiProvider, ScriptedTransport]:
    transport = ScriptedTransport(texts, provider="gemini")
    return GeminiProvider("k", transport=transport, **GEMINI_MODELS), transport


def ollama(texts: list[str]) -> tuple[OllamaProvider, ScriptedTransport]:
    transport = ScriptedTransport(texts, provider="ollama")
    return OllamaProvider(transport=transport, **OLLAMA_MODELS), transport


ADAPTERS = (("gemini", gemini), ("ollama", ollama))
IDS = [name for name, _ in ADAPTERS]


# -- the happy path ----------------------------------------------------------


@pytest.mark.parametrize(("name", "build"), ADAPTERS, ids=IDS)
async def test_valid_output_is_one_call(name, build):
    """The control. An implementation that always repaired would double every
    bill and satisfy every assertion below."""
    provider, transport = build([VALID])

    result = await provider.complete_json(request(), Extraction)

    assert len(transport.calls) == 1
    assert result.repaired is False
    assert result.value.employer == "Acme"
    assert result.value.confidence == 0.9


@pytest.mark.parametrize(("name", "build"), ADAPTERS, ids=IDS)
async def test_the_result_is_a_validated_instance_not_a_dict(name, build):
    """`AC-AI-01.5`. A dict would put the validation burden on ten call sites,
    and one of them would skip it."""
    provider, _ = build([VALID])

    result = await provider.complete_json(request(), Extraction)

    assert isinstance(result.value, Extraction)


# -- one repair --------------------------------------------------------------


@pytest.mark.parametrize(("name", "build"), ADAPTERS, ids=IDS)
async def test_invalid_output_triggers_exactly_one_repair(name, build):
    """AC-AI-05.6, first clause."""
    provider, transport = build([NOT_JSON, VALID])

    result = await provider.complete_json(request(), Extraction)

    assert len(transport.calls) == 2
    assert result.repaired is True
    assert result.value.employer == "Acme"


@pytest.mark.parametrize(("name", "build"), ADAPTERS, ids=IDS)
async def test_a_schema_violation_that_parses_still_triggers_a_repair(name, build):
    """The "**still** validate" case, and the one a format mode cannot catch.

    `{"confidence": 1.7}` is valid JSON of the right shape. Only Pydantic knows
    the field is bounded, and without this check a confidence of 1.7 would be
    stored and later rendered as a percentage.
    """
    provider, transport = build([OUT_OF_RANGE, VALID])

    result = await provider.complete_json(request(), Extraction)

    assert len(transport.calls) == 2
    assert result.repaired is True
    assert result.value.confidence == 0.9


@pytest.mark.parametrize(("name", "build"), ADAPTERS, ids=IDS)
async def test_the_repair_prompt_carries_the_validation_error(name, build):
    """§5.2: "a repair prompt that includes the validation error and the
    offending text".

    Without the error the model is told only "that was wrong", which is the
    least useful correction available.
    """
    provider, transport = build([OUT_OF_RANGE, VALID])

    await provider.complete_json(request(), Extraction)

    second = json.dumps(transport.calls[1])
    assert "confidence" in second
    assert "less than or equal to 1" in second


@pytest.mark.parametrize(("name", "build"), ADAPTERS, ids=IDS)
async def test_the_repair_prompt_carries_the_offending_text(name, build):
    provider, transport = build([NOT_JSON, VALID])

    await provider.complete_json(request(), Extraction)

    assert NOT_JSON in json.dumps(transport.calls[1])


@pytest.mark.parametrize(("name", "build"), ADAPTERS, ids=IDS)
async def test_the_offending_text_goes_in_as_untrusted_content(name, build):
    """HR-11: model output never steers the program.

    The failed response is wrapped in the same nonce-delimited block a job
    description gets. An injection that survived the first call must not get a
    second, cleaner run at the system prompt - which is exactly what pasting it
    into `system` would give it.
    """
    provider, transport = build([NOT_JSON, VALID])

    await provider.complete_json(request(), Extraction)

    second = json.dumps(transport.calls[1])
    assert "previous_invalid_response" in second
    # `ai/untrusted.py` renders a nonce-delimited block; its marker is what
    # proves the text went through that path rather than into the instructions.
    assert "UNTRUSTED" in second.upper()


# -- and then it stops -------------------------------------------------------


@pytest.mark.parametrize(("name", "build"), ADAPTERS, ids=IDS)
async def test_a_second_failure_raises_rather_than_retrying(name, build):
    """AC-AI-05.6, second clause. Exactly two calls, then a refusal."""
    provider, transport = build([NOT_JSON, NOT_JSON, VALID])

    with pytest.raises(StructuredOutputInvalid):
        await provider.complete_json(request(), Extraction)

    assert len(transport.calls) == 2, "a third attempt was made"


@pytest.mark.parametrize(("name", "build"), ADAPTERS, ids=IDS)
async def test_the_refusal_names_the_schema_and_the_error(name, build):
    """The caller degrades per §3.2 and the operator debugs from the log. Both
    need to know which schema and what was wrong with the output."""
    provider, _ = build([NOT_JSON, OUT_OF_RANGE])

    with pytest.raises(StructuredOutputInvalid) as caught:
        await provider.complete_json(request(), Extraction)

    message = str(caught.value)
    assert "Extraction" in message
    assert "confidence" in message


def test_the_repair_budget_is_one_for_both_adapters():
    """If the two disagreed, switching provider would change how often a feature
    fails - which is a product change disguised as a configuration change."""
    from app.ai.ollama import MAX_REPAIR_ATTEMPTS as OLLAMA_REPAIRS

    assert MAX_REPAIR_ATTEMPTS == OLLAMA_REPAIRS == 1


# -- the request the adapter actually sends ----------------------------------


async def test_gemini_asks_for_the_schema_in_the_provider_facility():
    """§5.2's first step. Validating without asking would waste the provider's
    constrained decoding and make repairs far more common."""
    provider, transport = gemini([VALID])

    await provider.complete_json(request(), Extraction)

    config = transport.calls[0]["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseJsonSchema"]["properties"]["confidence"]


async def test_ollama_asks_for_the_schema_in_its_format_field():
    """The same step, through Ollama's own name for it."""
    provider, transport = ollama([VALID])

    await provider.complete_json(request(), Extraction)

    assert transport.calls[0]["format"]["properties"]["employer"]


@pytest.mark.parametrize(("name", "build"), ADAPTERS, ids=IDS)
async def test_the_untrusted_resume_never_reaches_the_instructions(name, build):
    """§6, on the first call as well as the repair. A feature hands untrusted
    text to the AI layer; only the AI layer renders it, and only inside the
    block."""
    provider, transport = build([VALID])

    await provider.complete_json(request(), Extraction)

    sent = json.dumps(transport.calls[0])
    assert "Senior engineer at Acme" in sent, "the resume did not reach the model at all"
    assert "UNTRUSTED" in sent.upper()


@pytest.mark.parametrize(("name", "build"), ADAPTERS, ids=IDS)
async def test_the_response_carries_the_providers_token_counts(name, build):
    """`AC-AI-03.3`. The repair's tokens are the provider's too, and the row
    written for a repaired call has to reflect what was actually charged."""
    provider, _ = build([NOT_JSON, VALID])

    result = await provider.complete_json(request(), Extraction)

    assert result.response.input_tokens == 800
    assert result.response.output_tokens == 40


# -- errors that are not schema failures -------------------------------------


@pytest.mark.parametrize(("name", "build"), ADAPTERS, ids=IDS)
async def test_a_provider_error_is_not_repaired(name, build):
    """A 500 is not a schema problem, and retrying it as one would send the same
    prompt to a provider that is down - and bill for it."""

    class Failing(ScriptedTransport):
        async def post(self, url: str, *, json: dict[str, Any], **_: Any) -> Reply:
            self.calls.append(json)
            return Reply({}, status=500)

    provider, _ = build([VALID])
    failing = Failing([VALID], provider=name)
    provider._transport = failing  # noqa: SLF001

    with pytest.raises(ProviderError):
        await provider.complete_json(request(), Extraction)

    assert len(failing.calls) == 1


@pytest.mark.parametrize(("name", "build"), ADAPTERS, ids=IDS)
async def test_no_transport_is_a_configuration_error_not_a_schema_error(name, build):
    """An adapter with no client has not produced bad output; it has not been
    wired. Reporting that as `StructuredOutputInvalid` would send whoever is
    debugging it to the prompt."""
    provider, _ = build([VALID])
    provider._transport = None  # noqa: SLF001

    with pytest.raises(ProviderNotConfigured):
        await provider.complete_json(request(), Extraction)
