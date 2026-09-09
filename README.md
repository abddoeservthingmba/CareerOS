# JobPilot

A job-search assistant that finds roles worth applying to, explains why each one
scored the way it did, drafts the application, and remembers to follow up.

It never submits an application on your behalf and it never scrapes a source
that prohibits it. Those two are product-defining rather than configurable — see
[Hard rules](#hard-rules).

**This repository is built from a specification, not from a backlog.**
[`docs/spec/`](docs/spec/) is the contract: it says what to build, in what
order, and how to prove it is done. If the code and the specification disagree,
one of them is a bug and the disagreement gets recorded rather than resolved
quietly. [`CLAUDE.md`](CLAUDE.md) is the operating loop.

---

## Where this actually is

Honest version, because the interesting failure mode of a spec-driven build is a
README that describes the specification and calls it progress.

| | |
|---|---|
| **Phase** | P0 substantially built; **P1 at 2 of 14 requirements** |
| **API endpoints** | **one** — `POST /api/v1/auth/register` |
| **Tests** | 1976 passing |
| **Web client** | a design preview from committed fixtures; nothing is wired to the API |
| **Mobile client** | not started |

The seven phases and their requirement counts, from
[`BUILD-ORDER.md`](docs/spec/BUILD-ORDER.md):

| Phase | What it delivers | Requirements | State |
|---|---|---|---|
| **P0** | Infrastructure proving | 45 | substantially built — gaps listed below |
| **P1** | Identity and account | 14 | **2 built** (`AUTH-01`, `AUTH-09`) |
| **P2** | Candidate intelligence — résumé, profile | 14 | not started |
| **P3** | Job engine — connectors, ingestion | 17 | not started |
| **P4** | Matching — scoring, the feed, explanations | 11 | not started |
| **P5** | Application engine — packs, answers | 9 | not started |
| **P6** | Tracker and reminders | 8 | not started |
| **P7** | R1 closeout | 4 | not started |

P0 builds no features deliberately. Its exit criterion is that a commit reaches
staging unattended and both clients render live health from it — the plumbing,
proved, before anything is built on it.

### What "built" means here

Every section of the specification is `built`, `built-off`, `stub-501` or
`absent`. There is no fifth state ([`01-foundations.md`](docs/spec/01-foundations.md) §15).
[`docs/spec/status.yaml`](docs/spec/status.yaml) is generated, and it currently
reports 159 built and 29 absent — but **most of those carry no explicit status
line**, so their state is derived from a track annotation rather than verified.
Treat the table above as the real answer and `status.yaml` as the machine's
best guess until `FOUND-15`'s declarations are filled in.

---

## Architecture

**One image, two entrypoints.** The same container runs the API or the worker,
selected by the command and never by an environment variable, so a misconfigured
variable cannot start the wrong process (ADR-002).

```
docker run <image> api      # uvicorn, 2 workers
docker run <image> worker   # arq app.worker.WorkerSettings
```

**Modules do not import each other.** Nine feature modules under
`apps/api/app/modules/`, each with the same anatomy, each independent. They
communicate through in-process events (`core/events.py`) whose handlers do
nothing but enqueue a task — so a publisher's latency does not grow with the
number of subscribers. `import-linter` enforces 16 contracts with zero
exemptions; `make lint-imports` is the check.

**Layers, strictly.**

| Layer | May import | Rule |
|---|---|---|
| `router.py` | its own service, `core` | validate → one service call → response. No business `if` |
| `service.py` | `core`, `infra`, `ai`, its own module | the only place business rules live. Never `fastapi`, never `pymongo` |
| `repository.py` | its own `models.py`, `core` | every Mongo detail, index choices included |
| `models.py` | `core`, `shared` | Beanie documents. Never returned from a route |
| `infra/`, `ai/` | nothing above them | leaves. They open connections and call providers |

**The AI provider is behind a protocol** with a fake implementation, a per-feature
budget, and a degradation matrix that says what each feature does when its cap is
spent. No feature errors because a budget ran out; each degrades in a documented
way ([`ai-budget.yaml`](docs/spec/ai-budget.yaml)).

### Stack

| | |
|---|---|
| API | FastAPI, Python 3.12, `uv` |
| Data | MongoDB Atlas via Beanie, Redis for the queue and rate limits, S3-compatible object storage |
| Worker | ARQ |
| Web | Vite, React 19, TypeScript strict |
| Mobile | Flutter (P7) |

---

## Layout

```
apps/api/          FastAPI app and worker — one image, two entrypoints
  app/core/          config, errors, events, ids, clock, ratelimit, passwords, idempotency
  app/shared/        primitives: money, location, skills, emails, pagination, ulid
  app/infra/         mongo, redis, storage, email, breaches — connection-openers only
  app/ai/            provider protocol, registry, budget, prompts
  app/modules/       auth admin apply jobs matching notifications profile resume tracker
apps/web/          the Vite client
packages/contracts/ openapi.json and generated clients — written by CI only
infra/scripts/     the spec gates (specgate), tasks.py, generators
docs/spec/         the specification. Read this first
docs/adr/          architecture decisions
```

---

## Running it

Docker is not required and, on the machine this was built on, not possible —
virtualization is disabled, which is why `infra/scripts/run_api.py` exists.

```bash
cp .env.example .env          # then fill it in; .env is gitignored
make install                  # create the API virtualenv from uv.lock
make api                      # http://localhost:8000
make web                      # http://localhost:5173
```

`.env.example` is the authoritative variable list and is asserted to match
`Settings` exactly, in both directions. A missing required variable aborts the
boot naming the variable.

### The gate

```bash
make check          # lint, import contracts, types, tests — all four, or the work is not done
make check-spec     # the specification gates: traceability, closure, status registry
make bundle REQ=AUTH-02   # the files needed for one requirement, and nothing else
```

`make check` is not advisory. A requirement is done when its acceptance criteria
have tests at the paths the specification names and this is green.

---

## Deployments

| | Where | State |
|---|---|---|
| Web | Vercel — `career-os-rho-one.vercel.app` | live; serves the design preview |
| API | Render, from `render.yaml` | deploys; **needs a real Redis** |

Both are off the specified path. [`15-infra-and-ops.md`](docs/spec/15-infra-and-ops.md) §2
puts the web client on Cloudflare Pages and the API on one small VPS behind
Cloudflare (D3). Two criteria do not hold as a result, and they are recorded in
`render.yaml` rather than left to be discovered: `AC-OPS-01.1`'s read-only root
filesystem, which Render does not expose, and `AC-OPS-02.1`'s Cloudflare-only
origin — the API serves a Render hostname directly, so there is no WAF and no
coarse rate limit in front of it.

`APP_ENV=staging`, because D1 is unsettled and the production deploy is blocked
until the product name is decided.

---

## Hard rules

Twelve of them, in [`docs/spec/README.md`](docs/spec/README.md) §2, each with a
passing enforcement test. They override anything inferred from a code sample.
The two that define the product:

- **HR-1** — nothing is ever submitted to a third-party site on a user's behalf.
- **HR-2** — no scraping of a prohibited source.

There is no flag that turns either off.

Three more that are easy to violate by accident: money is a minor-unit integer,
never a float; every stored datetime is timezone-aware UTC, with local time only
at reminder scheduling and rendering; and an ownership failure answers **404,
not 403**, because 403 confirms the row exists.

---

## Known gaps

Stated here so they are not rediscovered.

**P0 is not finished.**

- No `infra/docker-compose.yml` and no `make up`. The Dockerfile exists and has
  never been built locally — Render's build was its first.
- `OPS-01`'s image tests are unwritten: `tests/integration/test_readyz.py`,
  `test_compose_boot.py`, and the `image-audit` / `image-entrypoints` /
  `layer-cache-check` steps in `api-ci.yml`.
- `.github/workflows/` has `api-ci`, `contracts` and `nightly-ai`. Missing:
  `web-ci`, `mobile-ci`, `deploy-staging`, `deploy-prod`. **Nothing builds
  `apps/web` before Vercel does.**
- `docs/adr/` holds ADR-011 … ADR-014. The R1 gate requires ADR-001 … ADR-010.
- `T-FOUND-09.4`'s `tests/integration/test_event_wiring.py` is unwritten.

**Blocking the next requirement.**

- **Redis is a placeholder on the deployment.** `AUTH-09`'s limiter is wired
  into `/register` and fails closed by design, so registration returns 503 in
  production until a real instance exists.
- **No email can be sent.** `MemorySender` and `SmtpSender` are built;
  `resend` and `ses` are declared-but-unbuilt. `AUTH-02`'s exit criterion is
  *sign up → verify → login*, so **D7 has to be settled before P1 can finish**.

**Recorded deviations.** Four, each explained where it lives, and three of them
still need the specification updated to match:

| Deviation | Where | Spec edit owed |
|---|---|---|
| `UserRegistered` / `UserDeletionRequested` added to §9's event table | `01-foundations.md` §9 | **done** |
| A sliding-window log instead of §9's "Redis token bucket" | `core/ratelimit.py` | `02` §9's first constraint |
| `TRUSTED_PROXY_CIDRS` — §9 admits no configuration for the client-IP rule | `core/config.py` | `02` §9, `15` §5's variable list |
| `REGISTER_MIN_MILLIS` — the mechanism for `AC-AUTH-01.4`'s timing clause | `core/config.py` | none; §1 states the property, not the means |

One inconsistency, unresolved: `core/consent.py` has `CONSENT_VERSION = 1`
while [`17-data-model.md`](docs/spec/17-data-model.md) §2.1 shows
`"version": "2026-09-01"` and `ConsentRecord.version` is a `str`.

---

## Reading order

1. [`docs/spec/README.md`](docs/spec/README.md) — the contract, the ID conventions, the twelve hard rules
2. [`docs/spec/00-scope-and-phases.md`](docs/spec/00-scope-and-phases.md) — tracks, phases, gates, and the open decisions
3. [`docs/spec/01-foundations.md`](docs/spec/01-foundations.md) — the conventions every module obeys
4. [`docs/spec/17-data-model.md`](docs/spec/17-data-model.md) — the schema contract
5. [`docs/spec/BUILD-ORDER.md`](docs/spec/BUILD-ORDER.md) — then work one requirement at a time
