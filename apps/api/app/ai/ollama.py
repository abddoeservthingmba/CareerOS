"""The Ollama adapter - `AI-02`, promoted from a stub by ADR-011.

`05-ai-layer.md` §2, as amended: "`ollama.py` (real, the local-development
provider - **amended by ADR-011**, so that prompt iteration and the
resume-extraction golden set can run against a real model with no text leaving
the machine)."

**Why this exists at all.** The specification's D5 decision (§5.4) is a choice
between a paid Gemini tier whose terms say prompts are not used for training and
a free tier whose terms say they are. The product sends resume text. During
development the fixtures are real résumés - `AC-AI-07.5` requires ten of them,
"the developer's own or explicitly licensed" - and sending those to a provider
that may train on them is a choice worth not having to make in order to iterate
on a prompt.

The fake provider avoids it entirely and is sufficient for every acceptance
criterion in `AI-03` through `AI-07`. But it is deterministic by construction:
it cannot answer "does this prompt extract employers correctly", which is the
question the precision gate exists to ask. Ollama sits in that gap.

**What is different from Gemini, and what is deliberately the same.**

Different: there is no credential. Nothing to inject, nothing to leak, no
ambient-credential confusion to guard against - HR-6 has nothing to bite on
here, because there is no Google credential in the picture at all.

The same: it is behind the same two protocols, passes the same contract suite
(`AC-AI-02.3`), raises only `AIError` subclasses (`AC-AI-01.4`), renders
untrusted content through the same nonce-delimited block (§6), reports the
provider's own token counts where it has them, and validates structured output
with Pydantic after asking for JSON - because a local model's format adherence
is *worse* than a hosted one's, not better, so "still validate" matters more
here rather than less.

**It refuses to serve production.** A local model reachable from a production
container is almost always a leftover configuration rather than an intention,
and the failure mode is silent: resumes get extracted by a 3B model and nobody
notices until the precision numbers are read. So `APP_ENV=prod` requires the
base URL to be set explicitly, and even then this is not the R1 production
default - Gemini is, and ADR-011 does not reopen that.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ValidationError

from app.ai.base import (
    Feature,
    JsonResult,
    LLMRequest,
    LLMResponse,
    ProviderError,
    ProviderNotConfigured,
    StructuredOutputInvalid,
    Tier,
)
from app.ai.untrusted import render as render_untrusted
from app.shared.embedding import Vector, quantize

logger = logging.getLogger("app.ai.ollama")

#: Where a local Ollama listens. Not a secret and not a credential - which is
#: the entire privacy argument for this adapter.
DEFAULT_BASE_URL = "http://127.0.0.1:11434"

#: Local only. A remote Ollama over plain HTTP would be resume text on the wire
#: in clear text, which is worse than any hosted provider - and an Ollama
#: reachable over the internet is an unauthenticated inference endpoint, because
#: Ollama has no authentication at all.
LOCAL_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1", "host.docker.internal"})

#: §5.2's rule, which applies to every adapter: exactly one repair attempt. A
#: local model that cannot produce the schema twice will not produce it on the
#: fifth try either, and each attempt costs seconds of a developer's time
#: instead of money.
MAX_REPAIR_ATTEMPTS = 1


class RemoteOllamaRefused(ProviderNotConfigured):
    """A base URL that is not on this machine.

    Ollama has no authentication. A non-local base URL is either an
    unauthenticated inference endpoint on the network or resume text crossing
    it in plain text, and usually both.
    """


def check_base_url(base_url: str, *, app_env: str = "local") -> str:
    """The URL, or a refusal naming the host."""
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        raise RemoteOllamaRefused(f"{base_url!r} has no http(s) scheme")

    host = parsed.hostname or ""
    if host not in LOCAL_HOSTS:
        raise RemoteOllamaRefused(
            f"{host!r} is not a local host. Ollama has no authentication, so a "
            "remote one is an unauthenticated inference endpoint - and the "
            "prompts crossing to it carry resume text. Allowed: "
            f"{sorted(LOCAL_HOSTS)}."
        )
    if app_env == "prod":
        raise RemoteOllamaRefused(
            "ollama is selected in production. ADR-011 promotes it as the "
            "*local-development* provider; Gemini remains the R1 production "
            "default. A local model serving production extracts résumés with a "
            "3B model and nobody notices until the precision numbers are read."
        )
    return base_url.rstrip("/")


def assert_configuration(
    *,
    selected_providers: Sequence[str],
    base_url: str,
    model_fast: str,
    model_quality: str,
    app_env: str = "local",
) -> None:
    """`AC-AI-02.5` - an unresolvable provider fails at startup, not at first call.

    No credential check, because there is no credential. That absence is the
    point of the adapter, not an omission.
    """
    if "ollama" not in selected_providers:
        return
    if not (model_fast and model_quality):
        raise ProviderNotConfigured(
            "ollama is selected but OLLAMA_MODEL_FAST/OLLAMA_MODEL_QUALITY are "
            "unset. Model ids are configuration (`AC-AI-02.2`); pull one with "
            "`ollama pull <model>` and name it here."
        )
    check_base_url(base_url, app_env=app_env)


class OllamaProvider:
    """A locally hosted model, behind `LLMProvider` and `EmbeddingProvider`.

    Note what the signature does *not* take: no key, no token, no credentials.
    `AC-AI-05.4`'s introspection applies to Gemini, but the same shape holds
    here for free - there is nothing to hold.
    """

    name = "ollama"

    def __init__(
        self,
        *,
        model_fast: str,
        model_quality: str,
        embedding_model: str = "",
        embedding_dims: int = 768,
        base_url: str = DEFAULT_BASE_URL,
        transport: Any = None,
        app_env: str = "local",
        # Generous, and deliberately so: a 7B model on a CPU takes tens of
        # seconds for a resume, and a timeout tuned for a hosted provider would
        # make every local call look like a provider failure.
        timeout_seconds: float = 300.0,
    ) -> None:
        if not (model_fast and model_quality):
            raise ProviderNotConfigured(
                "OllamaProvider needs both model ids; they are configuration, "
                "never literals in a .py file (`AC-AI-02.2`)"
            )
        self._models = {Tier.FAST: model_fast, Tier.QUALITY: model_quality}
        self._embedding_model = embedding_model
        self._transport = transport
        self._timeout = timeout_seconds
        self._base_url = check_base_url(base_url, app_env=app_env)
        self.model = embedding_model
        self.dims = embedding_dims

    def model_for(self, tier: Tier) -> str:
        return self._models[tier]

    @staticmethod
    def tier_for(feature: Feature) -> Tier:
        """§5.2's mapping, identical to Gemini's.

        Identical on purpose: a feature asks for a tier, and which model a tier
        resolves to is the adapter's business. If the two adapters disagreed
        about which features are expensive, switching provider would silently
        change which ones got the better model.
        """
        return Tier.QUALITY if feature is Feature.PACK_GENERATE else Tier.FAST

    # -- the calls -----------------------------------------------------------

    async def complete(self, req: LLMRequest) -> LLMResponse:
        model = self.model_for(self.tier_for(req.feature))
        started = time.perf_counter()

        body = await self._post("/api/chat", self._build_payload(req, model))
        text, input_tokens, output_tokens = _read_completion(body)

        return LLMResponse(
            text=text,
            model=model,
            prompt_version=req.prompt_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    async def complete_json[M: BaseModel](self, req: LLMRequest, schema: type[M]) -> JsonResult[M]:
        """Ask for the schema, then validate anyway, then repair exactly once.

        The "validate anyway" is not defensive habit here, it is necessary. A
        local 7B model asked for structured output produces *plausible* JSON far
        more often than it produces *correct* JSON - a date as `"2023"`, a list
        where an object belongs, a confidence of `1.5`. Trusting the format
        request is how a model's invention becomes a stored fact.
        """
        first = await self._json_attempt(req, schema)
        if first[0] is not None:
            return JsonResult(value=first[0], raw_text=first[1], repaired=False, response=first[2])

        repaired = await self._json_attempt(
            self._repair_request(req, first[1], first[3] or ""), schema
        )
        if repaired[0] is not None:
            logger.info(
                "structured output repaired on the second attempt",
                extra={"feature": str(req.feature), "provider": self.name},
            )
            return JsonResult(
                value=repaired[0], raw_text=repaired[1], repaired=True, response=repaired[2]
            )

        raise StructuredOutputInvalid(
            f"{req.feature} produced output that does not satisfy "
            f"{schema.__name__} on either attempt. A local model's format "
            f"adherence is worse than a hosted one's; consider a larger model "
            f"for this feature. Validation error: {repaired[3]}"
        )

    async def _json_attempt[M: BaseModel](
        self, req: LLMRequest, schema: type[M]
    ) -> tuple[M | None, str, LLMResponse, str | None]:
        model = self.model_for(self.tier_for(req.feature))
        started = time.perf_counter()

        payload = self._build_payload(req, model)
        # Ollama takes a JSON schema in `format`, which constrains decoding.
        payload["format"] = schema.model_json_schema()

        body = await self._post("/api/chat", payload)
        text, input_tokens, output_tokens = _read_completion(body)
        response = LLMResponse(
            text=text,
            model=model,
            prompt_version=req.prompt_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached=False,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

        try:
            return schema.model_validate_json(text), text, response, None
        except ValidationError as invalid:
            return None, text, response, str(invalid)

    def _repair_request(self, req: LLMRequest, offending: str, error: str) -> LLMRequest:
        """The offending text goes in `untrusted`, never into `system`.

        It is model output, and HR-11 says model output never steers the
        program. An injection that survived the first call must not get a
        second, cleaner run at the system prompt - so it is wrapped in the same
        nonce-delimited block a job description gets.
        """
        from dataclasses import replace

        return replace(
            req,
            system=(
                f"{req.system}\n\n"
                "The previous response did not satisfy the required schema. "
                "Correct it and return only valid JSON. The validation error "
                f"was: {error}"
            ),
            untrusted={**req.untrusted, "previous_invalid_response": offending},
        )

    def stream(self, req: LLMRequest) -> AsyncIterator[str]:
        """Not implemented, for the same reason as Gemini's.

        No R1 feature streams model output - `FOUND-11` streams stage progress -
        and a silent fallback to a blocking call would hide that from whoever
        adds the first one.
        """
        raise ProviderNotConfigured(
            "the Ollama adapter does not stream; no R1 feature streams model output"
        )

    async def embed(self, texts: Sequence[str], task: Literal["document", "query"]) -> list[Vector]:
        """Local embeddings, quantized the same way as every other provider's.

        `task` is accepted and ignored: Ollama's embedding endpoint has no
        task-type parameter. Ignored rather than rejected, because the caller
        should not have to know which provider is configured - and the
        distinction affects retrieval quality, not correctness.
        """
        if not self._embedding_model:
            raise ProviderNotConfigured(
                "OLLAMA_EMBEDDING_MODEL is unset; pull one with "
                "`ollama pull nomic-embed-text` and name it in configuration"
            )

        vectors: list[Vector] = []
        for text in texts:
            body = await self._post("/api/embed", {"model": self._embedding_model, "input": text})
            raw = body.get("embeddings") or []
            values = [float(value) for value in (raw[0] if raw else [])]
            vectors.append(quantize(values, model=self._embedding_model))
        return vectors

    # -- the wire ------------------------------------------------------------

    def _build_payload(self, req: LLMRequest, model: str) -> dict[str, Any]:
        """Ollama's chat body, with untrusted content rendered by the AI layer.

        §6 again: a feature never concatenates untrusted text into a system
        prompt. The nonce-delimited block is the only path by which a job
        description reaches a model, whichever model it is.
        """
        system = req.system
        if req.untrusted:
            rendered = render_untrusted(req.untrusted)
            system = f"{system}\n\n{rendered.text}"
            if rendered.was_truncated:
                logger.info(
                    "untrusted content was truncated before the call",
                    extra={"feature": str(req.feature), "slots": list(rendered.truncated)},
                )

        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        messages.extend(
            {"role": "user" if message.role == "user" else "assistant", "content": message.content}
            for message in req.messages
        )
        if len(messages) == 1:
            messages.append({"role": "user", "content": ""})

        return {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": req.temperature,
                "num_predict": req.max_output_tokens,
            },
        }

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """One HTTP call, with errors as codes rather than bodies.

        `AC-FOUND-14.5` applies here too. A local model's error body echoes the
        prompt just as readily as a hosted one's, and the log does not care that
        the round trip was to `127.0.0.1`.
        """
        if self._transport is None:
            raise ProviderNotConfigured(
                "OllamaProvider has no HTTP transport; one is injected at startup"
            )

        try:
            response = await self._transport.post(
                f"{self._base_url}{path}",
                json=payload,
                headers={"content-type": "application/json"},
                timeout=self._timeout,
            )
        except Exception as failure:
            raise ProviderError(self.name, 0, _local_failure(failure)) from failure

        status = int(getattr(response, "status_code", 0))
        if status >= 400:
            raise ProviderError(self.name, status, _classify(status))

        parsed: dict[str, Any] = response.json()
        return parsed


def _read_completion(body: Mapping[str, Any]) -> tuple[str, int, int]:
    """The text and Ollama's own token counts.

    `prompt_eval_count` and `eval_count` are what the server reports, and they
    are used as-is (`AC-AI-03.3`). They cost nothing locally, but they are what
    makes `ai_usage` rows comparable across providers - and a row with zero
    tokens would make a local call invisible on the dashboard rather than free.
    """
    message = body.get("message") or {}
    text = str(message.get("content", ""))
    return (
        text,
        int(body.get("prompt_eval_count", 0)),
        int(body.get("eval_count", 0)),
    )


def _classify(status: int) -> str:
    return {
        400: "invalid_request",
        404: "model_not_pulled",
        500: "provider_internal",
        503: "provider_unavailable",
    }.get(status, f"http_{status}")


def _local_failure(failure: BaseException) -> str:
    """A connection refused to `127.0.0.1:11434` has one overwhelmingly likely
    cause, and saying so saves the reader a search."""
    name = type(failure).__name__
    if "Connect" in name or "Refused" in name:
        return "ollama_not_running"
    return name


__all__ = [
    "DEFAULT_BASE_URL",
    "LOCAL_HOSTS",
    "MAX_REPAIR_ATTEMPTS",
    "OllamaProvider",
    "RemoteOllamaRefused",
    "assert_configuration",
    "check_base_url",
]
