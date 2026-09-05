# JobPilot — Agent Build Specification

**Spec version:** 2.1 (supersedes the combined BRD/Architecture v1.0 as the *build* contract)
**Date:** 2026-09-05
**Changes since 2.0:** five hardening passes — see §6
**Owner:** Sulthan Abdullah — solo developer, product owner
**Source of truth for:** what to build, in what order, and how to prove it is done

---

## 0. What this is

The v1.0 document was a BRD plus an architecture guide: it explained *what* and *why*, at length, for a human reader. This is the same product restated as a **build contract for coding agents and for you**. Every section in every file carries six fixed parts:

| Part | Meaning |
|---|---|
| **Objective** | The one outcome this section exists to produce. One sentence. |
| **Constraints** | What the implementation may not do. Non-negotiable unless a hard rule below is changed. |
| **Inputs** | Data, config, and upstream artifacts the section consumes, with types. |
| **Outputs** | Data, config, endpoints, and artifacts the section produces, with types. |
| **Acceptance criteria** | Numbered, observable statements. Each is true or false by inspection or by running something. No "should be fast". |
| **Tests** | The named test that proves each acceptance criterion, with its level and location. |

An agent given the right **bundle** should be able to implement a requirement without reading the rest. v2.0 claimed one module file plus two shared ones was always that bundle; v2.1 computes it instead — `make bundle REQ=<id>` returns the exact file list and section anchors from the dependency manifest (`18-dependency-closure.md` §6), and no R1 requirement needs more than five files.

### How to use this with an agent

1. Pick the next requirement from `BUILD-ORDER.md` — it is generated from the dependency graph, so "what next" is a file rather than a judgement.
2. Run `make bundle REQ=<id>` and give the agent exactly those files.
3. Tell it the track (`R1`, `R2`, `R3`) and the section's declared **Status** (§0, below), and to skip sections marked for later tracks.
4. Require it to output the tests named in the **Tests** part alongside the implementation, in the same commit.
5. Reject any commit where an acceptance criterion has no corresponding passing test, or where the section's declared status does not match what was built. The AC/test ID pairs are the review checklist.

### ID conventions

| Prefix | Meaning | Example |
|---|---|---|
| `AUTH-01`, `PROF-03`, … | Functional requirement, carried forward unchanged from BRD v1.0 §5 | `MATCH-02` |
| `HR-n` | Hard rule — a global invariant (§2 below) | `HR-4` |
| `AC-<REQ>.<n>` | Acceptance criterion for a requirement | `AC-MATCH-02.3` |
| `T-<REQ>.<n>` | Test proving that criterion | `T-MATCH-02.3` |
| `INV-<MOD>-<n>` | Module-local invariant, asserted in code | `INV-TRACK-1` |
| `D<n>` | Open decision you must settle (see `00-scope-and-phases.md` §5) | `D3` |
| `INV-<AREA>-<n>` | A named invariant asserted by a test and by the gate | `INV-FEED-1` |
| `F<n>` / `V<n>` | A consistency finding / a closure violation, recorded in `CONSISTENCY-REPORT-v2.1.md` | `F7`, `V1` |

**Status.** Every section also declares one of four implementation states (`01-foundations.md` §15): `built`, `built-off` (implemented, flag off in production), `stub-501` (route reserved, no implementation), `absent` (does not exist). The registry is checked against the flag defaults, the OpenAPI surface and the test suite, so a declared status that is untrue fails the build. There is deliberately no "partially implemented".

Requirement IDs are stable. If a requirement is dropped, its ID is retired, never reused.

**Range and list notation.** A **Tests** line may cover several criteria at once: `T-AUTH-05.1`–`.5` means the five tests `.1` through `.5`, and `T-FOUND-05.3`/`.5` means exactly those two. `(shared)` after a test path means the test is defined in another file's **Tests** list and is reused here rather than duplicated. The traceability gate (`01-foundations.md` §6) expands both forms and resolves `(shared)` across the whole specification, so every criterion must still resolve to a real test.

---

## 1. Two calls I made, flagged for your review

