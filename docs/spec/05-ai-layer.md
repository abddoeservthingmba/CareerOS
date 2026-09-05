# 05 — AI Layer (Provider-Agnostic, Gemini First)

**Module:** `apps/api/app/ai`
**Track:** R1 (all sections)
**Depends on:** `01-foundations.md` §2, §4, §10, §14
**Depended on by:** resume, profile, jobs, matching, apply
**Requirements:** `AI-01` … `AI-07`
**Public API:** `ai/__init__.py` exports `get_llm(feature)`, `get_embedder()`, `LLMRequest`, `LLMResponse`, `AIError`, `AIBudgetExceeded`, `EmbeddingModelMismatch`
**Publishes events:** none. **Consumes events:** none. The AI layer is a leaf.

This file resolves the second of the two flagged decisions in `README.md` §1. Read that section first; this is its implementation.

---

## 1. The contract — `AI-01`

**Objective.** Feature modules describe what they want from a model and never learn which model answered.

**Constraints.**
- Two protocols in `ai/base.py`, and nothing else in that file that touches a network:

```python
class LLMProvider(Protocol):
    name: str
    async def complete(self, req: LLMRequest) -> LLMResponse: ...
    async def complete_json(self, req: LLMRequest, schema: type[M]) -> JsonResult[M]: ...
    async def stream(self, req: LLMRequest) -> AsyncIterator[str]: ...

class EmbeddingProvider(Protocol):
    name: str
    model: str
    dims: int
    async def embed(self, texts: list[str], task: Literal["document", "query"]) -> list[Vector]: ...
```

```python
@dataclass(frozen=True)
class LLMRequest:
    feature: str                     # REQUIRED. Cost attribution and budget key.
    system: str
    messages: list[Message]
    untrusted: dict[str, str] = field(default_factory=dict)   # §6: content, delimited by the layer
    temperature: float = 0.2
    max_output_tokens: int = 1024
    user_id: str | None = None
    cache_key: str | None = None
    prompt_version: str = ""         # REQUIRED for any prompt-backed call

@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    cached: bool
    latency_ms: int

@dataclass(frozen=True)
class JsonResult(Generic[M]):
    value: M
    raw_text: str
    repaired: bool                   # True if the repair retry produced this
    response: LLMResponse
```

- `feature` is not optional and not free text: it is a member of a `Feature` StrEnum (`resume_extract`, `resume_quality`, `job_enrich`, `match_rationale`, `pack_generate`, `followup_draft`, `answer_suggest`, `embed_profile`, `embed_job`, `embed_question`). Budgets, pricing, provider selection, and the admin dashboard all key on it.
- No provider SDK type appears in any signature, return value, or exception raised across the boundary (HR-5). A provider's own exception is caught in the adapter and re-raised as an `AIError` subclass.
- `complete_json` is the only structured path. A feature that wants JSON never parses `complete()` output itself.
- Vectors carry their model: `Vector = tuple[str, int, bytes]` — `(model, dims, quantized)` per `17-data-model.md` §6 — or an equivalent frozen dataclass. A bare `list[float]` never crosses the boundary, which is what makes `EmbeddingModelMismatch` possible to enforce.

**Inputs.** A feature name, a prompt, a schema.

**Outputs.** `ai/base.py`, `ai/__init__.py`, the `Feature` enum, the exception hierarchy.

**Acceptance criteria.**
- `AC-AI-01.1` `ai/base.py` imports nothing outside the standard library, `pydantic`, and `app.shared` — in particular no HTTP client and no provider SDK.
- `AC-AI-01.2` Constructing an `LLMRequest` without `feature`, or with a `feature` outside the enum, raises.
- `AC-AI-01.3` A repo-wide check finds no import of a provider SDK outside `ai/<provider>.py`, and no `modules/*` import of `ai.gemini` or any other concrete adapter (HR-5).
- `AC-AI-01.4` Every public method of every adapter raises only `AIError` subclasses; a fault-injection test forces each provider failure mode and asserts the exception type.
- `AC-AI-01.5` `complete_json` returns a validated instance of the requested schema or raises; it never returns a dict.

