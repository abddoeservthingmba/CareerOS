# 01 — Foundations

**Module:** `apps/api/app/core`, `apps/api/app/shared`, repo root
**Track:** R1 (all sections)
**Depends on:** nothing
**Depended on by:** every module
**Requirements:** `FOUND-01` … `FOUND-14`
**Public API:** `app.core.config`, `app.core.errors`, `app.core.events`, `app.core.deps`, `app.core.logging`, `app.shared.*`

Read this file and `17-data-model.md` before implementing any other module. Everything here is a convention that, once broken in one module, is broken everywhere.

---

## 1. Repository layout — `FOUND-01`

**Objective.** One monorepo where the API, worker, web, and mobile builds share generated contracts and a single CI pipeline, and where the location of any file is predictable from its purpose.

**Constraints.**
- One Git repository. Trunk-based: `main` = production, `develop` = staging.
- The API and worker are the **same Docker image** with different entrypoints (ADR-002). No second Dockerfile for the worker.
- No generated code is hand-edited. `packages/contracts` is written only by the `contracts` CI workflow.
- Python is managed by `uv`, pinned in `pyproject.toml`. Node by the version in `.nvmrc`. Flutter by the version in `.fvmrc`.
- No file outside `apps/api/app/connectors/` may name a job source. No file outside `apps/api/app/ai/` may name an AI provider (HR-5).

**Inputs.** None (this is the scaffold).

**Outputs.** The tree below, plus a root `Makefile`, `README.md`, `.env.example`, `.gitignore`, `.pre-commit-config.yaml`.

```
jobpilot/
├─ apps/
│  ├─ api/
│  │  ├─ app/
│  │  │  ├─ main.py              # app factory only: settings, middleware, routers, lifespan
│  │  │  ├─ worker.py            # ARQ WorkerSettings + cron table
│  │  │  ├─ core/                # config errors logging events deps security clock
│  │  │  ├─ shared/              # Money Location Cursor Page Ulid SkillName — value objects
│  │  │  ├─ modules/
│  │  │  │  ├─ auth/ profile/ resume/ jobs/ matching/ apply/ tracker/ notifications/ admin/
│  │  │  ├─ connectors/          # base.py registry.py <name>/
│  │  │  ├─ ai/                  # base.py registry.py fake.py gemini.py usage.py budget.py prompts/
│  │  │  └─ infra/               # mongo.py redis.py storage/ email/ push/
│  │  ├─ tests/
│  │  │  ├─ unit/ integration/ connectors/ ai/ contract/ spec/
│  │  ├─ pyproject.toml  uv.lock  Dockerfile  .importlinter  pytest.ini
│  ├─ web/                       # see 13-web-client.md
│  └─ mobile/                    # see 14-mobile-client.md
├─ packages/contracts/           # openapi.json + generated ts/ and dart/ clients — CI-written
├─ infra/
│  ├─ docker-compose.yml         # api worker mongo redis minio mailpit
│  ├─ docker-compose.prod.yml
│  ├─ Caddyfile
│  └─ scripts/                   # backup.sh restore.sh seed.py
├─ docs/
│  ├─ spec/                      # this specification, versioned with the code
│  ├─ adr/  runbooks/  compliance/
└─ .github/workflows/            # api-ci web-ci mobile-ci contracts deploy-staging deploy-prod mobile-release
```

**Acceptance criteria.**
- `AC-FOUND-01.1` `make up` from a clean clone with only `.env.example` copied to `.env` boots api, worker, mongo, redis, minio, mailpit, and `curl localhost:8000/readyz` returns 200 within 90 s.
- `AC-FOUND-01.2` `docker build apps/api` produces one image; `docker run <img> api` starts uvicorn and `docker run <img> worker` starts ARQ, both from the same digest.
- `AC-FOUND-01.3` A grep for any of `adzuna|jooble|remotive|arbeitnow|himalayas|greenhouse|lever|ashby` outside `app/connectors/`, `tests/connectors/`, `docs/`, and `connectors.yaml` returns nothing.
- `AC-FOUND-01.4` A grep for `google.genai|openai|anthropic|ollama` outside `app/ai/`, `tests/ai/`, and `docs/` returns nothing.
- `AC-FOUND-01.5` `packages/contracts` has no commits whose author is not the CI bot.

**Tests.**
- `T-FOUND-01.1` `tests/integration/test_compose_boot.py` — CI job that runs `make up`, polls `/readyz`, tears down.
- `T-FOUND-01.2` `.github/workflows/api-ci.yml` step `image-entrypoints`: builds once, runs both entrypoints with `--help`-equivalent smoke.
- `T-FOUND-01.3` / `T-FOUND-01.4` `tests/spec/test_layer_leaks.py` — ripgrep-based, allowlist in the test.
- `T-FOUND-01.5` `.github/workflows/contracts.yml` guard step.

---

## 2. Configuration — `FOUND-02`

**Objective.** One typed settings object, populated only from the environment, validated at startup, with a committed example that cannot drift from it.

**Constraints.**
- `pydantic-settings`; a single `Settings` class in `core/config.py`; instantiated once in the app factory and injected. No module reads `os.environ` — including AI adapters (HR-6) and connectors.
- Every secret is a `SecretStr`. `repr()` of `Settings` must not reveal one.
- Startup validation is **fail-fast**: a missing or malformed required variable aborts the boot with a message naming the variable. Never a default that silently disables a feature.
- Feature flags resolve as: DB override (`feature_flags` collection) → env (`FLAG_*`) → code default. Resolution is cached for 30 s.
- `PRODUCT_NAME` supplies every user-visible product string (`README.md` §5).

**Inputs.** Process environment; `.env` in local only; `feature_flags` collection.

**Outputs.** `Settings` instance; `get_flag(key: str) -> bool`; `.env.example` (full list in `15-infra-and-ops.md` §5).

**Acceptance criteria.**
- `AC-FOUND-02.1` Booting with a required variable unset exits non-zero within 5 s and stderr contains the variable name.
- `AC-FOUND-02.2` `repr(settings)` and any log line containing settings show `**********` for every `SecretStr`.
- `AC-FOUND-02.3` Every field on `Settings` appears in `.env.example`, and every key in `.env.example` maps to a field. No extras either way.
- `AC-FOUND-02.4` No user-visible string literal equals the product name anywhere in `apps/`; all such strings interpolate `PRODUCT_NAME`.
- `AC-FOUND-02.5` A DB override for a flag takes effect within 30 s without a restart, and removing it reverts to the env value.

