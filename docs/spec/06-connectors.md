# 06 — Connector Framework

**Module:** `apps/api/app/connectors`
**Track:** R1 except §5 (the six additional connectors, R2)
**Depends on:** `01-foundations.md` §4, §10; `17-data-model.md` §2.6–2.7
**Depended on by:** `07-ingestion-and-jobs.md` only
**Requirements:** `CONN-01` … `CONN-07`
**Public API:** `connectors/__init__.py` exports `BaseConnector`, `ConnectorMeta`, `RawListing`, `JobDraft`, `SearchQuery`, `HealthStatus`, `registry`
**Constraint that defines this module:** `connectors/*` may not import `modules/*` or `ai/*` (`01-foundations.md` §4). A connector fetches and maps. It does not enrich, deduplicate, embed, or persist.

This is objective O6 from the brief: a source can be added, disabled, or removed without touching core modules. That is a testable claim, and §6 is how it is tested.

---

## 1. The connector contract — `CONN-01`

**Objective.** One interface that every source satisfies, narrow enough that a new connector is a mapping exercise rather than a design exercise.

**Constraints.**

```python
class ConnectorMeta(BaseModel):
    name: str                      # slug, matches the package directory
    display_name: str              # shown to users as attribution
    terms_url: str
    attribution: str               # exact required attribution string, per the source's terms
    requires_api_key: bool
    key_env_var: str | None
    rate_limit_per_min: int
    supports_location_filter: bool
    supports_keyword_filter: bool
    supports_cursor: bool
    regions: list[str]             # ISO2 codes, or "GLOBAL"
    listing_ttl_days: int | None    # source-imposed cache limit, if any

class BaseConnector(ABC):
    meta: ConnectorMeta
    def __init__(self, http: AsyncClient, api_key: str | None) -> None: ...
    async def fetch(self, q: SearchQuery, cursor: str | None) -> tuple[list[RawListing], str | None]: ...
    def normalize(self, raw: RawListing) -> JobDraft: ...          # PURE. No I/O, no clock, no randomness.
    async def healthcheck(self) -> HealthStatus: ...
```

- `normalize` is **pure and synchronous**. No network, no `clock.now()`, no random, no database. This is what makes a connector testable from a recorded fixture, and it is asserted (`AC-CONN-01.3`).
- The HTTP client and the API key are **injected**. A connector never constructs a client (so timeouts, proxies, and instrumentation are uniform) and never reads the environment (`01-foundations.md` §2).
- `JobDraft` is the canonical `Job` (`17-data-model.md` §2.6) minus every derived field: no `dedup_key`, no `simhash`, no `title_family`, no `seniority`, no canonical skills, no embedding, no status. A connector that sets a derived field fails validation — those belong to the ingestion service, and letting a connector guess them is how two sources end up with different taxonomies.
- `normalize` must be **total**: given a `RawListing` the source could plausibly emit, it either returns a valid `JobDraft` or raises `NormalizationError` with the offending field path. It never returns a half-populated draft with silent nulls in required fields.
- Required fields on `JobDraft`: `source`, `external_id`, `url`, `apply_url`, `title`, `company.name`, `location.raw`, `description_text`, `posted_at`. Everything else is optional and explicitly nullable.
- `fetch` respects `cursor` semantics: if `supports_cursor` is false, the connector pages internally and returns `None`, and the ingestion service must not assume otherwise.
- `healthcheck` performs the cheapest authenticated call the source offers and returns `{ok, latency_ms, detail, checked_at}`. It never counts against the ingestion rate budget in a way that starves fetching.
- Timeouts: connect 5 s, read 20 s, total 30 s per request, set by the injected client.

**Inputs.** `SearchQuery{keywords[], title_family, location, country, remote_only, posted_within_days, limit}`.

**Outputs.** `RawListing{connector, external_id, payload, fetched_at}` and `JobDraft`.