**Tests.**
- `T-AI-01.1` `tests/spec/test_ai_base_purity.py`.
- `T-AI-01.2` `tests/unit/test_llm_request.py`.
- `T-AI-01.3` `tests/spec/test_layer_leaks.py` (shared with `T-FOUND-01.4`) plus the `no-concrete-ai` import contract.
- `T-AI-01.4` `tests/ai/test_adapter_error_mapping.py`, parametrized over adapters and fault modes.
- `T-AI-01.5` `tests/ai/test_complete_json_contract.py`.

---

## 2. Selection and the registry — `AI-02`

**Objective.** Change which model serves a feature by changing configuration, with no code edit and no redeploy of a feature module.

**Constraints.**
- `ai/registry.py` resolves `Feature -> LLMProvider` and a single `EmbeddingProvider`, from `Settings`:

```
AI_PROVIDER_DEFAULT=gemini
AI_PROVIDER_RESUME_EXTRACT=gemini          # per-feature override, optional
AI_PROVIDER_MATCH_RATIONALE=gemini
AI_EMBEDDING_PROVIDER=gemini
GEMINI_MODEL_FAST=<model id>
GEMINI_MODEL_QUALITY=<model id>
GEMINI_EMBEDDING_MODEL=<model id>
```

- Model identifiers are **configuration, never code**. No model name is a literal in a `.py` file outside `.env.example` documentation. Gemini model names and free-tier limits change often enough that a hard-coded name is a scheduled outage.
- Each feature declares which **tier** it wants (`fast` or `quality`), not which model. The adapter maps tier to the configured model id.
- Providers are constructed once at startup and injected. An adapter never reads the environment (§5).
- Adapters present in R1: `gemini.py` (real), `fake.py` (deterministic, used by every test and by local development without a key). `openai.py`, `anthropic.py`, and `ollama.py` are R1 **stubs** that exist only to prove the contract: each is a class that satisfies the protocol, raises `ProviderNotConfigured` when called, and is included in the adapter contract test suite so that the protocol cannot drift into being Gemini-shaped.
- **Embedding model changes are a migration, not a config flip.** Switching `AI_EMBEDDING_PROVIDER` or the embedding model requires re-embedding every profile and job; the registry refuses to start if the configured embedding model differs from the one recorded in a `system_state` document unless `AI_EMBEDDING_MIGRATION=allow` is set, and starting with that flag enqueues `ai.reembed_all`.

**Inputs.** `Settings`; the `Feature` enum.

**Outputs.** `ai/registry.py`; `get_llm(feature)`; `get_embedder()`; startup validation.

**Acceptance criteria.**
- `AC-AI-02.1` Setting `AI_PROVIDER_MATCH_RATIONALE=fake` routes only that feature to the fake provider; every other feature still resolves to the default.
- `AC-AI-02.2` No model identifier string appears in any `.py` file (checked against a pattern list for the known provider naming shapes).
- `AC-AI-02.3` All five adapters pass the same contract suite; the three stubs pass by raising `ProviderNotConfigured` where a real call would occur.
- `AC-AI-02.4` Starting with a changed embedding model and no migration flag exits non-zero with a message naming both models; with the flag, it starts and `ai.reembed_all` is enqueued.
- `AC-AI-02.5` `get_llm` for a feature with no override and no default configured raises at startup, not at first call.

**Tests.**
- `T-AI-02.1` `tests/ai/test_registry_routing.py`.
- `T-AI-02.2` `tests/spec/test_no_model_literals.py`.
- `T-AI-02.3` `tests/ai/test_provider_contract.py`, parametrized over all adapters.
- `T-AI-02.4` `tests/ai/test_embedding_migration_guard.py`.
- `T-AI-02.5` `tests/ai/test_registry_startup_validation.py`.

---

## 3. Budgets, caching and degradation — `AI-03`

**Objective.** A runaway loop, a viral signup, or a badly-tuned top-N cannot produce a surprise bill, and hitting a cap degrades the product in a way that is specified per feature rather than improvised.

### 3.1 Budget state, and the order the checks run

