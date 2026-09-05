"""The AI contract - `AI-01`.

`05-ai-layer.md` §1: "Feature modules describe what they want from a model and
never learn which model answered."

`AC-AI-01.1` is the constraint that shapes this file: it "imports nothing
outside the standard library, `pydantic`, and `app.shared` - in particular no
HTTP client and no provider SDK". That is what makes HR-5 structural rather
than a rule people remember: a provider type cannot cross a boundary it cannot
reach.

Two further properties are enforced by the *types* rather than by discipline:

* `LLMRequest` has no field capable of carrying bytes, a file handle or a
  storage URL (`AC-RES-05.1`). HR-8 - "resume and document file bytes never
  leave our infrastructure" - is therefore not a code review item; there is
  nowhere to put a file.
* Untrusted content travels in `untrusted`, a mapping the AI layer alone
  renders (`AI-06`). A feature module that concatenates a job description into
  `system` is a static-check failure, not a silent injection surface.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from app.shared.embedding import Vector


class Feature(StrEnum):
    """Every AI-spending operation in the product.

    `05-ai-layer.md` §1: "`feature` is not optional and not free text ...
    Budgets, pricing, provider selection, and the admin dashboard all key on
    it." Ten members, matching `ai-budget.yaml` exactly (`AC-AI-03.12`).
    """

    RESUME_EXTRACT = "resume_extract"
    RESUME_QUALITY = "resume_quality"
    JOB_ENRICH = "job_enrich"
    MATCH_RATIONALE = "match_rationale"
    PACK_GENERATE = "pack_generate"
    FOLLOWUP_DRAFT = "followup_draft"
    ANSWER_SUGGEST = "answer_suggest"
    EMBED_PROFILE = "embed_profile"
    EMBED_JOB = "embed_job"
    EMBED_QUESTION = "embed_question"


class Tier(StrEnum):
    """`05-ai-layer.md` §2: "Each feature declares which **tier** it wants
    (`fast` or `quality`), not which model"."""

    FAST = "fast"
    QUALITY = "quality"


@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """What a feature asks for. Note what it cannot express.

    There is no `file`, no `bytes`, no `url` and no `attachment` field, and
    `AC-RES-05.1` asserts by introspection that none is ever added. That absence
    is the enforcement of HR-8.
    """

    feature: Feature
    system: str
    messages: tuple[Message, ...] = ()
    # §6: untrusted content is passed here as name -> text and is rendered into
    # the prompt by the AI layer alone, wrapped in a nonce-delimited block.
    untrusted: Mapping[str, str] = field(default_factory=dict)
    temperature: float = 0.2
    max_output_tokens: int = 1024
    user_id: str | None = None
    cache_key: str | None = None
    prompt_version: str = ""

    def __post_init__(self) -> None:
        # `AC-AI-01.2`: constructing without a feature, or with one outside the
        # enum, raises.
        if not isinstance(self.feature, Feature):
            raise ValueError(
                f"feature must be a Feature member, got {self.feature!r}; "
                "budgets, pricing and the admin dashboard all key on it"
            )
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError(f"temperature out of range: {self.temperature}")
        if self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    cached: bool
    latency_ms: int


@dataclass(frozen=True, slots=True)
class JsonResult[M: BaseModel]:
    value: M
    raw_text: str
    repaired: bool
    response: LLMResponse


# -- the exception hierarchy ------------------------------------------------
# `AC-AI-01.4`: "Every public method of every adapter raises only `AIError`
# subclasses." A provider's own exception is caught in the adapter and
# re-raised, so no SDK type crosses the boundary (HR-5).


class AIError(Exception):
    """The base of everything the AI layer raises."""


class ProviderNotConfigured(AIError):
    """The adapter exists to prove the protocol but has no credential.

    `05-ai-layer.md` §2: `openai.py`, `anthropic.py` and `ollama.py` are R1
    stubs "included in the adapter contract test suite so that the protocol
    cannot drift into being Gemini-shaped".
    """


class ProviderError(AIError):
    """The provider answered with a failure.

    Carries a status and a code, never the provider's message body, which can
    contain echoed prompt content (`AC-FOUND-14.5`).
    """

    def __init__(self, provider: str, status: int, code: str) -> None:
        super().__init__(f"{provider} returned {status} ({code})")
        self.provider = provider
        self.status = status
        self.code = code


class ProviderTimeout(AIError):
    """The provider did not answer inside the request's budget."""


class StructuredOutputInvalid(AIError):
    """`AC-AI-05.6`: invalid JSON survived the one repair retry."""


class AIBudgetExceeded(AIError):
    """`AI-03`: a cap would be crossed. Raised before the provider is contacted.

    Every feature handles this by degrading per `ai-budget.yaml`; no feature
    propagates it to the user as an unhandled error.
    """

    def __init__(self, feature: Feature, deny_reason: str, retry_after_seconds: int) -> None:
        super().__init__(f"{feature} denied by the {deny_reason} cap")
        self.feature = feature
        self.deny_reason = deny_reason
        self.retry_after_seconds = retry_after_seconds


# -- the protocols ----------------------------------------------------------


# `runtime_checkable` so the adapter contract suite (`AC-AI-02.3`) can assert
# conformance structurally. It checks method presence only; the signatures are
# asserted separately, which is what keeps the protocol from drifting into
# being Gemini-shaped.
@runtime_checkable
class LLMProvider(Protocol):
    name: str

    async def complete(self, req: LLMRequest) -> LLMResponse: ...

    async def complete_json[M: BaseModel](
        self, req: LLMRequest, schema: type[M]
    ) -> JsonResult[M]: ...

    def stream(self, req: LLMRequest) -> AsyncIterator[str]: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    name: str
    model: str
    dims: int

    async def embed(
        self, texts: Sequence[str], task: Literal["document", "query"]
    ) -> list[Vector]: ...
