# 15 — Infrastructure, Deployment and Operations

**Module:** `infra/`, `.github/workflows/`, `apps/api/Dockerfile`
**Track:** R1 except §6.2 (restore drill), §7 (runbooks), §4.3 (alert delivery) — all R2
**Requirements:** `OPS-01` … `OPS-08`

The operating constraint is one person, near-zero recurring cost, and a product that must not lose a user's data. Everything here follows from those three.

---

## 1. Docker and the single image — `OPS-01`

**Objective.** One artifact that runs the API or the worker, identical in every environment.

**Constraints.**
- Multi-stage `Dockerfile`: a build stage using `uv` to install into a virtual environment, then a slim runtime stage copying only that environment and the application. No compiler, no `uv`, no git in the runtime image.
- Runs as a **non-root user** with a read-only root filesystem and a writable `/tmp` only.
- Entrypoints: `api` (uvicorn, 2 workers) and `worker` (`arq app.worker.WorkerSettings`). Selected by the command, not by an environment variable, so a misconfigured variable cannot start the wrong process (ADR-002).
- `HEALTHCHECK` hits `/healthz`. `/readyz` additionally pings Mongo and Redis and verifies every declared index is present (`AC-DATA-01.3`) — a container that is up but missing an index is not ready.
- Image tagged with the git SHA and pushed to GHCR. `latest` is never deployed from; a deploy names a SHA, so a rollback is a known tag rather than a rebuild.
- Layer order puts dependency installation before application copy, so an application-only change rebuilds in seconds.
- Target: image under 400 MB in R1 (OCR in R2 adds roughly 200 MB and that increase is expected and budgeted).
- `docker compose` (local) brings up: api, worker, mongo, redis, minio, mailpit. `make up` is the only command a new machine needs after copying `.env.example`.

**Acceptance criteria.**
- `AC-OPS-01.1` The image runs as a non-root user with a read-only root filesystem, verified by inspecting the running container.
- `AC-OPS-01.2` Both entrypoints start from the same image digest (`AC-FOUND-01.2` shared).
- `AC-OPS-01.3` `/readyz` returns 503 when Mongo is down, when Redis is down, and when a declared index is missing; 200 otherwise.
- `AC-OPS-01.4` The runtime image contains no compiler, no package manager cache, and no `.git`.
- `AC-OPS-01.5` Changing one application file rebuilds without reinstalling dependencies.
- `AC-OPS-01.6` `make up` from a clean clone reaches a ready state within 90 s (`AC-FOUND-01.1` shared).
- `AC-OPS-01.7` Image size is under 400 MB.

**Tests.**
- `T-OPS-01.1`/`.4`/`.7` `.github/workflows/api-ci.yml` step `image-audit`.
- `T-OPS-01.2` `api-ci` step `image-entrypoints` (shared).
- `T-OPS-01.3` `tests/integration/test_readyz.py`.
- `T-OPS-01.5` `api-ci` step `layer-cache-check`.
- `T-OPS-01.6` `tests/integration/test_compose_boot.py` (shared).

---

## 2. Environments — `OPS-02`

**Objective.** Three environments where staging genuinely predicts production.

| Env | API + worker | Web | Data | Deploy |
|---|---|---|---|---|
| local | compose (api, worker, mongo, redis, minio, mailpit) | Vite dev | local | `make up` |
| staging | one container host, 1 api + 1 worker | Cloudflare Pages preview | Atlas M0 `jobpilot-stg`, R2 `jobpilot-stg` | auto on push to `develop` |
| prod | same host, 2 api + 1 worker behind Caddy | Cloudflare Pages | Atlas M0 → M10 on trigger, R2 `jobpilot-prod` | on `v*` tag, manual approval |

