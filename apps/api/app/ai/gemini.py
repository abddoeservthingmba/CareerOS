"""The Gemini adapter, and isolation from Google AI Pro - `AI-05`.

`05-ai-layer.md` §5: "Use Gemini through its Developer API on a key whose
billing is entirely separate from any consumer Google subscription, and make it
structurally impossible for a consumer credential or a user's sign-in token to
reach an inference call (HR-6)."

§5.1 is unusually careful about what the risk actually is, and it is worth
restating because the obvious reading is wrong. A Google AI Pro subscription is
a **consumer entitlement**. It grants nothing to the API, cannot authenticate a
request, and there is no code path by which API usage could be billed to it. So
the risk is not accidental spending. It is three other things:

1. **Key provenance.** A key from a project that shares a billing account with
   other work makes this product's spend indistinguishable from everything
   else, which defeats `AI-04` entirely and makes a spend alert unactionable.
   That control is procurement, not code, and lives in
   `docs/compliance/ai-providers.md`.
2. **Credential confusion.** Google OAuth is used here for *sign-in*
   (`AUTH-02`). Sign-in and inference both say "Google". A future change that
   reached for an available Google credential in the AI path - a user's OAuth
   token, application default credentials, a broad service account - would
   attach a user's identity to inference calls and could implicate their
   consumer account. This is what the class below is shaped to prevent.
3. **Terms drift.** Free-tier and paid-tier prompt-data terms differ, and the
   difference is exactly what the consent screen promises (§5.4, D5).

**The isolation is structural, not procedural.** This class takes one argument
that can hold a credential and it is a `str`. There is no parameter, attribute,
or method that can hold a token, a credentials object, or a service-account
path; nothing here reads `os.environ`; and `AC-AI-05.4` asserts all of that by
introspection rather than by review. The same move as `LLMRequest` having no
`file` field under HR-8: the rule is enforced by there being nowhere to put the
thing.

**Two startup guards** (`AC-AI-05.2`), both of which refuse to boot:

* `gemini` selected with no `GEMINI_API_KEY` - because the alternative is a
  container that starts healthy and fails at the first resume upload;
* `GOOGLE_APPLICATION_CREDENTIALS` present *at all* - because its presence means
  an ambient Google credential exists in this process, and the whole point of
  risk 2 is that the AI path must not be able to find one. That it is currently
  unused is not a defence; it is a loaded gun on the table.

**A base-URL allowlist** (`AC-AI-05.7`), because a configurable base URL is a
configurable exfiltration target: a proxy in the middle of this call sees every
resume and every job description in plain text.
"""

from __future__ import annotations

import json
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

logger = logging.getLogger("app.ai.gemini")

#: `AC-AI-05.7`. Hosts the adapter will talk to, and nothing else. A configured
#: base URL outside this set fails at startup rather than at first call: the
#: failure mode it guards is an accidental - or malicious - proxy that sees
#: every resume and job description in plain text on its way past.
#:
#: `localhost` is present for the record-and-replay tests, and only ever with an
#: explicit port; a bare `localhost` in a production configuration is caught by
#: the environment check in `assert_configuration`.
ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "generativelanguage.googleapis.com",
        "127.0.0.1",
        "localhost",
    }
)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"

#: The one environment variable whose mere presence is a misconfiguration
#: (`AC-AI-05.2`). Google's client libraries read it to find a service account;
#: if it is set, an ambient credential exists that the AI path must not be able
#: to reach.
AMBIENT_CREDENTIAL_VARS = ("GOOGLE_APPLICATION_CREDENTIALS",)

#: §5.2: "on failure retry exactly once with a repair prompt". Exactly once.
#: A loop would spend a user's budget on a model that has already demonstrated
#: it cannot produce the schema.
MAX_REPAIR_ATTEMPTS = 1


class BaseUrlNotAllowed(ProviderNotConfigured):
    """`AC-AI-05.7` - a base URL that is not on the allowlist."""


class AmbientCredentialPresent(ProviderNotConfigured):
    """`AC-AI-05.2` - `GOOGLE_APPLICATION_CREDENTIALS` is set in this process.

    A separate class from `ProviderNotConfigured`'s other causes because the
    remedy is different and specific: unset the variable. Nothing about the
    Gemini key is wrong.
    """


