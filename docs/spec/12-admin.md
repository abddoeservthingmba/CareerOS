# 12 — Operator Admin

**Module:** `apps/api/app/modules/admin`
**Track:** R1 except §4 (`ADMIN-04`, R2) and §5 (`ADMIN-05`, R2)
**Depends on:** every other module's public API (read-only, plus explicit control actions)
**Requirements:** `ADMIN-01` … `ADMIN-06`
**Public API:** `AdminService.*`
**Publishes:** none. **Consumes:** none.

There is one operator: you. The test of this module is whether you can run the product for a week without opening a Mongo shell or reading a log by hand. Everything here exists because the alternative is a database client at 11 p.m.

---

## 1. Connector dashboard — `ADMIN-01`

**Objective.** See, on one screen, whether jobs are flowing and which source is broken.

**Constraints.**
- Per connector: display name, enabled state, circuit state (`closed`/`open`/`half_open`), last run time and outcome, and for the last run: queries issued, items fetched, new, updated, deduped into existing, normalize failures, error count. Plus a 14-day sparkline of items fetched and a **compliance review age** with its warning state (`06-connectors.md` §4).
- Actions: toggle enabled (DB flag, effective next run), trigger a run now (`202`, idempotent by `Idempotency-Key`, rate limited 1 per connector per 5 minutes), reset the circuit breaker, and view the last 20 runs with their errors.
- A run's errors are shown as `{stage, code, at, count}` — codes, not raw provider messages (`01-foundations.md` §14). Where a normalize failure occurred, the raw payload id is linked so the payload can be inspected within its 30-day window (`CONN-05`).
- **Company boards** are managed here (`06-connectors.md` §5.3): add a slug, see its last successful fetch and job count, remove it, and see auto-disabled slugs with their reason. This is the one piece of operational data that grows by hand and it needs a UI or it will not be maintained.
- The dashboard reads `connector_runs` only; it never triggers a fetch to compute a number.
- An `open` circuit or a review age over 180 days is visually unmissable, not a subtle badge.

**Inputs.** `connector_runs`; registry metadata; the flags.

**Outputs.** `GET /admin/connectors`, `/admin/connectors/{name}/runs`, `POST /admin/connectors/{name}/toggle`, `/run`, `/reset-circuit`, `GET|POST|DELETE /admin/company-boards`.

**Acceptance criteria.**
- `AC-ADMIN-01.1` The dashboard shows every registered connector, including disabled ones, with all fields above populated from stored runs.
- `AC-ADMIN-01.2` Toggling off stops runs by the next cron period and leaves existing jobs queryable (shared with `AC-CONN-03.5`).
- `AC-ADMIN-01.3` "Run now" is idempotent for 5 minutes and returns `429` beyond the rate limit.
- `AC-ADMIN-01.4` Resetting an open circuit allows the next run to make requests.
- `AC-ADMIN-01.5` Error entries show codes, never a provider's raw message body.
- `AC-ADMIN-01.6` A normalize failure links to a retrievable raw payload inside 30 days and shows a tombstone after.
- `AC-ADMIN-01.7` Adding a company board slug causes the next run to fetch it; an auto-disabled slug is shown with its reason.
- `AC-ADMIN-01.8` A connector with an open circuit or a >180-day review age is rendered in the alert state.
- `AC-ADMIN-01.9` Loading the dashboard makes zero outbound requests to any job source.

**Tests.**
- `T-ADMIN-01.1` `tests/integration/test_admin_connectors.py`.
- `T-ADMIN-01.2` `tests/integration/test_connector_toggle.py` (shared).
- `T-ADMIN-01.3` `tests/integration/test_admin_run_now.py`.
- `T-ADMIN-01.4` `tests/integration/test_circuit_reset.py`.
- `T-ADMIN-01.5` `tests/unit/test_provider_error_logging.py` (shared).
- `T-ADMIN-01.6` `tests/integration/test_raw_payload_link.py`.
- `T-ADMIN-01.7` `tests/integration/test_board_slug_lifecycle.py` (shared).
- `T-ADMIN-01.8` `apps/web/.../connector-status.test.tsx`.
- `T-ADMIN-01.9` `tests/integration/test_admin_no_fetch.py`.

---

## 2. AI usage dashboard — `ADMIN-02`

**Objective.** See the bill forming, by feature, before it arrives. This is what makes the billing isolation in `05-ai-layer.md` §5 credible rather than aspirational.

**Constraints.**
- Aggregations over `ai_usage`: by day, by provider, by model, by feature, and by outcome. For each: request count, input and output tokens, estimated cost, cache-hit rate, p50/p95 latency, and error rate.
- The default view is **cost by feature for the last 14 days**, because that is the number that answers "what is expensive" and therefore "what to cap".
- Shows, prominently: today's spend against `AI_DAILY_COST_CAP_USD`, each feature's spend against its own cap, and the count of `budget_denied` outcomes — a nonzero denial count means users are being degraded and is the signal to raise a cap or fix a loop.
- Separates `:golden` suffixed features (nightly real-provider tests, `05-ai-layer.md` §7) from user-driven spend, so test cost never looks like product cost.
- Flags any `est_cost_usd: null` rows (an unpriced model, `AC-AI-04.3`) with a link to the pricing table.
- Aggregation must be cheap: pre-aggregated by a daily rollup job into a small collection for ranges beyond 7 days, computed live within 7 days. A dashboard that scans 13 months of rows every load is a dashboard that gets disabled.
- Cost figures are labelled **estimated** everywhere, because the provider's invoice is the truth and the difference should not be a surprise.