**Tests.**
- `T-FOUND-02.1` `tests/unit/test_config_failfast.py`, parametrized over every required field.
- `T-FOUND-02.2` `tests/unit/test_config_secrets.py`.
- `T-FOUND-02.3` `tests/spec/test_env_example_parity.py`.
- `T-FOUND-02.4` `tests/spec/test_no_hardcoded_product_name.py`.
- `T-FOUND-02.5` `tests/integration/test_feature_flags.py` with a frozen clock.

---

## 3. Primitives: time, IDs, money, location, skills — `FOUND-03`

**Objective.** Shared value objects so that no two modules represent the same concept differently.

**Constraints.**
- **Time (HR-10).** Every stored datetime is timezone-aware UTC. Code never calls `datetime.now()` directly — it calls `core.clock.now()`, which tests freeze. Local time is derived from `user.tz` at exactly two places: reminder scheduling (`11-notifications.md` §2) and client rendering.
- **IDs.** ULID, stored as the 26-character canonical string in `_id`. Mongo `ObjectId` never leaves the persistence layer and never appears in an API response. IDs are generated in the application, not by the database, so a document can be referenced before it is written.
- **Money.** `Money{amount: int, currency: ISO4217, period: "hour"|"month"|"year"}`. `amount` is a **minor-unit integer** (paise, cents) — never a float, anywhere, ever. Cross-currency comparison goes through `shared/fx.py`, which reads a daily-cached rate table and returns a `ConvertedMoney` carrying the rate and its date, so a displayed comparison can be explained.
- **Location.** `Location{raw, city, region, country: ISO3166-1 alpha-2, remote_mode}`. `country` is the only field guaranteed non-null after normalization. `remote_mode ∈ {onsite, hybrid, remote, unknown}`.
- **Skills.** `SkillName` is a canonical lowercase slug. A raw string becomes one only via `profile.canonicalize()` (`03-profile.md` §4). Comparing raw skill strings anywhere is a defect.
- **Enums** are Python `StrEnum` and are exported to the OpenAPI schema; clients generate from them rather than redeclaring.

**Inputs.** Raw strings and numbers from connectors, resumes, and user input.

**Outputs.** `app/shared/{clock,ulid,money,fx,location,skills,enums}.py` and their OpenAPI representations.

**Acceptance criteria.**
- `AC-FOUND-03.1` A repo-wide search finds no call to `datetime.now`, `datetime.utcnow`, `time.time`, or `date.today` outside `core/clock.py`.
- `AC-FOUND-03.2` Every datetime persisted by any module round-trips as UTC-aware; a naive datetime raises on write.
- `AC-FOUND-03.3` No API response body contains a 24-hex-character string in an `_id` or `*_id` field.
- `AC-FOUND-03.4` `Money` rejects float construction; `Money(1000, "INR", "year") + Money(1000, "USD", "year")` raises `CurrencyMismatch` rather than converting implicitly.
- `AC-FOUND-03.5` `fx.convert()` returns the rate and its date alongside the amount, and raises `RateUnavailable` rather than falling back to 1.0.
- `AC-FOUND-03.6` ULIDs generated in one process sort chronologically alongside those from another (monotonic within a millisecond).

**Tests.**
- `T-FOUND-03.1` `tests/spec/test_no_direct_clock.py`.
- `T-FOUND-03.2` `tests/unit/test_time_utc.py` + a Beanie pre-save hook test.
- `T-FOUND-03.3` `tests/contract/test_no_objectid_in_responses.py`, driven by the OpenAPI schema and one live call per endpoint family.
- `T-FOUND-03.4` `tests/unit/test_money.py` (hypothesis: no float path, associativity within a currency).
- `T-FOUND-03.5` `tests/unit/test_fx.py`.
- `T-FOUND-03.6` `tests/unit/test_ulid.py`.

---

## 4. Module boundaries and import contracts — `FOUND-04`

**Objective.** Make the modular monolith actually modular, by machine, so that any module could be extracted into a service later without archaeology (HR-12).

**Constraints.**

Layers, innermost first. An arrow means "may import".

```
shared  ←  core  ←  infra(interfaces)  ←  { ai/base, connectors/base }  ←  modules/*  ←  main.py
```

Rules, each a named `import-linter` contract:

| Contract | Rule |
|---|---|
| `layers` | `main` → `modules` → `{connectors.base, ai, infra, core, shared}` → `core` → `shared`. No upward import. |
| `module-independence` | For every pair of modules, an import is allowed **only** of the other module's `__init__.py` public surface. Importing `modules.X.models`, `.repository`, `.router`, or `.tasks` from module `Y` is forbidden. |
| `no-concrete-ai` | `modules.*` and `connectors.*` must not import `ai.gemini`, `ai.openai`, `ai.anthropic`, `ai.ollama` (HR-5). |
| `ai-is-leaf` | `ai.*` must not import `modules.*` or `connectors.*`. |
| `connectors-are-leaf` | `connectors.*` must not import `modules.*` or `ai.*`. A connector normalizes; enrichment is the ingestion service's job. |
| `no-oauth-in-ai` | `ai.*` must not import `authlib`, `google.auth`, `google.oauth2`, or `modules.auth` (HR-6). |
| `infra-is-dumb` | `infra.*` must not import `modules.*`, `ai.*`, or `connectors.*`. |
| `no-http-in-domain` | `modules.*.service` must not import `fastapi` or `starlette`. Services take and return plain objects; HTTP lives in `router.py`. |

A module's `__init__.py` exports only: its service class, its DTOs from `schemas.py`, its published event types, and its exceptions. Never a Beanie document, never a repository.

Cross-module side effects go through in-process domain events (§9), never a direct call into another module's service, with one exception: a **read** through another module's public service method is allowed and preferred over duplicating a query.

**Inputs.** The `.importlinter` file.

**Outputs.** A CI check; a `docs/adr/ADR-001-modular-monolith.md` recording the rationale.

**Acceptance criteria.**
- `AC-FOUND-04.1` `lint-imports` exits 0 with all seven cross-cutting contracts active, one `module-independence-<name>` contract per module, and **zero** `ignore_imports` entries. A module's package root is importable by another module — §5's sanctioned read — and its internals are not (ADR-014). An exemption requires a new ADR.
- `AC-FOUND-04.2` Every `modules/*/` directory contains exactly the files in §5 below, and every one of them has an `__init__.py` whose `__all__` is non-empty and contains no name defined in `models.py` or `repository.py`.
- `AC-FOUND-04.3` A deliberately introduced cross-module model import fails CI (verified by a test that runs `lint-imports` against a fixture package containing the violation).
- `AC-FOUND-04.4` Every module has a `README.md` stating purpose, public API, events published, and events consumed.