You asked me to split scope and to keep AI usage off your Google AI Pro plan. Both required judgement calls that I made rather than leaving blank. Overrule either and only the files named change.

### Call 1 — What is in the core release

**Decision:** the core release (`R1`) is the value loop for **one persona (P1, active job seeker) on web and Android**, with **three connectors**, **deterministic scoring only in production**, and **no data-export, no saved searches, no digest, no stats, no OCR, no multiple resume versions**. Twenty-two "Should" items from BRD §5 moved to stabilization (`R2`) and eight to later (`R3`).

**Why:** the R1 exit test is a single sentence — a new user signs up, uploads a resume, corrects the profile, sees fifty scored jobs, shortlists five, generates and approves one pack, marks it applied, and gets a follow-up reminder. Every item I cut can be removed from that sentence without changing it. Every item I kept cannot.

**The one place this is contentious:** `MATCH-02` (LLM match rationale) is a Must in BRD v1.0. I kept the code in R1 but ship it **feature-flagged off in production** until the AI budget accounting in `05-ai-layer.md` has run for two weeks. The deterministic breakdown alone satisfies "explainable" — that is what the UI renders and what the acceptance criteria test. The rationale paragraph is narrative on top. If you disagree, flip `FLAG_LLM_RATIONALE_ENABLED=true` at R1 and move `AC-MATCH-02.6`/`AC-MATCH-02.7` from R2 to R1 in `08-matching.md`; nothing else changes.

**Files affected:** `00-scope-and-phases.md` (the full cut list, with a reason per item), and a `Track:` line on every section elsewhere.

### Call 2 — Where the AI provider boundary sits, and how billing is kept separate

**Decision:** four layers, defined in `05-ai-layer.md`:

1. **Contract** — `ai/base.py` holds `LLMProvider` and `EmbeddingProvider` protocols plus `LLMRequest`/`LLMResponse`. No provider SDK type appears in a signature. No `google.genai` import exists outside `ai/gemini.py`.
2. **Selection** — `ai/registry.py` maps a *feature name* to a provider instance from config. Feature modules call `get_llm("resume_extract")`, never a concrete adapter. `import-linter` forbids `modules/* -> ai.gemini`.
3. **Credentials** — adapters receive their credential by constructor injection from the registry; an adapter never reads `os.environ`. The Gemini adapter accepts **only** a Gemini Developer API key (`GEMINI_API_KEY`), calls `generativelanguage.googleapis.com`, and is hard-wired to refuse any OAuth or user-account credential. A startup assertion fails the boot if a Google *user* credential is reachable from the AI path.
4. **Accounting** — every call writes an `ai_usage` row with `feature`, token counts, and a cost computed from a `MODEL_PRICING` config table. Per-feature and global daily caps live in Redis counters; exceeding a cap raises `AIBudgetExceeded`, which each feature handles by degrading, never by failing the user's request.

**On the Google AI Pro question specifically:** your Pro subscription is a consumer entitlement for Google's own apps. It grants no API quota and cannot be used to authenticate an API call. The isolation is therefore not a code trick — it is a procurement rule plus three enforcement points: the API key must belong to a Cloud project created solely for JobPilot with its own billing account (`AC-AI-05.1`); the AI path must contain no Google user-OAuth credential, which is asserted at boot and by an import contract (`AC-AI-05.2`, `AC-AI-05.3`); and Google OAuth for *sign-in* lives in `modules/auth` and is forbidden by import contract from reaching `ai/` (`AC-AI-05.4`). Sign-in and inference share the word "Google" and nothing else.

**Files affected:** `05-ai-layer.md` (whole file), `01-foundations.md` §4 (import contracts), `16-security-and-compliance.md` §3.

---

## 2. Hard rules

These override every other statement in this specification, including anything an agent infers from a code sample. A change to a hard rule is a product decision, not an implementation decision.