def check_base_url(base_url: str) -> str:
    """The URL, or a refusal naming the host.

    Validated by host rather than by prefix. A prefix check passes
    `https://generativelanguage.googleapis.com.attacker.example`, which is a
    different site with a reassuring name - and that is the exact trick this
    exists to stop.
    """
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        raise BaseUrlNotAllowed(
            f"{base_url!r} has no http(s) scheme; a base URL is a host this "
            "adapter will send resume text to, so it is validated rather than "
            "trusted"
        )
    host = parsed.hostname or ""
    if host not in ALLOWED_HOSTS:
        raise BaseUrlNotAllowed(
            f"{host!r} is not an allowed Gemini host. Allowed: "
            f"{sorted(ALLOWED_HOSTS)}. A configurable base URL is a "
            "configurable exfiltration target: whatever sits at that address "
            "sees every resume and job description in plain text."
        )
    if parsed.scheme == "http" and host not in ("127.0.0.1", "localhost"):
        raise BaseUrlNotAllowed(
            f"{base_url!r} is plaintext http to a remote host; prompts contain resume text"
        )
    return base_url.rstrip("/")


def assert_configuration(
    *,
    selected_providers: Sequence[str],
    api_key: str,
    base_url: str,
    environ: Mapping[str, str],
    app_env: str = "local",
) -> None:
    """`AC-AI-05.2` and `.7` - the boot-time refusals.

    `environ` is passed in rather than read, because `AC-AI-05.4` asserts that
    nothing in this module reads the environment: a check that read `os.environ`
    would be the one code path in the file able to find an ambient credential,
    which is precisely the thing being guarded against.
    """
    for variable in AMBIENT_CREDENTIAL_VARS:
        if environ.get(variable):
            raise AmbientCredentialPresent(
                f"{variable} is set in this process. Its presence means an "
                "ambient Google credential exists that the AI path must not be "
                "able to find (HR-6, `05-ai-layer.md` §5.1 risk 2). Unset it; "
                "the Gemini adapter takes an API key by constructor injection "
                "and nothing else."
            )

    if "gemini" not in selected_providers:
        return

    if not api_key:
        raise ProviderNotConfigured(
            "gemini is selected by AI_PROVIDER_* but GEMINI_API_KEY is unset. "
            "Refusing to boot rather than starting healthy and failing at the "
            "first resume upload."
        )

    checked = check_base_url(base_url)
    if app_env == "prod" and urlparse(checked).hostname in ("127.0.0.1", "localhost"):
        raise BaseUrlNotAllowed(
            "GEMINI_BASE_URL points at localhost in production. That is either "
            "a proxy nobody declared or a configuration left over from a test."
        )