**Tests.**
- `T-FOUND-04.1` `.github/workflows/api-ci.yml` step `import-linter`.
- `T-FOUND-04.2` `tests/spec/test_module_anatomy.py`.
- `T-FOUND-04.3` `tests/spec/test_import_linter_catches_violation.py`.
- `T-FOUND-04.4` `tests/spec/test_module_readmes.py`.

---

## 5. Module anatomy — `FOUND-05`

**Objective.** Identical internal shape for every module, so that finding the business rule for anything takes one guess.

**Constraints.**

```
modules/<name>/
├─ __init__.py      # public API. __all__ is the contract.
├─ router.py        # FastAPI routes. Thin: validate → call one service method → map to response.
├─ schemas.py       # Pydantic DTOs. The API contract. Separate from models, always.
├─ models.py        # Beanie documents. Persistence only. Never returned from a route.
├─ service.py       # Use cases. The ONLY place business rules live.
├─ repository.py    # Queries. Hides every Mongo detail, including index choices.
├─ tasks.py         # ARQ task functions. Thin wrappers that call service methods.
├─ events.py        # Event types this module publishes.
└─ README.md
```

- A route function is at most ~15 lines: dependency injection, one service call, one response mapping. No `if` on business state.
- A service method never touches `fastapi`, never builds a Mongo filter, and never calls an HTTP client directly (it calls an `infra` or `ai` interface).
- A repository method never contains a business rule. "Active jobs for a user" is a repository method; "should this user see this job" is a service rule.
- A task function receives **IDs only** — never a document, never a payload larger than a few hundred bytes (§10).
- Pure logic that needs no I/O (scoring, normalization, state transitions, fabrication checks) lives in its own module-local file (`scoring.py`, `normalize.py`, `state.py`, `fabrication.py`) with no imports from `infra`, `models`, or `repository`, so it is testable with plain dicts.

**Inputs.** N/A.

**Outputs.** A cookiecutter or `make new-module NAME=x` that emits the skeleton with a passing placeholder test.

**Acceptance criteria.**
- `AC-FOUND-05.1` `make new-module NAME=demo` produces a module that passes `lint-imports`, `mypy`, `ruff`, and its own placeholder test without edits.
- `AC-FOUND-05.2` No `router.py` function body exceeds 20 statements (checked by a lint rule).
- `AC-FOUND-05.3` No `service.py` in any module imports `fastapi`, `starlette`, `motor`, or `pymongo`.
- `AC-FOUND-05.4` No route returns a Beanie document instance; every response is a `schemas.py` model.
- `AC-FOUND-05.5` Each pure-logic file has zero imports from `app.infra`, `app.modules.*.models`, or `app.modules.*.repository`.

**Tests.**
- `T-FOUND-05.1` `tests/spec/test_new_module_scaffold.py` (runs the generator into a temp dir).
- `T-FOUND-05.2` `ruff` custom rule or `flake8-cognitive-complexity` config in `api-ci`.
- `T-FOUND-05.3` / `T-FOUND-05.5` `tests/spec/test_import_contracts.py` — runs `lint-imports` and asserts the `no-http-in-domain` and `pure-logic` contracts are active and passing.
- `T-FOUND-05.4` `tests/contract/test_response_models.py` — introspects every route's `response_model`.

---

## 6. Specification traceability gate — `FOUND-06`

**Objective.** Keep this specification and the code from drifting, by machine, in CI.

**Constraints.**
- The specification lives at `docs/spec/` in the repo and is versioned with the code. A PR that changes behaviour covered by an acceptance criterion must change the criterion in the same PR.
- The gate parses every `docs/spec/*.md`, extracts identifiers matching `AC-[A-Z]+-\d+\.\d+` and `T-[A-Z]+-\d+\.\d+`, and cross-checks them against the test suite.
- A test path named in a `T-` line must exist. A test may satisfy several criteria; a criterion may not be satisfied by zero tests.
- The parser expands the range and list notation described in `README.md` §0: `T-X-1.1`–`.4` covers criteria `.1` through `.4`, and `T-X-1.2`/`.5` covers exactly those two. A `(shared)` annotation points at a test defined in another file and is resolved across the whole specification, not per file.

**Inputs.** `docs/spec/*.md`; the collected pytest node IDs; `00-scope-and-phases.md` §2 track table.

**Outputs.** CI job `spec-trace`; a generated `docs/spec/TRACEABILITY.md` artifact listing requirement → track → AC → test → status.

**Acceptance criteria.**
- `AC-FOUND-06.1` Every `AC-` identifier in the spec has at least one `T-` identifier in the same file, and every `T-` identifier names a file that exists under `apps/api/tests/`, `apps/web/`, `apps/mobile/`, or `.github/workflows/`.
- `AC-FOUND-06.2` Every requirement marked **R1** in `00-scope-and-phases.md` §2 has ≥1 acceptance criterion somewhere in the spec.
- `AC-FOUND-06.3` No `AC-` or `T-` identifier is defined twice with different text.
- `AC-FOUND-06.4` `TRACEABILITY.md` is regenerated on every push to `develop` and published as a CI artifact.

**Tests.**
- `T-FOUND-06.1`–`.4` `tests/spec/test_traceability.py` — the parser and all four checks, one test case each.

---

## 7. Pagination — `FOUND-07`

**Objective.** Deep lists that stay constant-time and never skip or repeat an item when the underlying data changes mid-scroll.

**Constraints.**
- Cursor-based for every user-facing list. Cursor is an opaque base64url of `{sort_key_values, id}`, signed with `SECRET_KEY` so a client cannot forge a position into another user's data.
- Offset pagination is permitted **only** under `/admin`.
- Sort keys must be a total order — always tie-broken by `_id`. A sort on a nullable field must have a defined null position.
- `limit` default 25, max 100. A request over the max is clamped, not rejected, and the response says so.
- Response shape: `{items: [...], next_cursor: str|null, has_more: bool}`. No `total` on user-facing lists (it costs a second query and is never used); `total` is allowed under `/admin`.

**Inputs.** `?cursor=&limit=`; a `SortSpec` per endpoint.

**Outputs.** `shared/pagination.py`: `Cursor.encode/decode`, `paginate(query, sort, cursor, limit) -> Page[T]`.

