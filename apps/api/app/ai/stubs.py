"""Adapters that exist to prove the protocol - `AI-02`.

`05-ai-layer.md` §2, as amended by ADR-011: "`openai.py` and `anthropic.py` are R1
**stubs** that exist only to prove the contract: each is a class that satisfies
the protocol, raises `ProviderNotConfigured` when called, and is included in the
adapter contract test suite so that the protocol cannot drift into being
Gemini-shaped."

They live in one module rather than three files because three near-identical
files invite one of them to acquire a real implementation quietly. There is
nothing provider-specific here to separate - by design, since a stub that knew
anything about its provider would need that provider's SDK, and HR-5 forbids
that outside `ai/<provider>.py`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Literal

from pydantic import BaseModel

from app.ai.base import (
    JsonResult,
    LLMRequest,
    LLMResponse,
    ProviderNotConfigured,
)
from app.shared.embedding import Vector


class _UnconfiguredProvider:
    """Satisfies `LLMProvider` and `EmbeddingProvider`, and refuses to work."""

    name = "unconfigured"

    def _refuse(self) -> ProviderNotConfigured:
        return ProviderNotConfigured(
            f"the {self.name} adapter is an R1 stub; it proves the protocol and "
            "has no implementation. Configure `gemini`, or `fake` for local work."
        )

    async def complete(self, req: LLMRequest) -> LLMResponse:
        raise self._refuse()

    async def complete_json[M: BaseModel](self, req: LLMRequest, schema: type[M]) -> JsonResult[M]:
        raise self._refuse()

    async def stream(self, req: LLMRequest) -> AsyncIterator[str]:
        raise self._refuse()
        yield ""  # pragma: no cover - unreachable, and required to make this a generator

    async def embed(self, texts: Sequence[str], task: Literal["document", "query"]) -> list[Vector]:
        raise self._refuse()


class OpenAIProvider(_UnconfiguredProvider):
    name = "openai"


class AnthropicProvider(_UnconfiguredProvider):
    name = "anthropic"


#: ADR-011 promoted `ollama` out of this module: it is a real adapter in
#: `app/ai/ollama.py`, serving local development so that prompt iteration can
#: run against a real model with no text leaving the machine. `AC-AI-02.3` now
#: reads "the two stubs".
STUBS = (OpenAIProvider, AnthropicProvider)