**Constraints.**
- Three counters in Redis, all keyed to the UTC day and reset at 00:00 UTC: `ai:spend:global:{date}`, `ai:spend:feature:{feature}:{date}`, `ai:calls:user:{user_id}:{date}`.
- Caps come from config: `AI_DAILY_COST_CAP_USD` (global), `AI_FEATURE_CAP_USD__<FEATURE>` (optional, per feature), `AI_USER_DAILY_CALLS` (per user).
- **Check order is fixed and the first failure wins**, so a denial always has one unambiguous reason recorded in `ai_usage.deny_reason`:
  1. `user` — per-user daily call count
  2. `feature` — per-feature daily spend
  3. `global` — global daily spend
  Rationale for that order: an abusive account should be stopped before it is allowed to exhaust a shared budget, and a single feature's runaway should be attributed to that feature rather than reported as a global outage.
- **The pre-call check uses an estimate; the post-call record uses actuals.** Estimate = `measured_input_tokens × input_price + max_output_tokens × output_price`, deliberately pessimistic on output so a single large call cannot overshoot a cap it was under. Actual spend replaces the estimate in the counter after the call returns.
- **Budget state** is one of three values, exposed as the `ai_budget_state{feature}` gauge and on the admin dashboard:

| State | Condition | Behaviour |
|---|---|---|
| `ok` | spend < 80% of the binding cap | Normal |
| `soft` | 80–100% of the binding cap | Normal, plus a warning on the dashboard and one alert per day |
| `hard` | estimate would cross the cap | `AIBudgetExceeded` raised before the provider is contacted; the feature degrades per §3.2 |
- A cache hit is **free and is never denied**: the cache is checked before the budget, so a cached result is served even in `hard` state. This is what keeps job enrichment and rationale serving users during a cap breach.
- Rate limits are separate from cost caps. A per-provider token bucket at the provider's requests-per-minute limit queues and retries rather than rejecting: a burst of 200 enrichments drains slowly, it does not fail.
- Recovery is automatic at the next UTC day boundary. No feature requires a manual reset, and no degraded state persists past the reset.

### 3.2 The degradation matrix

Normative. Each row is the complete contract for one feature: what it does when the budget denies it, what the user sees, what is recorded, and how it recovers. **No feature may propagate `AIBudgetExceeded` to the user as an unhandled error**, and the two rows that do surface an error do so with a specific code and a `Retry-After`.

| Feature | Tier | Degradation | User-visible state | Recorded | Recovery |
|---|---|---|---|---|---|
| `resume_extract` | fast | Task retries with backoff for up to 24 h; the resume stays in `structuring` | "We're finishing this shortly" on the review screen; no error, no failed state | `outcome: budget_denied`, `deny_reason` | Automatic at the next reset, or when the retry lands; no user action |
| `resume_quality` | fast | Skipped entirely; deterministic checks still run | Deterministic feedback only, no gap in the UI | `outcome: budget_denied` | Next re-analysis; never retried on its own |
| `job_enrich` | fast | Dictionary-only skills; `skills_source: "dictionary"` | None — the job is visible and scoreable | `outcome: budget_denied` per job | `jobs.backfill_enrichment` at the next reset, gated the same way |
| `match_rationale` | fast | `rationale` stays null | The full deterministic breakdown with no empty placeholder | `outcome: budget_denied` | Next top-N selection; never backfilled, because a rationale for a job the user has moved past is worth nothing |
| `pack_generate` | quality | **Refuses**: `503 ai_budget_exceeded` with `Retry-After` set to seconds until the UTC reset | An explicit "we can't draft this right now, try after HH:MM" with the user's existing edits preserved | `outcome: budget_denied` | User retries after `Retry-After`; the idempotency key is still valid |
| `followup_draft` | fast | Falls back to a **template with placeholders**, not an error | A draft the user can edit, labelled as a template rather than AI-written | `outcome: budget_denied` | Next request |
| `answer_suggest` | fast | Skipped; the suggest button reports it is unavailable today | The user types the answer, which they can always do | `outcome: budget_denied` | Next day |
| `embed_profile` | — | Profile stored without an embedding | None | `outcome: budget_denied` | `ai.backfill_embeddings` at the next reset |
| `embed_job` | — | Job stored without an embedding; scoring uses the dictionary skills path (`08-matching.md` §2) | None | `outcome: budget_denied` | `ai.backfill_embeddings` at the next reset |
| `embed_question` | — | Answer-bank matching falls back to the `rapidfuzz` stage only | Slightly worse question matching; `needs_user` more often | `outcome: budget_denied` | Next suggestion or next backfill |