**Constraints.**
- **D3 default: one small VPS running compose behind Cloudflare** (`00-scope-and-phases.md` §5). Rationale: predictable cost (~₹400–600/month), no hobby-tier policy changes, and the compose file is already the source of truth. A PaaS remains a drop-in alternative precisely because the artifact is a container.
- Staging differs from production in exactly three documented ways: cluster and bucket names, the AI provider selection (staging may use the fake provider for some features), and connector enablement. **Nothing else** — a staging that differs structurally predicts nothing.
- The origin accepts traffic **only from Cloudflare IP ranges** (firewall plus a Caddy check); a direct request to the origin IP is refused, so the WAF and rate limiting cannot be bypassed.
- Cloudflare provides DNS, TLS, HSTS, WAF, a coarse rate limit, and static hosting for the web app (ADR-010).
- Secrets in production come from Docker secrets or the host's environment file with `0600` permissions, never from a file in the repository, and never from an image layer.
- Both environments run the same migration step on deploy; a failed migration aborts the deploy before the new image serves traffic.

**Acceptance criteria.**
- `AC-OPS-02.1` A request to the origin IP bypassing Cloudflare is refused.
- `AC-OPS-02.2` A documented diff between staging and production configuration shows only the three permitted differences (a CI check comparing the two env manifests).
- `AC-OPS-02.3` A push to `develop` reaches staging with no manual step and both clients show live health from it (the P0 gate).
- `AC-OPS-02.4` A `v*` tag deploys to production only after the manual approval gate.
- `AC-OPS-02.5` A failing migration aborts the deploy and the previous version continues serving.
- `AC-OPS-02.6` No secret appears in any image layer (a scan of the built image's layers).

**Tests.**
- `T-OPS-02.1` `infra/scripts/check_origin_lockdown.sh` + `tests/spec/test_origin_check_exists.py`.
- `T-OPS-02.2` `tests/spec/test_env_parity.py`.
- `T-OPS-02.3`/`.4`/`.5` `.github/workflows/deploy-staging.yml`, `deploy-prod.yml`.
- `T-OPS-02.6` `api-ci` step `layer-secret-scan`.

---

## 3. CI/CD — `OPS-03`

**Objective.** Everything that can be checked by a machine is checked before merge, and a deploy is boring.

| Workflow | Trigger | Steps |
|---|---|---|
| `api-ci` | PR, push | ruff, mypy, **import-linter**, pytest with Mongo + Redis service containers, coverage gates, `pip-audit`, `gitleaks`, prompt-immutability, spec traceability, image build + audit |
| `web-ci` | PR, push | tsc, eslint, vitest, bundle-size, admin-chunk isolation, Playwright smoke, lighthouse, artifact secret scan |
| `mobile-ci` | PR, push | `flutter analyze`, `flutter test`, permission audit, SDK scan, APK size, debug build, iOS analyze |
| `contracts` | API change | export OpenAPI → diff-classify → regenerate TS + Dart → PR if diff; fail on an unapproved breaking change |
| `deploy-staging` | push `develop` | build, push, migrate, deploy, smoke |
| `deploy-prod` | tag `v*` | same, with a manual approval environment |
| `mobile-release` | tag `mobile-v*` | signed AAB, fingerprint assertion, Play Internal Testing |
| `nightly` | schedule | `real_ai` golden tests, `real_source` connector drift, latency suites, e2e repeat ×20, capacity report, index-size budget |

**Constraints.**
- The **required** checks for merge are: ruff, mypy, import-linter, pytest, coverage gates, spec traceability, tsc, eslint, vitest, flutter analyze, flutter test. Everything else reports without blocking, so a flaky Lighthouse run never blocks a fix.
- Coverage gates: core modules (matching, jobs normalization/dedup, tracker state, apply fabrication, notifications scheduling) **≥70%**; each connector's `normalize` at 100% of branches reachable from its fixtures; the fabrication checker at 100% recall on its positive corpus (`AC-APPLY-04.1`), which is a gate rather than a percentage.
- Tests never reach an external host: `respx` in strict mode globally for Python, a request interceptor in Playwright (`AC-CONN-06.5`, `AC-WEB-08.2`). The nightly `real_*` markers are the only exception and they run in a separate workflow with their own credentials.
- Secrets are per-environment GitHub environments with required reviewers on production.
- A PR template requires: what and why, test evidence, an ADR link for an architectural change, and a compliance note for a connector change.
- Pre-commit runs ruff, mypy on changed files, gitleaks, prettier/eslint, and `dart format`, so CI is a confirmation rather than a discovery.

**Acceptance criteria.**
- `AC-OPS-03.1` A PR failing any required check cannot merge (branch protection asserted by a settings check script).
- `AC-OPS-03.2` The coverage gates fail the build when breached, verified by a deliberate uncovered branch in a fixture PR.
- `AC-OPS-03.3` A test attempting an external request fails with a clear message rather than succeeding silently.
- `AC-OPS-03.4` An unapproved breaking API change fails `contracts` (`AC-FOUND-13.4` shared).
- `AC-OPS-03.5` Production deploys require an approval; the audit trail shows who approved.
- `AC-OPS-03.6` A full `api-ci` run completes in under 12 minutes.

**Tests.**
- `T-OPS-03.1` `infra/scripts/check_branch_protection.sh`.
- `T-OPS-03.2` `api-ci` coverage configuration + `tests/spec/test_coverage_config.py`.
- `T-OPS-03.3` `tests/spec/test_no_live_source_calls.py` (shared).
- `T-OPS-03.4` `.github/workflows/contracts.yml` (shared).
- `T-OPS-03.5` `deploy-prod.yml` environment protection.
- `T-OPS-03.6` CI duration budget check in `api-ci`.

---

## 4. Observability — `OPS-04`

### 4.1 Logs, traces, metrics

**Constraints.** Per `01-foundations.md` §14: structlog JSON to stdout with `request_id` binding and the redaction rules; OpenTelemetry auto-instrumentation for FastAPI, httpx, and Motor; `/metrics` in Prometheus format behind `METRICS_TOKEN`; Sentry for API, web, and mobile with matching redaction.

Free-tier destinations, chosen so that observability costs nothing at this scale: logs shipped to Grafana Cloud Loki (or retained on the host with rotation if the free tier is exhausted), traces to Grafana Tempo, metrics scraped by Grafana Cloud or a small local Prometheus. The specification does not depend on the vendor — it depends on the data being emitted in standard formats, which it is.

### 4.2 The required metrics

Seven families, each named because a specific question needs it:

| Metric | Question it answers |
|---|---|
| `http_request_duration_seconds{route,status}` | Is the API meeting its latency budget |
| `queue_depth{queue}` | Is the worker keeping up |
| `task_duration_seconds{task,outcome}` | Which background job is slow or failing |
| `connector_run{connector,outcome}` + `connector_items{connector,kind}` | Is each source still delivering |
| `ai_tokens{feature,model,kind}` + `ai_cost_usd{feature}` | What is the spend, by feature |
| `ai_budget_state{feature}` | Are users being degraded right now |
| `reminders_sent{type,channel,outcome}` | Is the last clause of the exit sentence actually working |

### 4.3 Alerts — **Track: R2** (thresholds defined in R1, delivery in R2)

| Alert | Condition | Why |
|---|---|---|
| Connector circuit open | any connector `open` | A dead source is invisible otherwise |
| AI daily cap hit | global or per-feature cap reached | Users are being degraded |
| Queue depth | >1,000 for 10 minutes | The worker is stuck or overwhelmed |
| Error rate | >2% of requests over 10 minutes | Something is broken |
| Reminder dispatch stalled | no dispatch run in 10 minutes | The one feature with a deadline |
| Storage pressure | Atlas >75% for 3 days | The M10 trigger (`AC-DATA-06.4`) |
| Unpriced AI model | any `est_cost_usd: null` | Cost tracking has a blind spot |
| Backup missing | no successful backup in 36 hours | The thing you only discover when you need it |

**Acceptance criteria.**
- `AC-OPS-04.1` All seven metric families are present on `/metrics` and change as expected under a synthetic load (`AC-FOUND-14.3` shared).
- `AC-OPS-04.2` Every log line carries `request_id` and passes the privacy assertions (`AC-FOUND-14.1` shared).
- `AC-OPS-04.3` A trace spans an API request through to a Mongo query and an outbound provider call.
- `AC-OPS-04.4` Each of the eight alert conditions fires in a synthetic test of its condition.
- `AC-OPS-04.5` (R2) Each alert reaches you on a channel you actually read, verified by a live test of each.

**Tests.**
- `T-OPS-04.1` `tests/integration/test_metrics_endpoint.py` (shared).
- `T-OPS-04.2` `tests/integration/test_log_privacy.py` (shared).
- `T-OPS-04.3` `tests/integration/test_tracing.py`.
- `T-OPS-04.4` `tests/integration/test_alert_conditions.py`.
- `T-OPS-04.5` `tests/spec/test_runbooks_present.py` (shared) — asserts `docs/runbooks/alerting.md` and its manual verification record (R2).

---

## 5. Configuration and environment variables — `OPS-05`

**Objective.** One list, matching the code, with nothing secret in the repository.

**Constraints.** `.env.example` is the authoritative list and is asserted to match `Settings` exactly (`AC-FOUND-02.3`). Grouped as below; secrets are empty in the example.

```
# core
APP_ENV=local|staging|prod
PRODUCT_NAME=
API_BASE_URL=            WEB_ORIGIN=
SECRET_KEY=
JWT_PRIVATE_KEY_PEM=     JWT_PUBLIC_KEY_PEM=     JWT_ISSUER=     JWT_AUDIENCE=
ACCESS_TOKEN_TTL_MIN=15  REFRESH_TOKEN_TTL_DAYS=30  REFRESH_PEPPER=
# data
MONGODB_URI=             MONGODB_DB=
REDIS_URL=
# storage (R2, S3-compatible)
R2_ACCOUNT_ID=  R2_ACCESS_KEY_ID=  R2_SECRET_ACCESS_KEY=  R2_BUCKET=  R2_PUBLIC_BASE_URL=
# ai  — see 05-ai-layer.md §5 for the isolation rules
AI_PROVIDER_DEFAULT=gemini      AI_EMBEDDING_PROVIDER=gemini
AI_PROVIDER_RESUME_EXTRACT=     AI_PROVIDER_MATCH_RATIONALE=     AI_PROVIDER_PACK_GENERATE=
GEMINI_API_KEY=                 # dedicated Cloud project, own billing account (HR-6)
GEMINI_MODEL_FAST=  GEMINI_MODEL_QUALITY=  GEMINI_EMBEDDING_MODEL=
AI_DAILY_COST_CAP_USD=2   AI_USER_DAILY_CALLS=500   AI_RATIONALE_TOP_N=20   AI_CACHE_TTL_DAYS=7
AI_EMBEDDING_MIGRATION=   # 'allow' only during a deliberate re-embedding
OPENAI_API_KEY=  ANTHROPIC_API_KEY=  OLLAMA_BASE_URL=     # optional adapters
# connectors
ADZUNA_APP_ID=  ADZUNA_APP_KEY=
INGEST_MAX_QUERIES_PER_RUN=40   INGEST_DEFAULT_CRON="0 */6 * * *"   CONNECTOR_USER_AGENT=
# comms
EMAIL_PROVIDER=resend   RESEND_API_KEY=   EMAIL_FROM=
FIREBASE_SERVICE_ACCOUNT_JSON_B64=      # R2
VAPID_PUBLIC_KEY=  VAPID_PRIVATE_KEY=   # R3
# oauth  (sign-in only — never reachable from the AI path, HR-6)
GOOGLE_OAUTH_CLIENT_ID=  GOOGLE_OAUTH_CLIENT_SECRET=
# observability
SENTRY_DSN=  OTEL_EXPORTER_OTLP_ENDPOINT=  LOG_LEVEL=INFO  METRICS_TOKEN=
# flags (DB overrides these)
FLAG_LLM_RATIONALE_ENABLED=false  FLAG_JOB_ENRICHMENT_ENABLED=true  FLAG_OCR_ENABLED=false
FLAG_EXTENSION_APPLY_ENABLED=false  FLAG_DIGEST_ENABLED=false  FLAG_PUSH_ENABLED=false
FLAG_SIGNUP_ENABLED=true  FLAG_INGESTION_ENABLED=true
# limits (config, not literals)
RATE_LOGIN_PER_MIN_IP=10  RATE_LOGIN_PER_MIN_EMAIL=5  RATE_GENERAL_PER_MIN_USER=300
```

Note the two Google entries: `GEMINI_API_KEY` for inference and `GOOGLE_OAUTH_*` for sign-in. They belong to different Google products and different projects, and the import contract in `01-foundations.md` §4 makes it impossible for the AI path to reach the OAuth credentials.

**Acceptance criteria.**
- `AC-OPS-05.1` `.env.example` and `Settings` match exactly, both directions (`AC-FOUND-02.3` shared).
- `AC-OPS-05.2` No secret has a non-empty value in the example.
- `AC-OPS-05.3` Booting production with `GOOGLE_APPLICATION_CREDENTIALS` present fails (`AC-AI-05.2` shared).
- `AC-OPS-05.4` `gitleaks` finds no secret in the history at the R1 gate.

**Tests.**
- `T-OPS-05.1` `tests/spec/test_env_example_parity.py` (shared).
- `T-OPS-05.2` `tests/spec/test_env_example_no_secrets.py`.
- `T-OPS-05.3` `tests/ai/test_gemini_startup_guards.py` (shared).
- `T-OPS-05.4` `api-ci` step `gitleaks`.

---

## 6. Backups and disaster recovery — `OPS-06`

### 6.1 Backups — **R1**

**Objective.** Survive losing the database, because Atlas M0 has no automated backups.

**Constraints.**
- Nightly `ops.backup()` at 02:00 UTC: `mongodump` piped to gzip, uploaded to R2 at `backups/{YYYY-MM-DD}/dump.archive.gz`, 14-day lifecycle expiry.
- The dump is **verified**, not assumed: the job checks the archive's size against the trailing median (alerting on a 40% deviation, which is how a silently truncated dump is caught) and lists the archive after upload.
- A missing backup alerts within 36 hours (§4.3).
- R2 objects are the source of truth for files and have bucket versioning on with a 30-day noncurrent expiry, so a mistaken delete is recoverable.
- The backup contains personal data and is therefore in scope for the consent text's retention statement (`16-security-and-compliance.md` §4): a deletion request cannot reach into an existing backup, and backups age out at 14 days, which is disclosed.
- Backups are **never** restored into production without a documented decision; the drill restores into a scratch database.

### 6.2 Restore drill — **Track: R2**

Restore the most recent backup into a scratch Atlas database, run the integration suite against it, record the wall-clock time in `docs/runbooks/restore.md`. The number that matters is how long it takes, because that is the recovery time you are actually offering. Repeated quarterly.

**Acceptance criteria.**
- `AC-OPS-06.1` Seven consecutive nightly backups exist and the most recent restores into a scratch database with the integration suite passing (the R1 gate item).
- `AC-OPS-06.2` A deliberately truncated dump triggers the size-deviation alert.
- `AC-OPS-06.3` Backups older than 14 days are absent.
- `AC-OPS-06.4` A deleted R2 object is recoverable within 30 days from a noncurrent version.
- `AC-OPS-06.5` (R2) The drill is recorded with a measured recovery time.

**Tests.**
- `T-OPS-06.1` `tests/integration/test_backup_restore.py` (nightly) + the gate record.
- `T-OPS-06.2` `tests/integration/test_backup_verification.py`.
- `T-OPS-06.3` `infra/scripts/check_backup_retention.sh`.
- `T-OPS-06.4` `tests/integration/test_r2_versioning.py`.
- `T-OPS-06.5` `tests/spec/test_runbooks_present.py` (shared) — asserts `docs/runbooks/restore.md` records a measured recovery time (R2).

---

## 7. Runbooks — `OPS-07` — **Track: R2**

**Objective.** A written answer to each thing that will actually go wrong, so that solving it at 1 a.m. is reading rather than thinking.

Required, each with symptoms, diagnosis steps, actions, and a verification: **connector failing** (circuit open, or items dropping to zero); **AI cap exceeded** (which feature, raise or fix); **restore from backup** (with the measured time); **rotate JWT keys** (publish the new public key, then switch signing, then retire); **verify a user deletion** (the prefix listing and the per-collection counts); **add a company board** (slug, verification, first run); **storage pressure** (the M10 upgrade path); **email deliverability** (bounce rate, DNS, reputation).

Each runbook is written after the first time the situation occurs, or during R2 if it has not — a runbook invented from imagination is usually wrong in the detail that matters.

**Acceptance criteria.** `AC-OPS-07.1` All eight runbooks exist with the four required sections. `AC-OPS-07.2` The restore runbook contains a measured time. `AC-OPS-07.3` The deletion-verification runbook's steps are executable and were executed once.
**Tests.** `T-OPS-07.1`–`.3` `tests/spec/test_runbooks_present.py`.

---

## 8. Cost ceiling — `OPS-08`

**Objective.** Know what this costs at 50 users and what the first thing to break is.

**Constraints.** Target ≤₹1,000/month total at under 1,000 users, with every line either free-tier or a fixed small cost, and each line carrying the event that ends its free tier:

| Line | R1 cost | Free-tier limit that ends first |
|---|---|---|
| VPS (D3) | ~₹400–600 | Not free; fixed |
| Atlas M0 | ₹0 | 512 MB storage — `17-data-model.md` §6, alert at 75% |
| Cloudflare (DNS, TLS, WAF, Pages) | ₹0 | Generous; Pages build minutes first |
| R2 | ₹0 | 10 GB storage, and egress is free — which is why it was chosen |
| Redis (Upstash free) | ₹0 | Daily command count, which the reminder cron consumes steadily |
| Gemini API | Capped by `AI_DAILY_COST_CAP_USD` | Free-tier RPM and daily tokens; the cap is the real control |
| Resend | ₹0 | 3,000/month, which reminders will reach before signups do |
| Sentry / Grafana Cloud | ₹0 | Event and log volume |
| Play Console | one-off $25 | — |

- The **AI daily cap is the only cost that can run away**, which is why §4.3 alerts on it and `05-ai-layer.md` §3 enforces it before every call.
- A monthly cost review is a calendar item, not a hope: actual spend against this table, recorded in `docs/runbooks/cost.md`.
- D10 (invite-only R1 beta, hard cap 50 accounts) exists because two of these limits — Atlas storage and the AI cap — can be exhausted overnight by an open signup.

**Acceptance criteria.**
- `AC-OPS-08.1` The cost table exists in `docs/runbooks/cost.md` with actuals recorded monthly from the R1 tag onward.
- `AC-OPS-08.2` The signup allowlist enforces the 50-account cap and returns `403 signups_closed` beyond it (`AC-ADMIN-03.6` shared).
- `AC-OPS-08.3` Every free-tier line has an alert or a documented manual check for its limiting resource.
- `AC-OPS-08.4` The AI cap is set in every environment, and production's value is deliberate rather than the default.

**Tests.**
- `T-OPS-08.1` `tests/spec/test_cost_doc.py`.
- `T-OPS-08.2` `tests/integration/test_signup_gate.py` (shared).
- `T-OPS-08.3` `tests/spec/test_freetier_alerts.py`.
- `T-OPS-08.4` `tests/spec/test_env_parity.py` (shared).