**Acceptance criteria.**
- `AC-CONN-01.1` Every connector class in the registry satisfies the ABC and has a valid `ConnectorMeta`.
- `AC-CONN-01.2` `normalize` on every recorded fixture for every connector produces a `JobDraft` that validates, or raises `NormalizationError` — never returns an invalid draft.
- `AC-CONN-01.3` `normalize` is pure: a static check finds no `await`, no import of `httpx`/`app.core.clock`/`random`/`app.infra` in any connector's `mapping.py`, and calling it twice returns equal output.
- `AC-CONN-01.4` A `JobDraft` with a derived field set (`dedup_key`, `title_family`, `seniority`, `simhash`, `embedding`, `status`) is rejected.
- `AC-CONN-01.5` A connector constructing its own HTTP client or reading `os.environ` fails a static check.
- `AC-CONN-01.6` `healthcheck` for every enabled connector returns within 10 s in the integration environment (against recorded responses).
- `AC-CONN-01.7` Every required field is non-null in every fixture-derived draft.

**Tests.**
- `T-CONN-01.1` `tests/connectors/test_registry_contract.py`.
- `T-CONN-01.2`/`.7` `tests/connectors/test_normalize_fixtures.py`, parametrized over every connector × every fixture.
- `T-CONN-01.3` `tests/spec/test_normalize_purity.py`.
- `T-CONN-01.4` `tests/unit/test_jobdraft_validation.py`.
- `T-CONN-01.5` `tests/spec/test_connector_injection.py`.
- `T-CONN-01.6` `tests/connectors/test_healthchecks.py`.

---

## 2. Isolation, and the sources that are excluded — `CONN-02`, HR-2

**Objective.** Make the legal rule an architectural one, so that adding a prohibited scraper requires deleting a test rather than forgetting a policy.