class GeminiProvider:
    """Gemini's Developer API, behind `LLMProvider` and `EmbeddingProvider`.

    Note what the signature cannot express. There is no `credentials`, no
    `token`, no `service_account`, no `adc` and no `oauth` parameter, and
    `AC-AI-05.4` asserts by introspection that none is ever added. The key is a
    `str`, injected once at startup by `ai/registry.py`, and it is the only
    thing here that authenticates anything.
    """

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        *,
        model_fast: str,
        model_quality: str,
        embedding_model: str,
        embedding_dims: int = 3072,
        base_url: str = DEFAULT_BASE_URL,
        transport: Any = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key:
            raise ProviderNotConfigured(
                "GeminiProvider needs an API key; it has no other way to "
                "authenticate and deliberately no way to find one"
            )
        if not (model_fast and model_quality):
            raise ProviderNotConfigured(
                "GEMINI_MODEL_FAST and GEMINI_MODEL_QUALITY are configuration "
                "(`AC-AI-02.2`); a model id is never a literal in a .py file"
            )

        # Held in a closure, not an attribute. Name mangling alone was not
        # enough: `_GeminiProvider__key` still appears in `vars(self)`, which is
        # what a debug dump, a pickle and - the one that matters - a Sentry
        # stack frame's local variables all reach for. Worse,
        # `core/redaction.py` would not have scrubbed it: its key list holds
        # `api_key`, not a bare `key`, so the mangled name would have travelled
        # to a vendor's search index intact.
        #
        # A closure cell is not in `__dict__` and is not serialised by any of
        # those paths. `test_gemini_credential_surface.py` is what found this.
        def authorise() -> dict[str, str]:
            return {"x-goog-api-key": api_key, "content-type": "application/json"}

        self.__authorise = authorise
        self._models = {Tier.FAST: model_fast, Tier.QUALITY: model_quality}
        self._embedding_model = embedding_model
        self._transport = transport
        self._timeout = timeout_seconds
        self._base_url = check_base_url(base_url)
        self.model = embedding_model
        self.dims = embedding_dims

    # -- model selection -----------------------------------------------------

    def model_for(self, tier: Tier) -> str:
        """§5.2's tier mapping. A feature asks for a tier, never for a model."""
        return self._models[tier]

    @staticmethod
    def tier_for(feature: Feature) -> Tier:
        """§5.2: "`fast` for extraction, enrichment, rationale, follow-up drafts
        and answer suggestions; `quality` for pack generation."

        One place, so a feature added later cannot silently default to the
        expensive tier - or to the cheap one, which is worse, because it would
        be discovered as a quality complaint rather than as a bill.
        """
        return Tier.QUALITY if feature is Feature.PACK_GENERATE else Tier.FAST

    # -- the calls -----------------------------------------------------------

    async def complete(self, req: LLMRequest) -> LLMResponse:
        tier = self.tier_for(req.feature)
        model = self.model_for(tier)
        started = time.perf_counter()

        payload = self._build_payload(req, model)
        body = await self._post(f"/v1beta/models/{model}:generateContent", payload)

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
        """§5.2's three steps, in order, and the repair is exactly one.

        "pass the JSON schema via the provider's structured-output facility,
        then **still** validate with Pydantic, then on failure retry exactly
        once with a repair prompt that includes the validation error and the
        offending text."

        The "still validate" is the load-bearing word. A provider's
        structured-output mode constrains the *shape* and cannot know a business
        rule - that a score is 0-100, that a date is not in the future, that a
        skill is in the dictionary. Trusting the mode is how a model's plausible
        invention becomes a stored fact.
        """
        first = await self._json_attempt(req, schema)
        if first.value is not None:
            return JsonResult(
                value=first.value, raw_text=first.text, repaired=False, response=first.response
            )

        # Exactly one repair. A loop would spend a user's budget on a model that
        # has already shown it cannot produce this schema.
        repaired = await self._json_attempt(
            self._repair_request(req, first.text, first.error or ""), schema
        )
        if repaired.value is not None:
            logger.info(
                "structured output repaired on the second attempt",
                extra={"feature": str(req.feature), "prompt_version": req.prompt_version},
            )
            return JsonResult(
                value=repaired.value,
                raw_text=repaired.text,
                repaired=True,
                response=repaired.response,
            )

        raise StructuredOutputInvalid(
            f"{req.feature} produced output that does not satisfy "
            f"{schema.__name__} on either the first attempt or the repair. "
            f"Validation error: {repaired.error}"
        )

    async def _json_attempt[M: BaseModel](self, req: LLMRequest, schema: type[M]) -> _Attempt[M]:
        tier = self.tier_for(req.feature)
        model = self.model_for(tier)
        started = time.perf_counter()

        payload = self._build_payload(req, model)
        payload["generationConfig"]["responseMimeType"] = "application/json"
        payload["generationConfig"]["responseJsonSchema"] = schema.model_json_schema()

        body = await self._post(f"/v1beta/models/{model}:generateContent", payload)
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
            return _Attempt(value=schema.model_validate_json(text), text=text, response=response)
        except ValidationError as invalid:
            return _Attempt(value=None, text=text, response=response, error=str(invalid))

    def _repair_request(self, req: LLMRequest, offending: str, error: str) -> LLMRequest:
        """§5.2's repair prompt: the validation error and the offending text.

        The offending text goes in `untrusted`, not into `system`. It is model
        output, and HR-11 says model output never steers the program - so it is
        wrapped in the same nonce-delimited block a job description gets, and
        for the same reason: an injection that survived the first call must not
        get a second, cleaner run at the system prompt.
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
        """Not implemented, and deliberately not a silent fallback.

        `FOUND-11` streams *progress*, not tokens: the client watches stages,
        and no R1 feature streams model output. An adapter that quietly fell
        back to a blocking call would make a future streaming feature look like
        it worked while buffering the whole response.
        """
        raise ProviderNotConfigured(
            "the Gemini adapter does not stream. No R1 feature streams model "
            "output - `FOUND-11` streams stage progress - and a silent fallback "
            "to a blocking call would hide that from whoever adds the first one."
        )

    async def embed(self, texts: Sequence[str], task: Literal["document", "query"]) -> list[Vector]:
        """`DATA-06`'s quantized vectors, from Gemini's embedding model."""
        if not self._embedding_model:
            raise ProviderNotConfigured("GEMINI_EMBEDDING_MODEL is unset")

        body = await self._post(
            f"/v1beta/models/{self._embedding_model}:batchEmbedContents",
            {
                "requests": [
                    {
                        "model": f"models/{self._embedding_model}",
                        "content": {"parts": [{"text": text}]},
                        "taskType": (
                            "RETRIEVAL_DOCUMENT" if task == "document" else "RETRIEVAL_QUERY"
                        ),
                    }
                    for text in texts
                ]
            },
        )
        vectors: list[Vector] = []
        for entry in body.get("embeddings", []):
            values = [float(value) for value in entry.get("values", [])]
            vectors.append(quantize(values, model=self._embedding_model))
        return vectors

    # -- the wire ------------------------------------------------------------

    def _build_payload(self, req: LLMRequest, model: str) -> dict[str, Any]:
        """The request body, with untrusted content rendered by the AI layer.

        §6: untrusted text is never concatenated into the system prompt by a
        feature. `render_untrusted` wraps it in a nonce-delimited block, which
        is the only path by which a job description reaches a model.
        """
        system = req.system
        if req.untrusted:
            system = f"{system}\n\n{render_untrusted(req.untrusted)}"

        contents = [
            {
                "role": "user" if message.role == "user" else "model",
                "parts": [{"text": message.content}],
            }
            for message in req.messages
        ]
        if not contents:
            contents = [{"role": "user", "parts": [{"text": ""}]}]

        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {
                "temperature": req.temperature,
                "maxOutputTokens": req.max_output_tokens,
            },
        }

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """One HTTP call, with the key in a header and errors as codes.

        The key travels in `x-goog-api-key` rather than in the query string: a
        URL is logged by every proxy, load balancer and browser history between
        here and there, and §14 forbids a credential reaching a log.

        A provider failure is re-raised as `ProviderError` carrying a status and
        a code - never the response body, which routinely echoes the prompt
        (`AC-FOUND-14.5`).
        """
        if self._transport is None:
            raise ProviderNotConfigured(
                "GeminiProvider has no HTTP transport. One is injected at "
                "startup; there is no path here that constructs a client, "
                "because that path would also be a path to a credential."
            )

        try:
            response = await self._transport.post(
                f"{self._base_url}{path}",
                json=payload,
                headers=self.__authorise(),
                timeout=self._timeout,
            )
        except Exception as failure:
            raise ProviderError(self.name, 0, type(failure).__name__) from failure

        status = int(getattr(response, "status_code", 0))
        if status >= 400:
            raise ProviderError(self.name, status, _classify(status))

        parsed: dict[str, Any] = response.json()
        return parsed


class _Attempt[M: BaseModel]:
    """One structured-output attempt: parsed, or the text that would not parse."""

    __slots__ = ("error", "response", "text", "value")

    def __init__(
        self,
        value: M | None,
        text: str,
        response: LLMResponse,
        error: str | None = None,
    ) -> None:
        self.value = value
        self.text = text
        self.response = response
        self.error = error


def _read_completion(body: Mapping[str, Any]) -> tuple[str, int, int]:
    """The text and the provider's own token counts.

    The counts are the provider's (`AC-AI-03.3`): their tokenizer, their
    accounting for system instructions and schemas. A local estimate drifts, and
    always in the direction of under-counting what they charge for.
    """
    candidates = body.get("candidates") or []
    text = ""
    if candidates:
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(str(part.get("text", "")) for part in parts)

    usage = body.get("usageMetadata") or {}
    return (
        text,
        int(usage.get("promptTokenCount", 0)),
        # Thinking tokens are billed as output, so they are counted as output.
        int(usage.get("candidatesTokenCount", 0)) + int(usage.get("thoughtsTokenCount", 0)),
    )


def _classify(status: int) -> str:
    """A status to a stable code, so a dashboard can group failures.

    Codes rather than the provider's message, which can echo the prompt back
    (`AC-FOUND-14.5`).

    These are *provider* labels, not `ErrorCode` members: they name what Gemini
    said, and never reach a response body. `provider_rate_limited` carries the
    prefix for that reason - a bare `rate_limited` would collide with the API's
    own registry code (`AC-FOUND-12.4`), and the two mean different things. Ours
    is the user hitting our limit; this one is us hitting Google's.
    """
    return {
        400: "invalid_request",
        401: "unauthenticated",
        403: "permission_denied",
        404: "model_not_found",
        429: "provider_rate_limited",
        500: "provider_internal",
        503: "provider_unavailable",
    }.get(status, f"http_{status}")


def _json_dumps(payload: Any) -> str:
    """Used only by the record-and-replay tests; kept here so the payload shape
    has one canonical rendering."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


__all__ = [
    "ALLOWED_HOSTS",
    "AMBIENT_CREDENTIAL_VARS",
    "DEFAULT_BASE_URL",
    "MAX_REPAIR_ATTEMPTS",
    "AmbientCredentialPresent",
    "BaseUrlNotAllowed",
    "GeminiProvider",
    "assert_configuration",
    "check_base_url",
]
