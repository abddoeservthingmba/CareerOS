"""The deterministic provider - `AI-02`.

`05-ai-layer.md` §2: "`fake.py` (deterministic, used by every test and by local
development without a key)."

Two properties make it useful rather than merely present:

* **Deterministic.** The same request yields the same response, byte for byte,
  because the output is derived from a hash of the request. A golden test that
  passes today passes tomorrow (`AC-AI-07.3`), and `make up` works with no
  credential at all.
* **Honest about cost.** It reports token counts and a latency, so the
  accounting path (`AI-04`) and the budget path (`AI-03`) are exercised by the
  default test suite rather than only against a real provider.

It also carries the failure modes on purpose - `fail_with`, `invalid_json_once`
- because `AC-AI-01.4` and `AC-AI-05.6` need a way to force each one without
reaching a network.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from app.ai.base import (
    AIError,
    JsonResult,
    LLMRequest,
    LLMResponse,
    StructuredOutputInvalid,
)
from app.ai.untrusted import render
from app.shared.embedding import Vector, quantize

FAKE_MODEL = "fake-1"
FAKE_EMBEDDING_MODEL = "fake-embed-1"
FAKE_DIMS = 768


def _digest(req: LLMRequest) -> str:
    rendered = render(req.untrusted, nonce="fixed-for-hashing").text
    payload = " ".join(
        [
            req.feature.value,
            req.system,
            rendered,
            req.prompt_version,
            *(m.content for m in req.messages),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class FakeLLM:
    """A provider that answers from a hash instead of a network."""

    name = "fake"

    def __init__(
        self,
        *,
        model: str = FAKE_MODEL,
        responses: dict[str, str] | None = None,
        fail_with: AIError | None = None,
        invalid_json_once: bool = False,
    ) -> None:
        self.model = model
        # Canned answers by feature, for golden tests that need a specific one.
        self._responses = dict(responses or {})
        self._fail_with = fail_with
        self._invalid_json_once = invalid_json_once
        self.calls: list[LLMRequest] = []

    def _guard(self, req: LLMRequest) -> None:
        self.calls.append(req)
        if self._fail_with is not None:
            raise self._fail_with

    def _respond(self, req: LLMRequest, text: str) -> LLMResponse:
        return LLMResponse(
            text=text,
            model=self.model,
            prompt_version=req.prompt_version,
            # Deterministic and roughly proportional, so cost accounting has
            # something meaningful to add up.
            input_tokens=max(1, (len(req.system) + sum(len(m.content) for m in req.messages)) // 4),
            output_tokens=max(1, len(text) // 4),
            cached=False,
            latency_ms=12,
        )

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self._guard(req)
        text = self._responses.get(req.feature.value, f"fake:{_digest(req)[:16]}")
        return self._respond(req, text)

    async def complete_json[M: BaseModel](self, req: LLMRequest, schema: type[M]) -> JsonResult[M]:
        self._guard(req)

        repaired = False
        if self._invalid_json_once:
            # `AC-AI-05.6`: exactly one repair retry, then StructuredOutputInvalid.
            self._invalid_json_once = False
            repaired = True

        canned = self._responses.get(req.feature.value)
        raw = canned if canned is not None else json.dumps(_skeleton(schema, _digest(req)))
        try:
            value = schema.model_validate_json(raw)
        except ValidationError as exc:
            raise StructuredOutputInvalid(
                f"fake provider could not satisfy {schema.__name__}: {exc.error_count()} errors"
            ) from exc
        return JsonResult(
            value=value, raw_text=raw, repaired=repaired, response=self._respond(req, raw)
        )

    async def stream(self, req: LLMRequest) -> AsyncIterator[str]:
        self._guard(req)
        text = self._responses.get(req.feature.value, f"fake:{_digest(req)[:16]}")
        for chunk in text.split(" "):
            yield chunk + " "


class FakeEmbedder:
    """Deterministic embeddings, quantized like the real ones (`DATA-06`)."""

    name = "fake"
    model = FAKE_EMBEDDING_MODEL
    dims = FAKE_DIMS

    def __init__(self, *, model: str = FAKE_EMBEDDING_MODEL, dims: int = FAKE_DIMS) -> None:
        self.model = model
        self.dims = dims
        self.calls: list[tuple[tuple[str, ...], str]] = []

    async def embed(self, texts: Sequence[str], task: Literal["document", "query"]) -> list[Vector]:
        self.calls.append((tuple(texts), task))
        return [quantize(self._vector(text), self.model) for text in texts]

    def _vector(self, text: str) -> list[float]:
        """A stable pseudo-embedding: similar texts share leading bytes, so
        cosine similarity is meaningful enough for a fixture to assert on."""
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        stream = bytearray()
        counter = 0
        while len(stream) < self.dims:
            stream += hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            counter += 1
        return [(b - 127.5) / 127.5 for b in stream[: self.dims]]


def _skeleton(schema: type[BaseModel], digest: str) -> dict[str, Any]:
    """The smallest instance of `schema` that validates.

    Built from the model's own JSON schema so a feature's structured call works
    against the fake without the fake knowing that feature's shape.
    """
    spec = schema.model_json_schema()
    return _build_object(spec, spec.get("$defs", {}), digest)


def _build_object(spec: dict[str, Any], defs: dict[str, Any], digest: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, field in spec.get("properties", {}).items():
        if name in spec.get("required", []):
            out[name] = _build_value(field, defs, digest)
    return out


def _build_value(field: dict[str, Any], defs: dict[str, Any], digest: str) -> Any:
    if "$ref" in field:
        target = field["$ref"].rsplit("/", 1)[-1]
        return _build_object(defs.get(target, {}), defs, digest)
    if "anyOf" in field:
        return _build_value(field["anyOf"][0], defs, digest)
    if "enum" in field:
        return field["enum"][0]
    kind = field.get("type")
    if kind == "string":
        return f"fake-{digest[:8]}"
    if kind == "integer":
        return 0
    if kind == "number":
        return 0.0
    if kind == "boolean":
        return False
    if kind == "array":
        return []
    if kind == "object":
        return _build_object(field, defs, digest)
    return None