Three properties this matrix is built to guarantee, each separately testable:

- **No silent success.** Every degraded path writes an `ai_usage` row with `outcome: budget_denied` and a `deny_reason`. A feature that quietly does nothing is indistinguishable from a bug.
- **No data loss.** `pack_generate` is the only feature that refuses outright, and it preserves every user edit; nothing else discards work.
- **No permanent degradation.** Every row names a recovery, and the two rows that deliberately do not backfill (`match_rationale`, `resume_quality`) say so and say why.

### 3.3 Caching

**Constraints.**
- `complete_json` and `embed` results are cached in Redis under `sha256(provider | model | prompt_version | canonicalized_input)`, TTL `AI_CACHE_TTL_DAYS` (default 7).
- A cache hit writes an `ai_usage` row with `outcome: cache_hit` and `est_cost_usd: 0`. The row's `outcome` is the single representation of that fact — v2.0 also carried a `cached` boolean, which could disagree with `outcome`; `17-data-model.md` §2.12 now derives `cached` from `outcome` and does not store it twice (consistency finding F5).
- Embeddings are additionally cached **durably** on the `jobs` and `profiles` documents by `source_hash`, so they survive a Redis flush and are recomputed only when the source text changes.
- Job enrichment and match rationale are the highest-value cache targets: one enrichment serves every user who sees the job, which is the economics that makes the feature affordable at all.

**Inputs.** Config caps; Redis counters; measured token counts; the `MODEL_PRICING` table.

**Outputs.** `ai/budget.py`; `ai/usage.py`; `ai_usage` rows; `ai_budget_state{feature}` gauge; `docs/spec/ai-budget.yaml` — the matrix above in machine-readable form, which parametrizes the degradation tests.

**Acceptance criteria.**
- `AC-AI-03.1` For each of the ten features in §3.2, with the binding cap already consumed, the feature exhibits exactly its listed degradation, produces exactly its listed user-visible state, and writes `outcome: budget_denied`. Parametrized from `ai-budget.yaml`, so a feature added without a matrix row fails the test rather than defaulting to an error.
- `AC-AI-03.2` A call whose **estimate** would cross a cap is refused before the provider is contacted, asserted by the fake provider recording zero invocations.
- `AC-AI-03.3` Actual spend recorded after a call uses the provider's reported token counts, and `est_cost_usd` matches `MODEL_PRICING` to within a rounding cent.
- `AC-AI-03.4` The R1 gate scenario: the cap is deliberately tripped on staging and the resume pipeline, the feed and the pack flow each degrade as specified, with no 5xx in the logs other than the specified `503 ai_budget_exceeded`.
- `AC-AI-03.5` A repeated identical `complete_json` within the TTL contacts the provider once and writes two `ai_usage` rows, the second with `outcome: cache_hit` and `est_cost_usd: 0`.
- `AC-AI-03.6` 200 enrichment calls against a 15-per-minute limiter all complete, none raise, and elapsed time matches the limiter.
- `AC-AI-03.7` The three caps deny in the fixed order: with all three breached, `deny_reason` is `user`; with feature and global breached, `feature`; with only global breached, `global`.
- `AC-AI-03.8` A cache hit is served in `hard` budget state (the cache is checked before the budget).
- `AC-AI-03.9` `ai_budget_state` reports `ok`, `soft` and `hard` at the specified thresholds, and `soft` raises exactly one alert per day per feature.
- `AC-AI-03.10` Every degraded feature recovers without human action at the next UTC reset, verified with a frozen clock across the boundary for each backfilled feature.
- `AC-AI-03.11` `pack_generate` refused for budget preserves every prior user edit and returns a `Retry-After` equal to the seconds remaining until reset.
- `AC-AI-03.12` `ai-budget.yaml` has one row per `Feature` enum member; a member without a row, or a row without a member, fails.