**Acceptance criteria.**
- `AC-FOUND-07.1` Paging fully through a 500-item collection returns each item exactly once, with 20 items inserted and 20 deleted midway (no duplicates, no skips of items that existed for the whole traversal).
- `AC-FOUND-07.2` A cursor tampered with in any byte is rejected with 400 `invalid_cursor`.
- `AC-FOUND-07.3` A cursor issued for user A, replayed by user B, returns B's own first page — never A's data.
- `AC-FOUND-07.4` Every paginated query's `explain()` shows an index scan, not a collection scan, at 100k documents.
- `AC-FOUND-07.5` `limit=1000` returns 100 items and `clamped: true`.

**Tests.**
- `T-FOUND-07.1` `tests/integration/test_pagination_stability.py` (hypothesis-driven insert/delete interleaving).
- `T-FOUND-07.2` / `T-FOUND-07.3` `tests/integration/test_cursor_security.py`.
- `T-FOUND-07.4` `tests/integration/test_index_usage.py`.
- `T-FOUND-07.5` `tests/unit/test_pagination_limits.py`.

---

## 8. Idempotency — `FOUND-08`

**Objective.** A retried request never causes a second side effect — a second pack generation, a second AI charge, a second reminder.

**Constraints.**
- Any `POST` that spends money, sends a message, or creates a durable artifact **must** honour an `Idempotency-Key` header: pack generation, pack regeneration, applied-confirmation, custom reminders, export requests, admin connector runs.
- Key scope is `(user_id, route, key)`. Stored in Redis with a 24 h TTL plus a durable record for anything that spent money.
- First request stores `in_progress`; a concurrent duplicate returns `409 idempotency_in_progress`; a duplicate after completion returns the **original response body and status**, with header `Idempotent-Replay: true`.
- A request with the same key but a different body hash returns `422 idempotency_key_reuse`.
- ARQ tasks are separately idempotent by their own natural key (§10) — the HTTP layer's idempotency does not cover a task retried by the worker.

**Inputs.** `Idempotency-Key` header (client-generated UUIDv4); request body hash.

**Outputs.** `core/idempotency.py` dependency; `Idempotent-Replay` response header.

**Acceptance criteria.**
- `AC-FOUND-08.1` The same key sent twice sequentially produces one side effect and two identical response bodies, the second carrying `Idempotent-Replay: true`.
- `AC-FOUND-08.2` The same key sent twice concurrently produces one side effect; the loser gets 409.
- `AC-FOUND-08.3` The same key with a changed body gets 422 and produces no side effect.
- `AC-FOUND-08.4` A route in the "must honour" list that lacks the dependency fails a contract test.
- `AC-FOUND-08.5` Redis being unavailable causes the request to fail closed (503) rather than proceeding without protection.

**Tests.**
- `T-FOUND-08.1`–`.3` `tests/integration/test_idempotency.py`.
- `T-FOUND-08.4` `tests/contract/test_idempotent_routes.py` — asserts the dependency is present on an explicit route allowlist kept in the test.
- `T-FOUND-08.5` `tests/integration/test_idempotency_redis_down.py`.

---

## 9. Domain events — `FOUND-09`

**Objective.** Let modules react to each other without importing each other, and make the reaction graph readable in one file.

**Constraints.**
- In-process synchronous pub/sub in `core/events.py`. Not a message broker (ADR-001: extractable later, not distributed now).
- An event is a frozen Pydantic model in the publishing module's `events.py`, named in the past tense, carrying **IDs and primitives only** — no documents, no nested aggregates.
- Handlers are registered at app startup in one place (`core/events.py::register_all`), so the entire cross-module reaction graph is one readable function.
- A handler **must not** do work inline. It enqueues an ARQ task and returns. This keeps the publisher's latency independent of the number of subscribers and makes retries the queue's problem.
- A handler exception is logged and swallowed; it never fails the publisher's transaction. A handler that must not be lost enqueues before doing anything else.
- Events are not persisted and are not a log. Audit facts go to `audit_log` (`09-apply.md` §6) explicitly.

**R1 event set.**

| Event | Published by | Consumed by | Handler action |
|---|---|---|---|
| `ProfileUpdated{user_id, profile_version, changed_paths}` | profile | matching | enqueue `matching.rescore_user` (debounced 60 s) |
| `ProfileConfirmed{user_id}` | profile | — | (R2: completeness recompute) |
| `ResumeExtracted{user_id, resume_id}` | resume | profile | enqueue `profile.stage_extraction` |
| `JobsIngested{connector, job_ids}` | jobs | matching | enqueue `matching.score_new_jobs` |
| `JobExpired{job_id}` | jobs | tracker | enqueue `tracker.flag_expired_listing` |
| `ApplicationStatusChanged{application_id, user_id, from, to}` | tracker | notifications | enqueue `notifications.reconcile_reminders` |
| `PackApproved{user_id, application_id, pack_id, content_hash}` | apply | tracker | enqueue `tracker.append_timeline` |
| `AppliedConfirmed{user_id, application_id, applied_at}` | apply | tracker, notifications | transition to `applied`; schedule follow-up |
| `UserRegistered{user_id}` | auth | — | none in R1 |
| `UserDeletionRequested{user_id, requested_at}` | auth | — | none in R1; `AUTH-07`'s cron scans `users` |

The last two carry no consumer, and that is deliberate rather than an omission
waiting to be filled. `02-auth-and-account.md` §8 already names auth as their
publisher and `AUTH-01`'s Outputs require `UserRegistered`, so a registry
without them made two sections of this specification unbuildable — `publish`
rejects an unregistered name. They are declared here so the reaction graph stays
readable in one file even where the graph is a leaf: a reader asking "what
happens when someone registers" gets "nothing, in R1" as an answer rather than
as a silence.

`UserDeletionRequested` is listed with `AUTH-07` in view. Its handler action is
**none** on purpose: a deletion that depended on an in-process handler firing
would be lost on a restart between the request and the sweep, so the cron reads
`users.status` and `deletion_requested_at` instead. The event is a notification,
never the mechanism.

**Inputs.** Event instances.

**Outputs.** `core/events.py`; a generated `docs/events.md` table.