| # | Rule | Enforced by |
|---|---|---|
| **HR-1** | Nothing is submitted to a third-party site without an explicit per-application user approval action. No bulk apply, no unattended apply, no headless browser submission, ever — not behind a flag. | `09-apply.md` §5; `AC-APPLY-05.4`; absence of any HTTP client capable of posting to `apply_url` in `modules/apply` |
| **HR-2** | No connector may fetch from a source whose terms prohibit automated access. No HTML scraper for LinkedIn, Naukri, Indeed, Glassdoor, Instahyre, or Google Jobs SERP exists in the codebase. The connector framework ships **no HTML-parsing base class**. | `06-connectors.md` §2; `AC-CONN-02.4`; CI grep gate `T-CONN-02.4` |
| **HR-3** | An LLM never changes a match number. Rationale text is display-only and is stored in a field the scorer cannot read. | `08-matching.md` §2; `AC-MATCH-03.4` |
| **HR-4** | Generated application content may assert only facts traceable to a **confirmed** profile field or to the job posting. Untraceable claims are flagged and blocked from approval until the user edits or explicitly overrides. | `09-apply.md` §4; `AC-APPLY-04.1`–`.5` |
| **HR-5** | No provider SDK type crosses the `ai/` boundary. Feature modules import `ai` only through its public API. | `05-ai-layer.md` §1; `AC-AI-01.3`; import contract |
| **HR-6** | Gemini access uses a server-side Developer API key belonging to a dedicated Cloud project with its own billing account. No consumer Google account credential, no Google AI Pro entitlement, and no user OAuth token appears anywhere in the AI path. | `05-ai-layer.md` §5; `AC-AI-05.1`–`.4` |
| **HR-7** | Only profile fields with `confirmed: true` feed application pack generation. Unconfirmed AI extractions are excluded from prompts entirely. | `09-apply.md` §3; `AC-APPLY-02.2` |
| **HR-8** | Resume and document **file bytes** never leave our infrastructure. Only extracted text is sent to an AI provider. | `04-resume-pipeline.md` §3; `AC-RES-05.3` |
| **HR-9** | Every AI-generated artifact is labelled as AI-generated in the UI and stored with `model` and `prompt_version`. | `05-ai-layer.md` §4; `13-web-client.md` §5; `AC-AI-04.2` |
| **HR-10** | All stored timestamps are UTC. Local time exists only at render and at reminder-scheduling boundaries, derived from `user.tz`. | `01-foundations.md` §3; `AC-FOUND-03.1` |
| **HR-11** | Job description text and resume text are untrusted input to any prompt. They are delimited, the model is instructed to ignore instructions inside them, and no model output is ever used to select a code path, call a tool, or build a query. | `05-ai-layer.md` §6; `AC-AI-06.1`–`.3` |
| **HR-12** | Every module boundary in `01-foundations.md` §4 is enforced by `import-linter` in CI, not by review. A violating PR cannot merge. | `AC-FOUND-04.1` |

---

## 3. File index

Read in this order for a cold start. Track column shows where the bulk of the file's work lands.