**Tests.**
- `T-AI-03.1` `tests/ai/test_degradation.py`, parametrized from `ai-budget.yaml`.
- `T-AI-03.2` `tests/ai/test_precall_budget_check.py`.
- `T-AI-03.3` `tests/ai/test_cost_accounting.py`.
- `T-AI-03.4` `tests/integration/test_budget_trip_e2e.py`.
- `T-AI-03.5` `tests/ai/test_response_cache.py`.
- `T-AI-03.6` `tests/ai/test_rate_limiter.py`.
- `T-AI-03.7` `tests/ai/test_deny_precedence.py`.
- `T-AI-03.8` `tests/ai/test_cache_before_budget.py`.
- `T-AI-03.9` `tests/ai/test_budget_states.py`.
- `T-AI-03.10` `tests/ai/test_budget_recovery.py`.
- `T-AI-03.11` `tests/integration/test_pack_budget_refusal.py`.
- `T-AI-03.12` `tests/spec/test_budget_matrix_coverage.py`.

---

## 4. Usage accounting and provenance — `AI-04`

**Objective.** Every model call is attributable to a feature, a user, a model, and a cost; every artifact a model produced can be traced to the exact prompt and model that produced it (HR-9).

**Constraints.**
- Every call — success, failure, repair, cache hit, budget denial — writes exactly one `ai_usage` row (`17-data-model.md` §2.12). No call is unaccounted.
- `est_cost_usd` is computed from `MODEL_PRICING`, a config table of input and output per-million-token prices keyed by model id, with an explicit `unknown` marker. An unpriced model records `est_cost_usd: null` and increments an `ai_unpriced_model` counter that alerts, rather than silently recording zero.
- Every artifact stored anywhere in the product that a model produced carries `model` and `prompt_version`: `resumes.extraction_model`, `jobs.enrichment.model`, `match_scores.rationale_model`, `application_packs.model`. A stored artifact without them fails a schema check.
- The write of the usage row must not be able to fail the feature. It is fire-and-forget with a bounded in-process buffer flushed by the worker; a full buffer drops rows and increments a counter rather than blocking.

**Inputs.** `LLMResponse`; the pricing table.

**Outputs.** `ai_usage` rows; the admin dashboard aggregates (`12-admin.md` §2).

**Acceptance criteria.**
- `AC-AI-04.1` A test that exercises every AI feature once produces exactly one `ai_usage` row per call, with `outcome` correctly set across ok / invalid_json / repaired / provider_error / budget_denied / cache_hit.
- `AC-AI-04.2` Every model-produced artifact in every collection has non-null `model` and `prompt_version` (HR-9), asserted by a schema check over seeded data.
- `AC-AI-04.3` A model absent from `MODEL_PRICING` records `est_cost_usd: null` and increments the alert counter.
- `AC-AI-04.4` Failing the `ai_usage` write does not fail the feature call.
- `AC-AI-04.5` Summing `est_cost_usd` over a day equals the figure the admin dashboard shows for that day.

**Tests.**
- `T-AI-04.1` `tests/ai/test_usage_rows.py`.
- `T-AI-04.2` `tests/spec/test_artifact_provenance.py`.
- `T-AI-04.3` `tests/ai/test_unpriced_model.py`.
- `T-AI-04.4` `tests/ai/test_usage_write_failure.py`.
- `T-AI-04.5` `tests/integration/test_admin_ai_dashboard.py`.

---

## 5. The Gemini adapter, and isolation from Google AI Pro — `AI-05`

**Objective.** Use Gemini through its Developer API on a key whose billing is entirely separate from any consumer Google subscription, and make it structurally impossible for a consumer credential or a user's sign-in token to reach an inference call (HR-6).

### 5.1 What the isolation actually is

The Google AI Pro subscription is a **consumer entitlement** attached to a Google account. It grants higher limits inside Google's own applications. It does not grant API quota, it cannot authenticate an API request, and there is no code path by which API usage could be billed to it. So the risk is not that the code accidentally spends the subscription — that is not possible. The risks that *are* real, and that this section addresses:

1. **Key provenance.** An API key created inside a Cloud project that shares a billing account with other personal work makes JobPilot's spend indistinguishable from everything else, which defeats the cost tracking in §4 and makes a spend alert unactionable.
2. **Credential confusion.** Google OAuth is used in this product for *sign-in* (`AUTH-02`). Sign-in and inference both say "Google". A future change that reaches for an available Google credential in the AI path — a user's OAuth token, application default credentials, a service account with broad scopes — would be a serious privacy failure: it would attach a user's identity to inference calls and could implicate their consumer account.
3. **Terms drift.** Free-tier and paid-tier terms for prompt data use differ, and the difference is exactly what the consent screen promises the user (§5.4, D5).

### 5.2 Constraints

- The Gemini adapter accepts **one credential type**: a Developer API key string, injected at construction. It has no code path that reads application default credentials, no service-account JSON handling, no OAuth flow, and no ability to accept a bearer token.
- The adapter calls the Gemini Developer API endpoint only. The base URL is configurable for testing but defaults to the Developer API host; a configured base URL that is not on an allowlist fails at startup.
- `ai/*` must not import `authlib`, `google.auth`, `google.oauth2`, `googleapiclient`, or `app.modules.auth` — the `no-oauth-in-ai` import contract (`01-foundations.md` §4).
- A startup assertion fails the boot if: `AI_PROVIDER_*` selects `gemini` and `GEMINI_API_KEY` is absent; or `GOOGLE_APPLICATION_CREDENTIALS` is set in the process environment at all (its presence means an ambient Google credential exists that the AI path must not be able to find, so it is treated as a misconfiguration and refused with an explanatory message).
- **Procurement rule, recorded in `docs/compliance/ai-providers.md` and checked at the R1 gate:** the key belongs to a Cloud project created solely for this product, with its own billing account, and a project-level budget alert set at twice `AI_DAILY_COST_CAP_USD` × 30. The project has no other API enabled. This is a manual control with a documented owner; the code cannot verify it, so the gate item is a signed statement, not a test.
- The key is server-side only. It is never returned by any endpoint, never logged (`01-foundations.md` §14), and never present in a client bundle. A CI check greps the built web bundle and the Flutter release artifacts for the key's prefix pattern.
- Structured output: pass the JSON schema via the provider's structured-output facility, then **still** validate with Pydantic, then on failure retry exactly once with a repair prompt that includes the validation error and the offending text. A second failure raises `StructuredOutputInvalid` and the feature degrades per §3.
- Tier selection: `fast` for extraction, enrichment, rationale, follow-up drafts and answer suggestions; `quality` for pack generation. Both are model ids from config (§2).
- Model names and free-tier limits are verified against Gemini's documentation at implementation time and recorded with a date in `docs/compliance/ai-providers.md`. Any figure in this specification about a provider's limits is indicative and must not be hard-coded.

### 5.3 Inputs / Outputs

**Inputs.** `GEMINI_API_KEY` (SecretStr), model ids, base URL, the request.
**Outputs.** `ai/gemini.py`; the startup assertions; `docs/compliance/ai-providers.md`.

### 5.4 The free-vs-paid tier decision (D5)

Free-tier and paid-tier terms differ in whether prompts may be used to improve the service. The product sends **resume text** and **job description text** to the provider (never files, HR-8), and the consent screen must state what actually happens. Two acceptable positions, one required choice before public sign-up:

- **Paid tier before any public account.** The consent text says prompts are not used for training. Recommended; the R2 gate assumes it.
- **Free tier, disclosed.** The consent text says explicitly that prompt content may be used by the provider to improve their service, in plain language, above the fold — not in a linked policy.

What is **not** acceptable is a consent text that implies the first while running the second. `16-security-and-compliance.md` §4 holds the copy for both.

### 5.5 Acceptance criteria