**Inputs.** `ai_usage`; the pricing table; caps.

**Outputs.** `GET /admin/ai-usage?from=&to=&group_by=`; the rollup collection.

**Acceptance criteria.**
- `AC-ADMIN-02.1` Every grouping returns figures that match a direct aggregation over seeded rows.
- `AC-ADMIN-02.2` Today's spend shown equals the sum of today's `est_cost_usd` (`AC-AI-04.5` shared).
- `AC-ADMIN-02.3` `budget_denied` counts are displayed per feature and are nonzero after a deliberate cap trip.
- `AC-ADMIN-02.4` `:golden` spend is excluded from the product-spend totals and shown separately.
- `AC-ADMIN-02.5` Unpriced-model rows are flagged with a count.
- `AC-ADMIN-02.6` A 13-month range loads from rollups in under 1 s at 500k underlying rows.
- `AC-ADMIN-02.7` Every cost figure is labelled as an estimate.

**Tests.**
- `T-ADMIN-02.1`/`.2` `tests/integration/test_admin_ai_dashboard.py`.
- `T-ADMIN-02.3` `tests/integration/test_budget_trip_e2e.py` (shared).
- `T-ADMIN-02.4` `tests/integration/test_golden_spend_separation.py`.
- `T-ADMIN-02.5` `tests/ai/test_unpriced_model.py` (shared).
- `T-ADMIN-02.6` `tests/integration/test_usage_rollup.py`.
- `T-ADMIN-02.7` `apps/web/.../ai-usage.test.tsx`.

---

## 3. Feature flags — `ADMIN-03`

**Objective.** Turn something off in ten seconds without a deploy. This is the mechanism the whole R1/R2 split leans on.

**Constraints.**
- Resolution order: DB override → env `FLAG_*` → code default, cached 30 s (`01-foundations.md` §2).
- The R1 flag set, each with its default and its blast radius documented in the UI: `llm_rationale_enabled` (false in prod), `job_enrichment_enabled` (true), `ocr_enabled` (false), `extension_apply_enabled` (false, R3), `digest_enabled` (false, R2), `push_enabled` (false, R2), `signup_enabled` (true, and the invite-only gate D10), `ingestion_enabled` (true — a global kill switch for all connectors, which is the one you will actually want at 2 a.m.).
- Every flag change writes an `audit_log` `admin_action` row with the old and new value and the operator id.
- A flag the code does not know is rejected on write, so a typo cannot silently do nothing.
- Flags are booleans only. A flag that wants a value is configuration, and configuration is a deploy — this keeps the flag surface small and its semantics obvious.
- The UI lists every known flag with its resolved value and **where that value came from** (DB, env, or default), because the commonest flag confusion is an env value silently overriding an expectation.

**Inputs.** `GET|PUT /admin/flags/{key}`.

**Outputs.** `feature_flags` documents; audit rows.

**Acceptance criteria.**
- `AC-ADMIN-03.1` Every flag in the R1 set is listed with its resolved value and its source.
- `AC-ADMIN-03.2` A DB override takes effect within 30 s and removing it reverts to env or default (`AC-FOUND-02.5` shared).
- `AC-ADMIN-03.3` An unknown flag key is rejected `422`.
- `AC-ADMIN-03.4` Every change writes an audit row with old value, new value, and operator.
- `AC-ADMIN-03.5` Setting `ingestion_enabled: false` stops every connector's next run.
- `AC-ADMIN-03.6` Setting `signup_enabled: false` returns `403 signups_closed` from registration and Google sign-in for new accounts, while existing users are unaffected.

**Tests.**
- `T-ADMIN-03.1` `tests/integration/test_admin_flags.py`.
- `T-ADMIN-03.2` `tests/integration/test_feature_flags.py` (shared).
- `T-ADMIN-03.3` `tests/integration/test_unknown_flag.py`.
- `T-ADMIN-03.4` `tests/integration/test_admin_audit.py`.
- `T-ADMIN-03.5` `tests/integration/test_ingestion_kill_switch.py`.
- `T-ADMIN-03.6` `tests/integration/test_signup_gate.py`.

---

## 4. Skill alias and taxonomy management — `ADMIN-04` — **Track: R2**

**Objective.** Grow the vocabulary from what real listings and real resumes actually say.

**Constraints.** Three reports, each with an action:
- **Unmapped skills** (`03-profile.md` §4): the string, its occurrence count, whether it came from resumes or listings, with "map to canonical" and "create canonical" actions. Ordered by count, because the top twenty are most of the value.
- **Unmatched titles** (`07-ingestion-and-jobs.md` §4): titles falling to `title_family: other`, with counts, and a "propose a rule" action that writes a candidate regex into a review file rather than applying it live — a bad title rule mis-scores every job it touches, so this one stays a code change with a test.
- **Unresolved locations**: raw location strings that produced no country.