| # | File | Covers | Requirements | Track |
|---|---|---|---|---|
| — | `README.md` | This file: contract format, hard rules, flagged decisions | — | — |
| 00 | `00-scope-and-phases.md` | R1/R2/R3 track definitions, full cut list with reasons, phase order inside R1, gates, open decisions | — | all |
| 01 | `01-foundations.md` | Repo layout, module anatomy, import contracts, config, errors, IDs, time, pagination, idempotency, SSE, events, task rules, logging | `FOUND-01`…`FOUND-14` | R1 |
| 02 | `02-auth-and-account.md` | Registration, login, Google OIDC, tokens, verification, reset, sessions, deletion, export, consent, the authorization model | `AUTH-01`–`10` | R1/R2 |
| 03 | `03-profile.md` | Profile schema, confidence provenance, preferences, skill canonicalization, completeness, audit | `PROF-01`–`07` | R1/R2/R3 |
| 04 | `04-resume-pipeline.md` | Upload, text extraction, OCR, structured extraction, review/apply, re-analysis, quality feedback | `RES-01`–`07` | R1/R2 |
| 05 | `05-ai-layer.md` | Provider protocols, registry, Gemini adapter, billing isolation, budgets, caching, prompts, injection defence | `AI-01`–`07` | R1 |
| 06 | `06-connectors.md` | `BaseConnector` contract, registry, compliance records, circuit breaker, the v1 connector set, adding a connector | `CONN-01`–`07` | R1/R2 |
| 07 | `07-ingestion-and-jobs.md` | Canonical `Job`, normalization, dedup, skill extraction, staleness, search, hide/report | `JOB-01`–`10` | R1/R2 |
| 08 | `08-matching.md` | Weights `w1`, candidate-set selection, embeddings, explain contract, thresholds, feedback, gap analysis | `MATCH-01`–`08` | R1/R2/R3 |
| 09 | `09-apply.md` | Answer Bank, pack generation, anti-fabrication, approval gates, assisted apply, audit, extension | `APPLY-01`–`08` | R1/R2/R3 |
| 10 | `10-tracker.md` | Application entity, state machine, views, notes/contacts/docs/interviews, timeline, manual entry, stats | `TRACK-01`–`07` | R1/R2 |
| 11 | `11-notifications.md` | Reminder types, scheduling, dispatch, channels, idempotency, quiet hours, digest | `NOTIF-01`–`05` | R1/R2 |
| 12 | `12-admin.md` | Connector dashboard, AI usage dashboard, feature flags, alias management, flagged queue, role gating | `ADMIN-01`–`06` | R1/R2 |
| 13 | `13-web-client.md` | React + TS structure, screens, state, SSE, auth handling, AI labelling, accessibility | `WEB-*` | R1/R2 |
| 14 | `14-mobile-client.md` | Flutter structure, screens, push, deep links, flavors, offline, permissions UX | `MOB-*` | R1/R2 |
| 15 | `15-infra-and-ops.md` | Docker, environments, CI/CD, observability, backups, runbooks, cost ceiling | `OPS-*` | R1/R2 |
| 16 | `16-security-and-compliance.md` | Security controls, connector compliance process, DPDP/GDPR, consent, retention enforcement | `SEC-*` | R1/R2 |
| 17 | `17-data-model.md` | Every collection, field, index, and retention rule; the field and enum registries | `DATA-01`…`DATA-07` | R1 |
| 18 | `18-dependency-closure.md` | The dependency manifest, module graph, track and phase closure checks, build order, agent handoff bundles | `DEP-01`…`DEP-06` | R1 |

**Machine-readable companions**, all committed and all checked in CI: `dependencies.yaml` (the graph), `ai-budget.yaml` (the degradation matrix), `fields.yaml` and `enums.yaml` (generated from file 17), `status.yaml` (implementation states), `BUILD-ORDER.md` (generated), `SPEC-METADATA.json` (the whole specification as data), and `CONSISTENCY-REPORT-v2.1.md` (the first run of the checks).

`docs/adr/`, `docs/runbooks/`, and `docs/compliance/` remain as in v1.0 §9.1 and are written as the work lands; `00-scope-and-phases.md` §4 says which phase produces which.

---

## 4. What did not change from v1.0

Restated so no agent re-litigates a settled decision:

- **Stack.** React + TypeScript (Vite) web; Flutter mobile; FastAPI **modular monolith** in Python 3.12; MongoDB Atlas with Beanie; Cloudflare R2 for files; Redis + ARQ for queue, cache, and rate limits; Docker for everything, one image with `api` and `worker` entrypoints.
- **Architecture posture.** ADR-001 through ADR-010 from v1.0 §8.2 stand. Connectors are plugins. AI is behind protocols. Match scores are precomputed and stored. Scoring is deterministic and versioned.
- **Product posture.** Assisted before automated. Explainable before clever. Replaceable infrastructure. Connectors isolated from core.
- **Non-goals.** Unattended auto-apply, prohibited scraping, recruiter/employer features, billing, interview prep, multi-language UI.
- **Canonical schemas.** Appendices A–E of v1.0 are carried into `17-data-model.md` (Job, collections), `04-resume-pipeline.md` (`ProfileExtraction`), `09-apply.md` (`ApplicationPack`), and `15-infra-and-ops.md` (env vars), with the R2/R3 fields marked so R1 does not build them.

## 5. What the name is not