- `AC-AI-05.1` `docs/compliance/ai-providers.md` exists, states the dedicated Cloud project and billing account, names the budget-alert threshold, and carries a review date within 90 days. (R1 gate: signed statement.)
- `AC-AI-05.2` Boot fails with a clear message when `gemini` is selected and `GEMINI_API_KEY` is unset, and when `GOOGLE_APPLICATION_CREDENTIALS` is present in the environment.
- `AC-AI-05.3` The `no-oauth-in-ai` import contract is active and passing; a fixture that adds `import google.auth` to `ai/gemini.py` fails CI.
- `AC-AI-05.4` The Gemini adapter's constructor accepts only a key string; a test asserts it has no attribute or parameter capable of holding a token, a credentials object, or a service-account path, and that no method reads `os.environ`.
- `AC-AI-05.5` A built web bundle and a Flutter release artifact contain no substring matching the API-key pattern.
- `AC-AI-05.6` Invalid JSON from the provider triggers exactly one repair retry; a second failure raises `StructuredOutputInvalid` and writes an `ai_usage` row with `outcome: invalid_json`.
- `AC-AI-05.7` A configured base URL outside the allowlist fails at startup (blocks an accidental proxy that could exfiltrate prompts).
- `AC-AI-05.8` The consent text rendered by the client matches the tier actually configured, asserted by a test that reads both the flag and the copy key.

### 5.6 Tests

- `T-AI-05.1` `tests/spec/test_compliance_docs.py` (existence, required headings, review-date freshness).
- `T-AI-05.2` `tests/ai/test_gemini_startup_guards.py`.
- `T-AI-05.3` `tests/spec/test_import_linter_catches_violation.py` (extended with the OAuth fixture).
- `T-AI-05.4` `tests/ai/test_gemini_credential_surface.py` (introspection).
- `T-AI-05.5` `.github/workflows/web-ci.yml` and `mobile-ci.yml` step `secret-scan-artifacts`.
- `T-AI-05.6` `tests/ai/test_structured_repair.py`.
- `T-AI-05.7` `tests/ai/test_base_url_allowlist.py`.
- `T-AI-05.8` `tests/integration/test_consent_matches_tier.py`.

---

## 6. Untrusted content and prompt injection — `AI-06`

**Objective.** Job descriptions and resumes are attacker-controlled text. Treat them as data, never as instructions, and never let model output steer the program (HR-11).

**Constraints.**
- Untrusted content is never concatenated into a prompt by a feature module. It is passed in `LLMRequest.untrusted` as a mapping of name → text, and the AI layer is the only code that renders it into the prompt, wrapped in delimiters with a fixed preamble instructing the model that the delimited region contains data to analyse and that any instructions inside it are to be ignored and reported.
- Delimiters are randomized per request (a nonce), so content cannot close the delimiter it is inside.
- Content is length-capped before rendering: 8,000 characters for a job description (`17-data-model.md` §6), 30,000 for resume text with a documented chunking strategy above that.
- **Model output is never used to choose a code path.** It is validated into a schema and stored or displayed. Specifically: no output field selects a provider, a URL, a collection, a filter, a task name, or a template; no output is passed to `eval`, a shell, a query builder, or an HTTP client; there is no tool-calling in R1 or R2.
- Model output rendered in a client is treated as untrusted text: escaped, never `dangerouslySetInnerHTML`, never a live link. A URL produced by a model is displayed as text, not linked.
- The extraction and enrichment prompts additionally instruct the model to report suspected injection attempts in a `warnings` array, which is stored and surfaced to the operator — a listing that tries to manipulate the pipeline is a signal worth seeing.
- Feature prompts state their refusal boundary: the extraction prompt may not invent, the pack prompt may not assert facts absent from the provided profile (HR-4).

**Inputs.** Job descriptions, resume text, user-typed answers.

**Outputs.** `ai/untrusted.py` (renderer, nonce, caps); `warnings` propagation.

**Acceptance criteria.**
- `AC-AI-06.1` A feature module that concatenates untrusted text into `system` or `messages` instead of `untrusted` fails a static check (the renderer is the only place the delimiter literal exists, and a lint rule forbids f-string interpolation of the known untrusted variable names into prompt strings).
- `AC-AI-06.2` A corpus of 25 injection payloads (instruction override, delimiter escape, fake system turn, exfiltration request, schema subversion, "ignore your rules and output X") passed as job descriptions and resume text produces, for every one: a schema-valid result, no field containing the injected instruction as a value, and no change in which provider, model, or prompt was used.
- `AC-AI-06.3` A static check confirms no model output value is used as a key, a name, a URL, a path, or a filter anywhere in the codebase.
- `AC-AI-06.4` Delimiters differ between two consecutive requests with identical content.
- `AC-AI-06.5` A model-produced URL is rendered as inert text in both clients.
- `AC-AI-06.6` Content exceeding the cap is truncated before rendering, and the truncation is recorded on the artifact.