**Constraints.**
- Core modules import `connectors.base` and `connectors.registry` only. No module names a connector. Discovery is by package scan of `connectors/` plus the `connectors.yaml` enable list.
- **The framework ships no HTML-parsing base class and no HTML parser dependency in the connector path.** There is no `BeautifulSoup`, no `lxml.html`, no `selectolax` import reachable from `connectors/`. A connector that wanted to scrape would have to add a dependency, which is visible in a lockfile diff and blocked by a test.
- Explicitly excluded, by name, in `connectors/EXCLUDED.md` with the reason and the date checked: LinkedIn, Naukri, Indeed (HTML), Glassdoor, Instahyre, Monster, Shine, and Google Jobs SERP results. Each entry names the clause of the source's terms that prohibits automated access.
- The exclusion list is not a suggestion: a connector whose `meta.name` or whose base URL matches an excluded source fails at registry load.
- Headless browsers are absent from the whole API image. No Playwright, no Selenium, no Puppeteer in `apps/api` dependencies. (The web app's Playwright is a dev dependency of `apps/web` only and cannot reach production code.)

**Inputs.** `connectors.yaml`; `EXCLUDED.md`.

**Outputs.** The registry; CI gates.

**Acceptance criteria.**
- `AC-CONN-02.1` No file under `app/modules/` names any connector (shared with `AC-FOUND-01.3`).
- `AC-CONN-02.2` Disabling every connector in `connectors.yaml` leaves the API booting and every non-ingestion test passing.
- `AC-CONN-02.3` Adding a new connector package requires no edit to any file under `app/modules/` — proven by the drill in §6.
- `AC-CONN-02.4` No HTML-parsing library and no browser-automation library is importable from `connectors/` or present in the API's production dependency set (HR-2).
- `AC-CONN-02.5` `EXCLUDED.md` lists every excluded source with a terms clause reference and a checked date within 180 days.
- `AC-CONN-02.6` A connector whose base URL matches an excluded host fails registry load with a clear error.

**Tests.**
- `T-CONN-02.1` `tests/spec/test_layer_leaks.py` (shared).
- `T-CONN-02.2` `tests/integration/test_no_connectors_enabled.py`.
- `T-CONN-02.3` `tests/spec/test_connector_addition_drill.py`.
- `T-CONN-02.4` `tests/spec/test_no_scraping_deps.py` — parses `uv.lock` and greps the import graph.
- `T-CONN-02.5` `tests/spec/test_excluded_sources_doc.py`.
- `T-CONN-02.6` `tests/connectors/test_excluded_host_guard.py`.

---

## 3. Reliability: limits, retries, circuit breaker — `CONN-03`

**Objective.** One failing or throttling source degrades only itself.

**Constraints.**
- Per-connector token-bucket rate limiter in Redis, keyed by connector name, at `meta.rate_limit_per_min`. Shared across worker processes — a limiter that is per-process is not a limiter.
- Retries: 3 attempts, exponential backoff with full jitter, only on 429, 5xx, and transport errors. **Never** on 4xx other than 429 — retrying a 400 is a bug amplifier. `Retry-After` is honoured when present, up to 120 s.
- Circuit breaker per connector: `closed → open` after 5 consecutive failed **runs** (not requests), `open` for 30 minutes, then `half_open` for one probe run. Opening writes a `connector_runs` row with `circuit_state: open`, sets the connector's admin status, and alerts (`15-infra-and-ops.md` §4).
- A connector's failure never fails the parent ingestion run: `ingest.run` handles one connector, and connectors run as separate cron jobs, so isolation is structural rather than defensive.
- Enable/disable is a DB-backed flag readable in the admin UI, taking effect on the next run without a deploy. A disabled connector's existing jobs are **not** deleted — they age out by the staleness rule (`07-ingestion-and-jobs.md` §6), because deleting them would strand applications.
- Every outbound request carries a descriptive `User-Agent` naming the product and a contact URL. Some sources require it; all sources deserve it.

**Inputs.** Run outcomes; config; the flag.

**Outputs.** `connector_runs` rows; circuit state; metrics `connector_run_outcome`, `connector_items`, `connector_latency`.

**Acceptance criteria.**
- `AC-CONN-03.1` With two worker processes, the combined request rate to one connector does not exceed its limit over a 60-second window.
- `AC-CONN-03.2` A 429 with `Retry-After: 30` results in a wait of ≥30 s before the retry; a 400 results in zero retries.
- `AC-CONN-03.3` Five consecutive failed runs open the circuit; the sixth run exits immediately without an HTTP request; after 30 minutes exactly one probe request is made.
- `AC-CONN-03.4` A connector raising in `fetch` does not prevent other connectors' scheduled runs from completing in the same period.
- `AC-CONN-03.5` Disabling a connector stops its runs within one cron period and leaves its jobs queryable.
- `AC-CONN-03.6` Every outbound request has the configured `User-Agent`.

**Tests.**
- `T-CONN-03.1` `tests/integration/test_connector_rate_limit.py` (two worker processes).
- `T-CONN-03.2` `tests/connectors/test_retry_policy.py`.
- `T-CONN-03.3` `tests/integration/test_circuit_breaker.py` (frozen clock).
- `T-CONN-03.4` `tests/integration/test_connector_isolation.py`.
- `T-CONN-03.5` `tests/integration/test_connector_toggle.py`.
- `T-CONN-03.6` `tests/connectors/test_user_agent.py`.

---

## 4. Compliance record and attribution — `CONN-04`, `CONN-05`, `CONN-07`

**Objective.** For every source, be able to answer "are we allowed to do this, and when did we last check" without opening a browser.

**Constraints.**
- Every connector package contains `COMPLIANCE.md` with a fixed set of headings, all required: **Source**, **Terms URL**, **Access method** (documented API / public feed), **Permitted use**, **Attribution requirement** (the exact string), **Rate limits stated by the source**, **Caching/retention limits stated by the source**, **Personal data received**, **Last reviewed** (ISO date), **Reviewed by**.
- A connector without a valid `COMPLIANCE.md` fails registry load. This is deliberate friction: it is the only mechanism that makes the paperwork happen at the moment the connector is written.
- `meta.attribution` must equal the attribution string in `COMPLIANCE.md`, checked at load.
- The admin dashboard shows review age; >180 days raises a warning and >365 days disables the connector automatically (`12-admin.md` §1).
- `meta.listing_ttl_days`, where a source imposes one, is enforced by the retention rule in `17-data-model.md` §5 — a job from a source with a 30-day cache limit expires at 30 days regardless of whether it is still listed.
- **Attribution is rendered on every job card and every job detail view**, in both clients, alongside a "view original" link to `source_refs[].url`. Not in a footer, not on hover — on the card. After a cross-source merge, every contributing source is attributed.
- `raw_listings` retains payloads 30 days (`CONN-05`) for debugging normalizers. Payloads may contain the source's full description; they are covered by the same retention and deletion rules as any other data.

**Inputs.** `COMPLIANCE.md` files; `meta`.

**Outputs.** Load-time validation; the admin review-age view; UI attribution.

**Acceptance criteria.**
- `AC-CONN-04.1` A connector package missing `COMPLIANCE.md`, missing a required heading, or with an unparseable `Last reviewed` date fails registry load with a message naming the connector and the problem.
- `AC-CONN-04.2` `meta.attribution` differing from the document's attribution string fails load.
- `AC-CONN-04.3` A review date older than 365 days marks the connector disabled at load; between 180 and 365 days it loads with a warning surfaced in admin.
- `AC-CONN-04.4` Every job card and detail view in both clients renders the attribution string and a working "view original" link, for a merged job showing every contributing source (component tests, both clients).
- `AC-CONN-04.5` A source with `listing_ttl_days: 30` has its jobs expired at 30 days even while still being returned by the source.
- `AC-CONN-05.1` A raw payload is retrievable for 30 days and absent at 31 (TTL index).

**Tests.**
- `T-CONN-04.1`–`.3` `tests/connectors/test_compliance_records.py`.
- `T-CONN-04.4` `apps/web/.../job-card.test.tsx`, `apps/mobile/test/job_card_test.dart`.
- `T-CONN-04.5` `tests/integration/test_source_ttl.py`.

**Attribution, stated against its own requirement.**
- `AC-CONN-07.1` Every job card and job detail view in both clients shows the source's exact `attribution` string and a working link to the original posting; a merged job shows one entry per contributing source (`AC-CONN-04.4` shared).
- `AC-CONN-07.2` A job whose only source has been disabled still renders its stored attribution rather than a blank.
- `T-CONN-07.1`–`.2` `apps/web/.../job-card.test.tsx`, `apps/mobile/test/job_card_test.dart`, `tests/integration/test_attribution_persistence.py`.
- `T-CONN-05.1` `tests/integration/test_ttl_indexes.py` (shared).

---

## 5. The connector set — `CONN-06`

**Objective.** Three shapes in R1 that between them exercise every branch of the framework; six more in R2 for coverage.

### 5.1 R1 — three connectors

| Connector | Access | Coverage | Key | Why this one is in R1 |
|---|---|---|---|---|
| `adzuna` | Documented API | India + ~15 countries | Yes, free app id/key | The best India coverage available through a documented API, and it exercises the keyed, paginated, location-filtered path |
| `remotive` | Public JSON API | Global remote, tech-heavy | No | Keyless, no location filter, returns everything and requires client-side filtering — the opposite shape from Adzuna, which is the point |
| `greenhouse_board` | Public board API per company | Per curated company | No | The per-company shape: one connector instance fanning out over a configured list of board slugs. Exercises multi-target fetch and the "no search filter at all" case |

Each of the three differs in keying, in filtering, and in pagination. A framework that handles all three handles the R2 six.

### 5.2 R2 — six more — **Track: R2**

`jooble` (keyed aggregator; makes fuzzy dedup earn its keep against Adzuna), `arbeitnow` (public, carries a visa-sponsorship flag worth surfacing), `himalayas` (public, unusually good structured salary), `lever_postings` (per-company, second board family), `ashby_board` (per-company, common among startups), `rss_generic` (config-driven field mapping for any permitted feed; **SSRF-guarded** per `16-security-and-compliance.md` §2 — allowlisted hosts only, private IP ranges resolved and blocked, no redirects to new hosts).

### 5.3 Constraints

- Company boards (`greenhouse_board`, later `lever_postings`, `ashby_board`) read their slug list from `company_boards` config managed in admin (`12-admin.md` §1). A slug that 404s three consecutive runs is auto-disabled with a note, because companies delete boards and a dead slug should not look like a connector failure.
- Every connector's fixtures are **recorded from real responses** once, scrubbed of anything identifying, and committed. Tests never hit a live source; the nightly `real_ai`-style marker `real_source` optionally does, for drift detection.
- Query fan-out per run is capped by `INGEST_MAX_QUERIES_PER_RUN` and allocated by active-user demand (`07-ingestion-and-jobs.md` §2).

**Acceptance criteria.**
- `AC-CONN-06.1` All three R1 connectors are registered, healthchecked, and produce valid drafts from their fixtures.
- `AC-CONN-06.2` Each R1 connector has ≥10 recorded fixtures including at least one each: missing salary, remote listing, malformed date, empty description, and a listing that must raise `NormalizationError`.
- `AC-CONN-06.3` `normalize` branch coverage is 100% of branches reachable from the committed fixtures, for every connector.
- `AC-CONN-06.4` A dead board slug is auto-disabled after three 404 runs with a recorded reason, without opening the connector's circuit.
- `AC-CONN-06.5` No test in the default suite makes a request to a real source host.
- `AC-CONN-06.6` (R2) `rss_generic` refuses a feed URL that resolves to a private IP range, and refuses a redirect to a host outside the allowlist.

**Tests.**
- `T-CONN-06.1` `tests/connectors/test_registry_contract.py` (shared).
- `T-CONN-06.2`/`.3` `tests/connectors/test_normalize_fixtures.py` with a coverage assertion per connector.
- `T-CONN-06.4` `tests/integration/test_board_slug_lifecycle.py`.
- `T-CONN-06.5` `tests/spec/test_no_live_source_calls.py` (respx in strict mode, globally).
- `T-CONN-06.6` `tests/connectors/test_rss_ssrf.py` (R2).

---

## 6. Adding a connector, and the one-hour drill — `CONN-02` (proof)

**Objective.** Make the isolation claim measurable rather than aspirational.

**Constraints.** The developer checklist:

1. `connectors/<name>/` containing `__init__.py`, `connector.py` (fetch, healthcheck), `mapping.py` (pure normalize), `COMPLIANCE.md`.
2. Record fixtures into `tests/connectors/<name>/fixtures/*.json`, scrubbed.
3. Write normalize tests from the fixtures, including one that must raise.
4. Add the entry to `connectors.yaml`: `enabled`, `cron`, `rate_limit`, `key_env_var`, `regions`.
5. `make connector-smoke NAME=<name>` — validates meta, loads compliance, runs healthcheck against fixtures, runs normalize over all fixtures, prints a sample `JobDraft`.
6. Deploy; confirm the first run in the admin dashboard.

**The drill.** The P3 exit gate (`00-scope-and-phases.md` §4) is that a fixture-backed dummy connector goes from nothing to visible in the admin dashboard in **under one hour, timed**, touching no file outside `connectors/`, `tests/connectors/`, and `connectors.yaml`. `T-CONN-02.3` automates the "touching no file outside" half by running the scaffold and asserting the diff's file set; the timing half is recorded by hand in `docs/adr/ADR-007-connector-plugins.md`.

**Inputs.** A source's API documentation.

**Outputs.** A registered connector; a recorded drill result.

**Acceptance criteria.**
- `AC-CONN-02.7` `make connector-smoke NAME=<name>` exists, runs offline, and fails informatively for each of: invalid meta, missing compliance heading, fixture that fails to normalize, attribution mismatch.
- `AC-CONN-02.8` `make new-connector NAME=<name>` scaffolds a connector whose diff touches only the three permitted paths, and whose placeholder tests pass.
- `AC-CONN-02.9` The timed drill result is recorded in ADR-007 with a date and a duration.

**Tests.**
- `T-CONN-02.7` `tests/spec/test_connector_smoke_target.py`.
- `T-CONN-02.8` `tests/spec/test_connector_addition_drill.py` (shared with `T-CONN-02.3`).
- `T-CONN-02.9` `tests/spec/test_adr_present.py`.