Mapping an alias triggers a bounded backfill: re-canonicalize affected profiles and jobs, then rescore the affected pairs. The backfill is a queued task with a visible progress state, because mapping a common alias can touch thousands of documents.

**Acceptance criteria.** `AC-ADMIN-04.1` Each report shows counts and sources, ordered by count. `AC-ADMIN-04.2` Mapping an alias triggers the backfill and rescore for exactly the affected documents. `AC-ADMIN-04.3` A title rule proposal writes to a review file and changes no live behaviour. `AC-ADMIN-04.4` Every action is audited. `AC-ADMIN-04.5` A no-chain invariant is enforced: an alias cannot point at another alias (`AC-PROF-06.6` shared).
**Tests.** `T-ADMIN-04.1`–`.5` `tests/integration/test_admin_taxonomy.py`.

---

## 5. Flagged listings queue — `ADMIN-05` — **Track: R2**

**Objective.** Act on user reports of scams quickly, because a scam listing that stays visible is the fastest way to lose a user.

**Constraints.** Queue of jobs with `flagged.count > 0`, ordered by count then recency, showing each reason and the reporter count (never reporter identities). Actions: **confirm** (sets `status: flagged` permanently, applies the −50 scoring penalty, removes from search, and records the decision), **dismiss** (clears flags, restores the job, records the decision), or **escalate to source** (records that the source was notified — some boards act on reports, and the record matters if a pattern emerges with one source). Every decision is audited with the operator id. A confirmed scam pattern (the same company name across multiple flagged listings) is surfaced as a grouped suggestion.

**Acceptance criteria.** `AC-ADMIN-05.1` The queue shows flagged jobs with reasons and counts and no reporter identity. `AC-ADMIN-05.2` Confirming removes the job from search and applies the penalty (`AC-JOB-10.3` shared). `AC-ADMIN-05.3` Dismissing restores it and records the decision (`AC-JOB-10.4` shared). `AC-ADMIN-05.4` Repeat company names across flagged listings are grouped. `AC-ADMIN-05.5` Every decision is audited.
**Tests.** `T-ADMIN-05.1`–`.5` `tests/integration/test_flagged_queue.py`.

---

## 6. Role gating and the admin surface — `ADMIN-06`

**Objective.** The admin surface is not discoverable, not reachable, and not confusable with the product.

**Constraints.**
- `role: "operator"` on the user document. There is no third role and no permission matrix in R1 — one operator does not need one, and building one now guarantees it is wrong when a second person arrives.
- Every `/admin` route requires the role and returns **404 to everyone else** (`02-auth-and-account.md` §6) — not 403, so the surface is not enumerable.
- The web client puts admin in a separate route group with its own layout and its own lazily-loaded bundle: an ordinary user's bundle contains no admin code, so the screens cannot leak through a bug or be read out of the JavaScript.
- There is **no admin surface in the mobile app at all**. Nothing to gate, nothing to review in a store submission.
- Every admin mutation writes `audit_log` `admin_action` with the operator id, the action, the target, and before/after values where applicable.
- Admin routes may read any user's data, and that is exactly why every such read is audited too, at a coarser granularity: reading a specific user's profile or applications writes an audit row. Being able to answer "did I look at someone's data" matters even with one operator.
- Optional IP allowlist via config for `/admin` (`16-security-and-compliance.md` §2), off by default.
- The operator role is granted only by a database change or a documented CLI command, never through the API. There is no "promote user" endpoint.

**Inputs.** Auth context.

**Outputs.** Gated routes; audit rows.

**Acceptance criteria.**
- `AC-ADMIN-06.1` Every `/admin` route returns 404 for a non-operator, enumerated from the OpenAPI document (`AC-AUTH-10.2` shared).
- `AC-ADMIN-06.2` The production web bundle for a non-admin route contains no admin component code (asserted against the built chunks).
- `AC-ADMIN-06.3` The mobile app contains no admin screen or admin API call (static check).
- `AC-ADMIN-06.4` Every admin mutation writes an audit row with before/after values.
- `AC-ADMIN-06.5` Reading an individual user's data through an admin route writes an audit row naming the operator and the target.
- `AC-ADMIN-06.6` No API endpoint can grant the operator role.
- `AC-ADMIN-06.7` With the IP allowlist configured, a request from outside it returns 404 even for the operator.

**Tests.**
- `T-ADMIN-06.1` `tests/integration/test_cross_tenant_sweep.py` (shared).
- `T-ADMIN-06.2` `.github/workflows/web-ci.yml` step `bundle-isolation` + `apps/web/scripts/check-admin-chunk.mjs`.
- `T-ADMIN-06.3` `tests/spec/test_no_admin_in_mobile.py`.
- `T-ADMIN-06.4`/`.5` `tests/integration/test_admin_audit.py`.
- `T-ADMIN-06.6` `tests/spec/test_no_role_grant_endpoint.py`.
- `T-ADMIN-06.7` `tests/integration/test_admin_ip_allowlist.py`.