**Acceptance criteria.**
- `AC-FOUND-09.1` Every handler registered in `register_all` does nothing but enqueue (asserted by inspecting that no handler imports a repository or an `infra` client).
- `AC-FOUND-09.2` A handler that raises does not propagate to the publisher, and the error is logged with the event name and `request_id`.
- `AC-FOUND-09.3` Publishing an event with a non-primitive field raises at construction.
- `AC-FOUND-09.4` The ten R1 events above each have a test that publishes them and asserts the expected task was enqueued with the expected arguments. For the two that have no consumer (`UserRegistered`, `UserDeletionRequested`), the test asserts that publishing succeeds and enqueues **nothing** — an event with no subscriber must not be an error, and must not quietly acquire one.
- `AC-FOUND-09.5` `docs/events.md` is generated from the registry and matches the table above.

**Tests.**
- `T-FOUND-09.1` `tests/spec/test_handlers_only_enqueue.py`.
- `T-FOUND-09.2` `tests/unit/test_event_bus.py`.
- `T-FOUND-09.3` `tests/unit/test_event_payload_primitives.py`.
- `T-FOUND-09.4` `tests/integration/test_event_wiring.py`, parametrized over the table.
- `T-FOUND-09.5` `tests/spec/test_events_doc.py`.

---

## 10. Background tasks — `FOUND-10`

**Objective.** Long or expensive work runs off the request path, survives a restart, retries safely, and never runs twice in a way the user can notice.

**Constraints.**
- ARQ on Redis. Worker settings and the cron table in `app/worker.py`, in one place.
- A task signature takes **IDs and small scalars only**. If a task needs a document, it loads it. Rationale: a fat payload in Redis goes stale, and a schema change breaks queued jobs.
- Every task is **idempotent by a natural key** and states its key in a docstring. Re-running it must converge, not duplicate. Examples: `resume.process(resume_id)` keyed on `resume_id` + `status` guard; `matching.score(user_id, job_id)` keyed on the unique index; `reminders.dispatch()` keyed on `dedup_key`.
- Retries: max 3, exponential backoff with jitter, then the job is written to `failed_tasks` with the full traceback and the arguments, and an alert fires if the rate exceeds the threshold in `15-infra-and-ops.md` §4.
- A task must set a timeout shorter than the queue's visibility window. A task expected to exceed 60 s must checkpoint by splitting itself (enqueue the next chunk) rather than running long.
- Cron tasks must tolerate overlapping runs: each takes a Redis lock named for itself and exits quietly if held.
- Tasks never call another module's service across a boundary that events would cover; they may call their own module's service freely.

**R1 task/cron inventory** — eighteen tasks. A nineteenth needs a row here before it can be registered: `core/tasks.py` refuses at import any task whose name is absent from this table (`AC-FOUND-10.4`).

| Task | Trigger | Natural key | Notes |
|---|---|---|---|
| `resume.process(resume_id)` | on upload | `resume_id` + status guard | The `04-resume-pipeline.md` §2 stage machine |
| `profile.stage_extraction(resume_id)` | `ResumeExtracted` | `resume_id` | Produces a review draft, never overwrites confirmed fields |
| `ingest.run(connector)` | cron per connector, default `0 */6 * * *` | connector + run window | Lock-guarded |
| `jobs.enrich(job_ids)` | after ingest, gated | `job_id` + `enrichment.model` | Budget-gated (`05-ai-layer.md` §3) |
| `jobs.mark_stale(connector)` | end of `ingest.run` | connector + run id | — |
| `matching.score_new_jobs(job_ids)` | `JobsIngested` | `(user_id, job_id)` unique index | Chunked at 200 jobs |
| `matching.rescore_user(user_id)` | `ProfileUpdated`, debounced | `(user_id, profile_version)` | Skips if a newer version is queued |
| `matching.rationale(user_id, job_id)` | top-N selection | `(user_id, job_id, prompt_version)` | Off in prod at R1 |
| `apply.generate_pack(application_id)` | route (idempotent) | `application_id` + `content_hash` | — |
| `notifications.reconcile_reminders(application_id)` | status/interview change | `dedup_key` per occurrence | Cancels stale, schedules new |
| `reminders.dispatch()` | cron `* * * * *` | `dedup_key` | Batches of 200; lock-guarded |
| `account.purge_deleted()` | cron `0 3 * * *` | `user_id` | 7-day hard delete incl. storage |
| `jobs.purge_expired()` | cron `0 4 * * *` | `expired_at` window + reference check | `DATA-05`; clears descriptions on referenced jobs rather than deleting them (ADR-013) |
| `connector_runs.purge()` | cron `0 4 * * *` | `started_at` window | `DATA-05`; 180 days (ADR-013) |
| `notifications.purge()` | cron `0 4 * * *` | `created_at` window | `DATA-05`; covers `notifications` and sent/cancelled `reminders` (ADR-013) |
| `ops.purge_failed_tasks()` | cron `0 4 * * *` | `resolved_at` window | `DATA-05`; 90 days, resolved only (ADR-013) |
| `ops.backup()` | cron `0 2 * * *` | date | `mongodump` → R2 |
| `ops.heartbeat()` | cron `* * * * *` | minute | Liveness signal from P0 onward |

**Inputs.** Task arguments; Redis.

**Outputs.** Enqueued jobs; `failed_tasks` documents; queue-depth metric.

**Acceptance criteria.**
- `AC-FOUND-10.1` Every task function's parameters are `str`, `int`, `bool`, `float`, or a list of those. A dict or model parameter fails a contract test.
- `AC-FOUND-10.2` Every task has a docstring line starting `Idempotency key:`.
- `AC-FOUND-10.3` Running any task twice with the same arguments produces the same end state and no duplicate side effect (parametrized over the inventory).
- `AC-FOUND-10.4` Killing the worker mid-task and restarting it completes the work exactly once, verified for `resume.process` and `reminders.dispatch`.
- `AC-FOUND-10.5` A task that exhausts retries appears in `failed_tasks` with arguments and traceback, and increments the failure metric.
- `AC-FOUND-10.6` Two concurrent invocations of any cron task result in one doing work and one exiting on the lock.

**Tests.**
- `T-FOUND-10.1` / `T-FOUND-10.2` `tests/spec/test_task_signatures.py`.
- `T-FOUND-10.3` `tests/integration/test_task_idempotency.py`, parametrized.
- `T-FOUND-10.4` `tests/integration/test_worker_restart.py`.
- `T-FOUND-10.5` `tests/integration/test_failed_tasks.py`.
- `T-FOUND-10.6` `tests/integration/test_cron_locks.py`.

---

## 11. Long operations and streaming — `FOUND-11`

**Objective.** The client can watch a slow operation progress without polling tightly, and can fall back to polling when streaming is unavailable.