"JobPilot" is still a placeholder (v1.0 D1). Nothing in the code may hard-code it as a user-visible string: product name comes from `PRODUCT_NAME` in config, used by email templates, the consent screen, and store listings. Package names, the Mongo database name, and the JWT issuer may use `jobpilot` as an internal identifier. See `AC-FOUND-02.4`.


---

## 6. What changed in v2.1

Five hardening passes, in response to a review of v2.0 that found it a good architecture document and a not-quite-sufficient agent contract. None of it is structural surgery: the section format, the tracks, the hard rules and the requirement IDs are unchanged.

### 6.1 R1 dependency closure — new file `18-dependency-closure.md`

v2.0 declared module boundaries but never declared the *graph*: which requirement needs which before it can be built. `dependencies.yaml` now carries 149 entries with `requires`, phase, module, events and collections, and two checks run in CI. **Track closure** (no R1 requirement transitively needs R2 or R3 work) passed on the first run. **Phase closure** (every dependency sits in an earlier or equal phase) found four violations, all now fixed — most consequentially that P1's auth flows needed email that only existed in P6, which is why `FOUND-16` now owns email transport as infrastructure. `BUILD-ORDER.md` is generated from the graph, and `make bundle REQ=<id>` replaces the guess about which files an agent needs.

### 6.2 The AI budget and degradation matrix — `05-ai-layer.md` §3, rewritten

v2.0 listed a degradation per feature in prose. v2.1 makes it normative and machine-readable: three counters with a **fixed deny precedence** (user → feature → global, first failure wins, recorded in `ai_usage.deny_reason`), three budget states with thresholds, a pessimistic pre-call estimate, and a ten-row matrix giving each feature its degradation, its user-visible state, what is recorded, and how it recovers. `ai-budget.yaml` parametrizes the tests, so a feature added without a matrix row fails rather than defaulting to an error. Three invariants are now separately testable: no silent success, no data loss, no permanent degradation.

### 6.3 The "50 scored jobs" invariant — `08-matching.md` §8, new

The exit sentence could be read three ways. **Scored**, **eligible** and **shown** are now distinct defined terms, and the sentence means *eligible at the default threshold*. `INV-FEED-1` fixes the gate against a committed reference profile and the seeded corpus; `INV-FEED-2` requires ≥99% scoring coverage, so a thin feed caused by a scoring backlog is a measurable defect rather than an excuse. The section also specifies what v2.0 never did: the ordered behaviour when fifty do not exist, including the two empty states that mean opposite things — *still scoring* (normal for the first minutes after onboarding) and *nothing matches* — and a `widen` block computed from stored rows with no rescore and no AI call. It states explicitly what it is not: a per-user SLA.

### 6.4 The cross-document data-model check — `17-data-model.md` §7, new

Ten findings, six of them real inconsistencies, all recorded with resolutions in `CONSISTENCY-REPORT-v2.1.md`. The two that would have cost the most: `resumes` carried two lifecycle enums whose members differed by name (`extracting` vs `extracting_text`), and `jobs.revision` was asserted by two acceptance criteria but never declared. `DATA-07` replaces the one-off check with a standing one — `fields.yaml` and `enums.yaml` generated from this file, and CI failing on a field reference that does not resolve or an enum member used but unregistered. Enum ownership moved out of the module files, which is where the drift came from.

### 6.5 Implemented-disabled vs not-implemented — `01-foundations.md` §15, new

Four states with obligations attached, replacing v2.0's single gate line. `built-off` now means something specific and demanding: criteria pass with the flag forced on, enabling requires no code change or migration, the flag is in the admin list with its blast radius, and the UI is complete with the feature off. `absent` means no route, no flag, no dead code, no skipped test — with the one carve-out that `[R2]`-marked model fields may exist ahead of the feature, because the additive-schema rule requires it. `MATCH-02b` is the only `built-off` section in R1.

### 6.6 What this did not change

The six-part section contract, the twelve hard rules, the three tracks, the requirement IDs, the phase count, and every architectural decision from v1.0's ADR set. Two requirements moved phase (`APPLY-09` P5 → P6) and one dependency direction was reversed (`NOTIF-04` now depends on `JOB-07`, not the reverse). No requirement changed track.