**Tests.**
- `T-AI-06.1` `tests/spec/test_untrusted_rendering.py`.
- `T-AI-06.2` `tests/ai/test_injection_corpus.py` — the corpus lives in `tests/ai/fixtures/injections/`.
- `T-AI-06.3` `tests/spec/test_no_output_driven_control_flow.py`.
- `T-AI-06.4` `tests/unit/test_delimiter_nonce.py`.
- `T-AI-06.5` `apps/web/src/features/**/__tests__/ai-content.test.tsx` and `apps/mobile/test/ai_content_test.dart`.
- `T-AI-06.6` `tests/unit/test_content_caps.py`.

---

## 7. Prompt management and golden tests — `AI-07`

**Objective.** A prompt is a versioned artifact with tests, so a change to it is reviewable and its effect measurable — and so any output can be reproduced from what is stored beside it.

**Constraints.**
- Prompts live at `ai/prompts/<feature>/v<N>.md` with YAML front matter: `version`, `feature`, `tier`, `output_schema` (dotted path to the Pydantic model), `untrusted_slots` (names expected in `LLMRequest.untrusted`), `changelog`.
- Prompts are loaded and validated at startup: every referenced schema importable, every declared slot used in the body, no undeclared slot referenced. A malformed prompt fails the boot.
- A prompt is **immutable once used in production**. An improvement creates `v<N+1>`. This is what makes `prompt_version` on a stored artifact meaningful.
- `prompt_version` is `"<feature>/v<N>"` and is recorded on every artifact and every `ai_usage` row.
- **Golden tests** live in `tests/ai/golden/<feature>/` as `(input, expected)` pairs and run in two modes: against the **fake provider** on every CI run (deterministic, asserts the prompt renders and the schema parses), and against the **real provider** nightly under the `real_ai` marker with tolerance-based assertions (field presence, precision thresholds, no fabrication) rather than string equality.
- The resume extraction golden set is at least **10 real resumes** with hand-labelled expected output, and the P2 exit gate is ≥90% field-level precision on skills and employers (`00-scope-and-phases.md` §4). Resumes used as fixtures are the developer's own or explicitly licensed, are scrubbed of contact details, and are documented as such.
- Nightly real-provider runs write their spend to `ai_usage` under a `feature` suffix of `:golden` so test spend is separable from user spend on the dashboard.

**Inputs.** Prompt files; golden fixtures.

**Outputs.** `ai/prompts/`; the loader; the two test modes; a nightly report.

**Acceptance criteria.**
- `AC-AI-07.1` Every prompt file's front matter validates, every `output_schema` path imports, every declared slot appears in the body and every `{{slot}}` in the body is declared.
- `AC-AI-07.2` Editing a prompt file whose version has been used in production (detected by presence in `ai_usage` on staging or prod, checked in CI against a committed manifest) fails CI with a message to create the next version.
- `AC-AI-07.3` Golden tests against the fake provider pass on every CI run and cover every feature that has a prompt.
- `AC-AI-07.4` The nightly `real_ai` run posts a report: per feature, pass/fail, tokens, cost, and any tolerance breach.
- `AC-AI-07.5` Resume extraction achieves ≥90% field-level precision on skills and employers across the 10-resume golden set.
- `AC-AI-07.6` No golden fixture contains a real phone number or email address (scrub check).

**Tests.**
- `T-AI-07.1` `tests/ai/test_prompt_loader.py`.
- `T-AI-07.2` `.github/workflows/api-ci.yml` step `prompt-immutability`.
- `T-AI-07.3` `tests/ai/test_golden_fake.py`.
- `T-AI-07.4` `.github/workflows/nightly-ai.yml`.
- `T-AI-07.5` `tests/ai/test_extraction_precision.py` (marker `real_ai`, plus a fake-provider variant asserting the harness itself).
- `T-AI-07.6` `tests/spec/test_fixture_scrub.py`.