**Constraints.**
- SSE via `sse-starlette`. No WebSockets in R1 or R2.
- Every `202 Accepted` response body is `{task_id, status, status_url, events_url}`. Both URLs must work: `status_url` is a plain GET returning the current state, `events_url` is the SSE stream. A client that cannot use SSE must be able to complete every flow by polling `status_url`.
- Stream events are `{stage, progress: 0-100, status, detail, at}`. Stages are a fixed per-operation enum, declared in the module's spec file.
- A stream sends a heartbeat comment every 15 s and closes on a terminal status. Maximum stream lifetime 10 min, after which the client re-polls.
- Streams are authenticated the same way as any other route. A stream is scoped to one resource owned by the caller; a 404 on ownership failure (`02-auth-and-account.md` §6).
- Behind Cloudflare, buffering must be disabled for these routes (`Cache-Control: no-cache`, `X-Accel-Buffering: no`).

**Inputs.** Resource ID; auth context.

**Outputs.** `core/sse.py`; per-module event stages.

**Acceptance criteria.**
- `AC-FOUND-11.1` Every `202` response validates against the `AcceptedResponse` schema and both URLs return 200 for the owner.
- `AC-FOUND-11.2` Every flow that uses SSE is completable end to end with SSE blocked, using `status_url` alone (proven for the resume pipeline and pack generation).
- `AC-FOUND-11.3` A stream for a resource owned by another user returns 404 and emits no events.
- `AC-FOUND-11.4` A stream emits a heartbeat within 20 s of silence and closes within 1 s of a terminal status.
- `AC-FOUND-11.5` Responses on SSE routes carry `Cache-Control: no-cache` and `X-Accel-Buffering: no`.

**Tests.**
- `T-FOUND-11.1` `tests/contract/test_accepted_responses.py`.
- `T-FOUND-11.2` `tests/integration/test_poll_fallback.py`.
- `T-FOUND-11.3` `tests/integration/test_sse_ownership.py`.
- `T-FOUND-11.4` `tests/integration/test_sse_lifecycle.py`.
- `T-FOUND-11.5` `tests/contract/test_sse_headers.py`.

---

## 12. Errors — `FOUND-12`

**Objective.** One error shape, one place that maps exceptions to it, and a machine-readable code for every failure a client must handle differently.

**Constraints.**
- `AppError(code: str, message: str, http_status: int, details: dict|None)` hierarchy in `core/errors.py`. One exception handler in `main.py` renders RFC 7807 `application/problem+json`.
- `code` is a stable snake_case string and is the client's contract. `message` is human-readable and may change. Clients switch on `code`, never on `message` or status alone.
- Every error response carries `request_id`, echoed from the request and present in the logs.
- A 500 never leaks an internal message. It returns `{code: "internal_error", request_id}` and logs the detail with the traceback.
- Validation failures from Pydantic render as `422` with `code: "validation_error"` and a `details.fields` map. Field paths use the DTO's names, not the model's.
- The full code registry lives in `core/errors.py` as an enum and is exported to OpenAPI so generated clients get it as a type.
- No module defines an error code outside `core/errors.py` (prevents two modules inventing `not_found`).

**Inputs.** Raised exceptions.

**Outputs.** `problem+json` responses; `ErrorCode` enum in the OpenAPI schema; `docs/error-codes.md` generated from the enum.

**Acceptance criteria.**
- `AC-FOUND-12.1` Every non-2xx response from every route validates against the `Problem` schema and carries a `code` from `ErrorCode`.
- `AC-FOUND-12.2` An unhandled exception produces a 500 whose body contains no exception text, and a log line at `error` with the traceback and the same `request_id`.
- `AC-FOUND-12.3` `request_id` in the response header equals the one in every log line for that request.
- `AC-FOUND-12.4` A grep finds no string literal used as an error code outside `core/errors.py`.
- `AC-FOUND-12.5` `docs/error-codes.md` matches the enum.

**Tests.**
- `T-FOUND-12.1` `tests/contract/test_problem_json.py` — walks every route with deliberately bad input.
- `T-FOUND-12.2` `tests/integration/test_unhandled_exception.py`.
- `T-FOUND-12.3` `tests/integration/test_request_id_propagation.py`.
- `T-FOUND-12.4` `tests/spec/test_error_code_registry.py`.
- `T-FOUND-12.5` same test.

---

## 13. API versioning and contract export — `FOUND-13`

**Objective.** Two generated clients that cannot disagree with the server, and a versioning rule that makes a breaking change visible in review.

**Constraints.**
- All routes under `/api/v1`. A breaking change creates `/api/v2`; it is never made in place. Additive changes (new optional field, new endpoint) are allowed within `v1`.
- The OpenAPI document is exported by CI and committed to `packages/contracts/openapi.json`. TS (`openapi-typescript` + `openapi-fetch`) and Dart (`openapi-generator` dart-dio) clients are generated from it, also by CI.
- A PR whose API surface changes gets an automatic diff comment classifying each change as additive or breaking. A breaking change on `v1` fails CI unless the PR body contains `BREAKING-API-APPROVED:` with a reason.
- Every route declares `response_model`, an explicit `status_code`, `tags` matching its module, an `operation_id` of `<module>_<action>` (so generated client method names are stable), and a `responses` entry for every error code it can raise.
- `/healthz`, `/readyz`, `/metrics` sit outside `/api/v1` and outside the generated clients.

**Inputs.** FastAPI route definitions.

**Outputs.** `packages/contracts/openapi.json`; `packages/contracts/ts/`; `packages/contracts/dart/`; the diff comment.

**Acceptance criteria.**
- `AC-FOUND-13.1` Every route under `/api/v1` has a `response_model`, an explicit `status_code`, a module-matching tag, and an `operation_id` matching `^[a-z_]+_[a-z_]+$`.
- `AC-FOUND-13.2` `openapi.json` in the repo equals the one generated from the current code (CI regenerates and diffs).
- `AC-FOUND-13.3` Both generated clients compile: `tsc --noEmit` on the TS client, `dart analyze` on the Dart client.
- `AC-FOUND-13.4` A removed field or a widened requirement on `v1` fails CI without the approval token.
- `AC-FOUND-13.5` No route outside `/api/v1` appears in either generated client.

**Tests.**
- `T-FOUND-13.1` `tests/contract/test_route_metadata.py`.
- `T-FOUND-13.2`–`.4` `.github/workflows/contracts.yml`.
- `T-FOUND-13.5` `tests/contract/test_client_surface.py`.

---

## 14. Logging and observability hooks — `FOUND-14`

**Objective.** Every log line is a queryable JSON object correlated to a request, and no line contains a secret or a person's data.

**Constraints.**
- `structlog` to stdout, JSON in every environment except local (where it is pretty-printed).
- Every line binds `request_id`, `module`, and — where authenticated — `user_id`. Never an email address, never a token, never a code, never a request or response body, never resume or job text.
- Provider errors are logged as a **code and a status**, never the provider's message body, which can contain echoed content.
- One middleware assigns `request_id` (accepting an inbound `X-Request-ID` if it is a valid UUID, else generating one) and echoes it in the response header.
- OpenTelemetry auto-instrumentation for FastAPI, httpx, and Motor. Span attributes follow the same redaction rule.
- `/metrics` in Prometheus format, protected by `METRICS_TOKEN`. Required metrics: request latency histogram by route and status; queue depth by queue; task duration and outcome by task; connector run outcome by connector; AI tokens and cost by feature and model; reminders sent by type and channel.
- Sentry for API, web, and mobile, with `before_send` applying the same redaction list.

**Inputs.** Requests, tasks, provider calls.

**Outputs.** JSON logs; traces; `/metrics`; Sentry events.

**Acceptance criteria.**
- `AC-FOUND-14.1` A test that exercises registration, login, resume upload, pack generation, and a reminder send captures all log output and asserts it contains none of: the test email address, the test password, any JWT, any OTP, any substring of the test resume, any substring of a job description.
- `AC-FOUND-14.2` Every log line emitted during a request contains the same `request_id` as the response header.
- `AC-FOUND-14.3` `/metrics` without a valid token returns 401; with one, it exposes all seven required metric families.
- `AC-FOUND-14.4` A Sentry event captured in a test has redacted `user.email` and no request body.
- `AC-FOUND-14.5` An AI provider 400 with an echoed prompt in its body produces a log line containing the status code and not the body.

**Tests.**
- `T-FOUND-14.1` `tests/integration/test_log_privacy.py`.
- `T-FOUND-14.2` `tests/integration/test_request_id_propagation.py`.
- `T-FOUND-14.3` `tests/integration/test_metrics_endpoint.py`.
- `T-FOUND-14.4` `tests/unit/test_sentry_before_send.py`.
- `T-FOUND-14.5` `tests/unit/test_provider_error_logging.py`.

---

## 15. Implementation status — `FOUND-15` — **added in v2.1**

**Objective.** Make "is this built?" a question with four possible answers and a machine check, so that a flag that is off, a route that is a stub, and a feature that does not exist are never confused with one another — by an agent, by a reviewer, or by you in six weeks.

**Constraints.**

Four states. There is no fifth, and in particular there is no "partially implemented":

| State | Means | Code | Flag | API surface | Tests |
|---|---|---|---|---|---|
| `built` | Implemented and on | Present | None, or default on | Route present and working | Full, passing in CI |
| `built-off` | Implemented, deliberately disabled in production | Present | Default **off** in production | Route present; returns the feature's **declared degradation**, never an error | Full, passing in CI with the flag forced on |
| `stub-501` | Route reserved so a client can detect it, no implementation behind it | Minimal | None | Route present, `501 not_implemented`, tagged `x-status: stub` in OpenAPI | One test asserting the 501 and the code |
| `absent` | Does not exist | None | None | No route | None |

- Every section in every specification file carries a `**Status:**` line naming one of the four. The generator writes them into `docs/spec/status.yaml` and into `SPEC-METADATA.json`, so the state of the whole product is one file.
- **Default by track**: an R1 section is `built`; an R2 or R3 section is `absent`. Any other combination must be declared explicitly with a reason on the same line. The only `built-off` in R1 is `MATCH-02b` (`08-matching.md` §4), and `README.md` §1 explains why.
- **`built-off` obligations**, all four required, because a flag that has never been on is not a feature but a rumour:
  1. Its acceptance criteria pass in CI with the flag **forced on**, against the fake provider where an external service is involved.
  2. Turning it on in production requires **no code change and no migration** — proven by a test that flips the flag in the integration environment and runs the feature's criteria against a database seeded in the off state.
  3. Its flag appears in `ADMIN-03`'s list with its blast radius, and the admin UI shows the resolved value and where the value came from.
  4. The UI is **complete with the feature off**: no empty placeholder, no disabled button, no "coming soon". `AC-MATCH-02.6` is the worked example.
- **`stub-501` obligations**: the code is `not_implemented`, registered in `ErrorCode` (§12) and in `docs/error-codes.md`; the response never varies by input; the route never returns 500; neither client offers a control that calls it. A stub is justified only by a client that must distinguish "not yet" from "not a thing" — otherwise use `absent`.
- **`absent` obligations**, which is where the real discipline lives: no dead code, no commented-out block, no unreachable branch, no unused flag, no orphan migration, no test skipped with a "later" marker, and no model field that nothing reads. An R2 feature's *data-model fields* may exist ahead of time when `17-data-model.md` marks them `[R2]` — the additive-schema rule requires it — and those fields must be null and unread until the feature is built.
- **The status registry is checked against reality**, not trusted: for every section, CI verifies the flag's production default in config, the route's presence and behaviour in `openapi.json`, the existence of the named tests, and — for `absent` — that no module file, flag, or route for it exists. A declared status that does not match reality fails the build.
- A status change is a deliberate edit to the specification in the same PR as the code. Discovering a feature's status by reading the code is the failure this section removes.

**Inputs.** The `Status:` lines; `Settings` flag defaults; `openapi.json`; the collected test node IDs.

**Outputs.** `docs/spec/status.yaml`; a `status` field per section in `SPEC-METADATA.json`; the CI check; the admin flag view's resolved-status column.

**Acceptance criteria.**
- `AC-FOUND-15.1` Every section in every specification file has a `Status:` line naming exactly one of the four states.
- `AC-FOUND-15.2` Every R1 section is `built` except `MATCH-02b`, which is `built-off` with a stated reason; every R2 and R3 section is `absent` unless it declares otherwise with a reason.
- `AC-FOUND-15.3` For each `built-off` section, its acceptance criteria pass with the flag forced on, and flipping the flag against an off-state database requires no migration.
- `AC-FOUND-15.4` For each `built-off` section, the UI is complete with the flag off — no placeholder, no disabled control (component tests in both clients).
- `AC-FOUND-15.5` Every `stub-501` route returns 501 with `code: not_implemented`, is tagged `x-status: stub`, and is called by no control in either client.
- `AC-FOUND-15.6` For every `absent` section: no route, no flag, no module file, no skipped test, and no code path mentioning it. Model fields marked `[R2]`/`[R3]` are permitted, are null in every seeded fixture, and are read by nothing.
- `AC-FOUND-15.7` The whole codebase contains no `TODO`, `FIXME`, `XXX`, `raise NotImplementedError`, `@pytest.mark.skip`, or commented-out code block on an R1 path.
- `AC-FOUND-15.8` `status.yaml` matches reality for all four dimensions (flag default, route presence, route behaviour, test presence); a deliberate mismatch fails CI in a fixture test.
- `AC-FOUND-15.9` The admin flag view shows each flag's resolved value, its source, and the status of the section it gates.

**Tests.**
- `T-FOUND-15.1`/`.2` `tests/spec/test_status_declared.py`.
- `T-FOUND-15.3` `tests/integration/test_flag_flip.py`.
- `T-FOUND-15.4` `apps/web/.../flag-off-complete.test.tsx`, `apps/mobile/test/flag_off_complete_test.dart`.
- `T-FOUND-15.5` `tests/contract/test_stub_routes.py`.
- `T-FOUND-15.6` `tests/spec/test_absent_sections.py`.
- `T-FOUND-15.7` `tests/spec/test_no_placeholders.py`.
- `T-FOUND-15.8` `tests/spec/test_status_matches_reality.py`.
- `T-FOUND-15.9` `tests/integration/test_admin_flags.py` (shared).

---

## 16. Transactional email transport — `FOUND-16` — **added in v2.1**

**Objective.** One way to send a templated message to one address, available from the first phase, owned by infrastructure rather than by the notifications module.

**Why this is foundations and not notifications.** `AUTH-01`, `AUTH-03` and `AUTH-05` send email in phase P1 — verification, the attempted-registration notice, password reset. In v2.0 the only email specification lived in `NOTIF-02a`, phase P6, which made P1 unbuildable as written (`18-dependency-closure.md` §5.1). The cut that fixes it is also the right one on principle: **delivering a templated message to an address is infrastructure**, like storage or the queue. **Deciding which messages a user receives, when, and through which channel is product**, and stays in `notifications`.

**Constraints.**
- `infra/email` exposes one protocol and nothing else:

```python
class EmailSender(Protocol):
    async def send(self, to: str, template_id: str, data: dict,
                   idempotency_key: str | None = None) -> MessageId: ...
```

- No provider SDK type crosses that boundary; the adapter (Resend by default, SES the documented alternative — D7) receives its credential by constructor injection and never reads the environment (§2).
- **Templates are a registry, validated at startup.** Each template declares its `template_id`, its required `data` keys, and its subject. A `send` with a missing key raises before the provider is contacted. MJML compiled to HTML at build time, and **a plain-text alternative is required** — text-only clients and spam scoring both need one.
- **Idempotency**: a `send` with an `idempotency_key` already seen within 24 h is a no-op returning the original `MessageId`. This is what makes the reminder dispatcher's claim-then-send safe (`11-notifications.md` §3).
- **Privacy**: the only personal datum in an email is the recipient's own. Logs carry `template_id`, `MessageId` and outcome — never the address, never the body, never a token (§14). A provider error is logged as a code (`AC-FOUND-14.5`).
- **Deliverability is part of the contract, not an afterthought**: SPF, DKIM and DMARC on the sending domain are verified by a script at the R1 gate (`AC-NOTIF-02.6`), because transactional mail that lands in spam fails silently and takes the last clause of the exit sentence with it.
- **Bounces and complaints**: a webhook marks `users.email_undeliverable`, stops further sends to that address, and surfaces the state in the in-app inbox. Continuing to send to a bouncing address damages the domain for every other user.
- Retries: 3 attempts with backoff on 5xx and transport errors only; never on a 4xx, which means the address or the payload is wrong and retrying just burns quota.
- Locally and in tests, the adapter is `mailpit`; no test sends real mail (`AC-FOUND-16.5`).
- **R1 template set**: `verify_email`, `registration_attempted`, `password_reset`, `password_changed`, `deletion_requested`, `deletion_completed`. `NOTIF-02a` adds the reminder templates in P6; `AUTH-08` adds `export_ready` in R2.

**Inputs.** Recipient address, `template_id`, `data`, optional idempotency key.

**Outputs.** `infra/email/{base,resend,mailpit}.py`; the template registry; the bounce webhook; `email_sent{template,outcome}` metric.

**Acceptance criteria.**
- `AC-FOUND-16.1` Every R1 template renders in HTML and plain text, and a golden-file test catches unintended changes (shared with `AC-NOTIF-02.1`).
- `AC-FOUND-16.2` A `send` missing a required `data` key raises before any provider call.
- `AC-FOUND-16.3` The same idempotency key twice within 24 h produces one delivery and the same `MessageId`.
- `AC-FOUND-16.4` No log line, metric label, or Sentry event contains a recipient address or a message body.
- `AC-FOUND-16.5` No test in any suite sends mail outside mailpit (asserted by an outbound-request guard).
- `AC-FOUND-16.6` A bounce webhook marks the address undeliverable, stops sends, and writes an in-app notification (shared with `AC-NOTIF-02.3`).
- `AC-FOUND-16.7` `modules/auth` contains no email client and no provider import; it depends only on `EmailSender` (import contract, shared with `AC-DEP-05.2`).
- `AC-FOUND-16.8` A 4xx from the provider is not retried; a 5xx is retried three times with backoff.
- `AC-FOUND-16.9` Swapping the adapter to a second provider requires no change outside `infra/email` — proven by the SES adapter passing the same contract suite.

**Tests.**
- `T-FOUND-16.1` `tests/unit/test_email_templates.py` (shared).
- `T-FOUND-16.2` `tests/unit/test_template_registry.py`.
- `T-FOUND-16.3` `tests/integration/test_email_idempotency.py`.
- `T-FOUND-16.4` `tests/integration/test_log_privacy.py` (shared).
- `T-FOUND-16.5` `tests/spec/test_no_live_email.py`.
- `T-FOUND-16.6` `tests/integration/test_bounce_handling.py` (shared).
- `T-FOUND-16.7` `tests/spec/test_email_ownership.py` (shared).
- `T-FOUND-16.8` `tests/unit/test_email_retries.py`.
- `T-FOUND-16.9` `tests/integration/test_email_adapter_contract.py`.
