# 07 — Ingestion, Normalization and Job Search

**Module:** `apps/api/app/modules/jobs`
**Track:** R1 except §7.1 (`JOB-07`, R2) and §7.2 (`JOB-10`, R2)
**Depends on:** `06-connectors.md`, `03-profile.md` §4 (canonicalize), `05-ai-layer.md`, `17-data-model.md` §2.6–2.7
**Requirements:** `JOB-01` … `JOB-10`
**Public API:** `JobService.search`, `.get`, `.hide`, `.report`, `IngestService.run`, `.mark_stale`
**Publishes:** `JobsIngested`, `JobExpired`. **Consumes:** none.

The connector's job is to hand over a `JobDraft`. Everything that makes a draft comparable to other drafts — taxonomy, dedup, skills, embedding, persistence — happens here, in one place, so that two sources cannot disagree about what a "senior backend role in Bengaluru" is.

---

## 1. The canonical job — `JOB-01`

**Objective.** One document shape that scoring, search, and the UI all read, where every field is either normalized or explicitly marked as raw.

**Constraints.**
- Shape and enumerations: `17-data-model.md` §2.6. The three deliberate changes from BRD v1.0 Appendix A (`apply_url` inside `source_refs[]`, stored `simhash`/`unseen_runs`, `skills_source`) are stated there with reasons.
- Every field is in exactly one of three classes, and the class is documented per field: **as-supplied** (`title`, `description_text`, `location.raw`), **normalized** (`title_family`, `seniority`, `location.city/country`, `salary`, `employment_type`), or **derived by us** (`required_skills`, `simhash`, `embedding`, `quality_flags`). Scoring reads only the second and third classes; the UI shows the first.
- `description_text` is capped at 8,000 characters (`17-data-model.md` §6) and the truncation is flagged. `description_html_sanitized` is produced by an allowlist sanitizer (tags: p, br, ul, ol, li, strong, em, a with http(s) href only; everything else stripped) — job HTML is untrusted input to a browser as well as to a model.
- `quality_flags` is a computed list from deterministic rules: `no_salary`, `vague_description` (<400 chars), `no_skills_listed`, `stale_posting` (>45 days), `suspicious_contact` (an email or a WhatsApp number in the description — a common scam marker), `pay_to_apply` (a fee mentioned). These feed `red_flags` in the explain payload (`08-matching.md` §3).
- A job is never mutated in place by ingestion in a way that loses history: `first_seen_at` never changes, `last_seen_at` and `unseen_runs` do, and a materially changed description (simhash distance >6) increments a `revision` counter and re-runs enrichment and embedding.

**Inputs.** `JobDraft` from a connector.

**Outputs.** A `jobs` document.

**Acceptance criteria.**
- `AC-JOB-01.1` Every `jobs` document validates against the model, and a field-class table in the module README covers every field.
- `AC-JOB-01.2` A description containing `<script>`, an `onclick` attribute, a `javascript:` href, and a `data:` href yields sanitized HTML with none of them, and the plain text carries no markup.
- `AC-JOB-01.3` Each of the six `quality_flags` rules fires on a crafted fixture and does not fire on a clean one.
- `AC-JOB-01.4` Re-ingesting an unchanged listing leaves `first_seen_at`, `revision`, `embedding`, and `enrichment` untouched and updates only `last_seen_at` and `unseen_runs`.
- `AC-JOB-01.5` A materially changed description increments `revision` and triggers re-enrichment and re-embedding.
- `AC-JOB-01.6` No stored `description_text` exceeds 8,000 characters (shared with `AC-DATA-06.2`).

**Tests.**
- `T-JOB-01.1` `tests/spec/test_job_field_classes.py`.
- `T-JOB-01.2` `tests/unit/test_html_sanitizer.py`.
- `T-JOB-01.3` `tests/unit/test_quality_flags.py`.
- `T-JOB-01.4`/`.5` `tests/integration/test_job_upsert.py`.
- `T-JOB-01.6` `tests/integration/test_description_truncation.py` (shared).

---

## 2. Scheduling and query fan-out — `JOB-02`

**Objective.** Spend a limited number of source requests where the users actually are.

**Constraints.**
- One ARQ cron per connector, schedule from `connectors.yaml`, default `0 */6 * * *`. Cron entries are staggered so three connectors do not start in the same minute.
- Each run is lock-guarded by connector name (`01-foundations.md` §10) — an overrunning run is skipped, not doubled.
- **Query fan-out.** A run does not fetch "everything". It builds a query list from **active user demand**: the distinct `(title_family, country, remote_mode)` tuples across users who signed in within the last 30 days, ordered by the number of users wanting each, capped at `INGEST_MAX_QUERIES_PER_RUN` (default 40) and further capped by the connector's rate limit × the run's time budget.
- Tuples are allocated round-robin across cap slots rather than strictly by popularity, so a niche tuple is not permanently starved by a popular one. The allocation is recorded in `connector_runs.queries` so starvation is visible.
- A connector that supports no filtering (`remotive`) ignores the query list, fetches its full feed once, and filters client-side; the framework must not assume the query list is used.
- Cold start: with zero users, a run uses a seed query list from config so staging has data before anyone signs up.
- On-demand refresh in R1 is **operator-only** (`POST /admin/connectors/{name}/run`). Per-saved-search refresh arrives with `JOB-07` in R2.
- The run has a hard time budget (default 10 minutes) after which it stops fetching, records what it did, and exits successfully — a partial run is a normal outcome, not a failure.

**Inputs.** Active users' preferences; `connectors.yaml`; caps.

**Outputs.** `connector_runs` row; `raw_listings`; upserted jobs; `JobsIngested{connector, job_ids}`.

**Acceptance criteria.**
- `AC-JOB-02.1` With 20 seeded users spanning 8 tuples and a cap of 5, the run issues 5 queries, and across four consecutive runs every one of the 8 tuples is served at least once.
- `AC-JOB-02.2` Two overlapping invocations result in one doing work (shared with `AC-FOUND-10.6`).
- `AC-JOB-02.3` With zero active users, the run uses the seed list and ingests jobs.
- `AC-JOB-02.4` A run exceeding its time budget exits with `status: partial`, a recorded query count, and a `JobsIngested` event for what it did ingest.
- `AC-JOB-02.5` `connector_runs.queries` records the actual tuples used, sufficient to detect starvation.
- `AC-JOB-02.6` A connector with `supports_keyword_filter: false` receives no query list and still ingests.

**Tests.**
- `T-JOB-02.1` `tests/integration/test_query_fanout.py`.
- `T-JOB-02.2` `tests/integration/test_cron_locks.py` (shared).
- `T-JOB-02.3` `tests/integration/test_cold_start_seed.py`.
- `T-JOB-02.4` `tests/integration/test_run_time_budget.py`.
- `T-JOB-02.5` `tests/integration/test_fanout_recording.py`.
- `T-JOB-02.6` `tests/integration/test_unfiltered_connector.py`.

---

## 3. Deduplication — `JOB-03`

**Objective.** One job the user sees once, however many sources carry it, with every source still reachable.

**Constraints.**
- **Stage 1, exact per source.** `(source, external_id)` unique across `source_refs[]`. An existing match is an update, not an insert.
- **Stage 2, exact cross-source.** `dedup_key = sha1(norm(company) | norm(title) | norm(locus))` where `locus` is the city or the literal `remote`. `norm` lowercases, strips legal suffixes (Pvt Ltd, Inc, LLC, GmbH), strips punctuation, collapses whitespace, and removes seniority prefixes from the title only for the key (not for display). A match merges.
- **Stage 3, fuzzy.** Candidates are jobs whose simhash is within Hamming distance 6 (queried via a banded index on simhash prefixes, not a full scan), then confirmed by `rapidfuzz.token_set_ratio(company) ≥ 92` **and** `token_set_ratio(title) ≥ 92`. Both conditions, not either — a company match alone merges unrelated roles, and a title match alone merges the same role at different employers, and both mistakes are worse than a duplicate.
- **Merge semantics.** The surviving document keeps the earliest `first_seen_at`, appends to `source_refs[]`, and resolves conflicting scalars by a documented precedence: prefer the value from the source with `salary.source == "listing"` over an estimate; prefer the longer `description_text`; prefer a non-null over a null; on a genuine tie prefer the `primary_source` (the source with the earliest `first_seen_at`). Every merge writes a `merged_from` audit entry on the document with the field-level decisions, so a wrong merge is diagnosable.
- A merge **never** rewrites `_id`. Applications and match scores point at `_id`; changing it would strand them. If two documents already exist and are later found to be duplicates, the newer is marked `status: merged_into` with a pointer and is excluded from search, but its `_id` stays resolvable so any application referencing it still works.
- Dedup is **idempotent**: re-running ingestion on identical input produces no additional merges.
- Merge decisions are logged at `info` with both ids and the reason (exact / fuzzy with scores), because this is the subsystem most likely to be wrong in a way nobody notices.

**Inputs.** A validated `JobDraft`; existing jobs.

**Outputs.** An inserted, updated, or merged `jobs` document; `connector_runs.deduped_into_existing`.

**Acceptance criteria.**
- `AC-JOB-03.1` The same listing from the same source twice results in one document with one `source_refs` entry and an updated `last_seen_at`.
- `AC-JOB-03.2` The same job from Adzuna and Greenhouse (fixture pair) merges into one document with two `source_refs` entries and both apply URLs preserved.
- `AC-JOB-03.3` "Acme Pvt Ltd" / "Acme" and "Senior Backend Engineer" / "Backend Engineer (Senior)" produce the same `dedup_key`.
- `AC-JOB-03.4` Two genuinely different jobs at the same company with similar titles ("Backend Engineer, Payments" vs "Backend Engineer, Growth") do **not** merge; two identical roles with reworded descriptions do.
- `AC-JOB-03.5` A merge preserves the earliest `first_seen_at`, prefers a listing-sourced salary over an estimated one, and records field-level decisions in `merged_from`.
- `AC-JOB-03.6` Re-running the full ingestion over the same fixtures produces zero additional merges (idempotence).
- `AC-JOB-03.7` A job discovered to be a duplicate after an application references it becomes `merged_into` and the application still resolves to a viewable job.
- `AC-JOB-03.8` The fuzzy candidate query uses the simhash index and does not collection-scan at 100k jobs.
- `AC-JOB-03.9` Across a 500-listing fixture corpus with 60 known duplicate pairs, precision ≥0.98 and recall ≥0.85, asserted as a regression test.

**Tests.**
- `T-JOB-03.1`–`.3` `tests/unit/test_dedup_keys.py`, `tests/integration/test_dedup_exact.py`.
- `T-JOB-03.4` `tests/unit/test_dedup_fuzzy_boundaries.py`.
- `T-JOB-03.5` `tests/unit/test_merge_precedence.py`.
- `T-JOB-03.6` `tests/integration/test_dedup_idempotence.py`.
- `T-JOB-03.7` `tests/integration/test_late_merge.py`.
- `T-JOB-03.8` `tests/integration/test_index_usage.py` (shared).
- `T-JOB-03.9` `tests/integration/test_dedup_corpus.py`.

---

## 4. Normalization — `JOB-04`

**Objective.** Turn each source's vocabulary into ours, so a score means the same thing regardless of where the job came from.

**Constraints.**
- **Title → family + seniority.** Rules in `jobs/title_families.yaml`: ordered rules of regex plus keyword sets, first match wins, each rule carrying a comment explaining an example it exists for. No LLM in this path — it must be deterministic and auditable. An unmatched title gets `title_family: other` and is recorded in an unmatched-titles report, which is how the rule set grows. Seniority from an explicit ordered pattern list (intern, junior, mid, senior, lead, principal, manager, director, executive) with `unknown` as the honest default; a numeric "3+ years" in the title does not set seniority.
- **Location.** A three-tier resolver: exact match against a bundled geonames-lite table (city, region, country, ~40k rows for the countries we serve, committed as a compressed asset — no runtime geocoding API, no per-listing network call); then a country-name and ISO-code match; then remote-only detection from phrases. `country` must resolve or the draft is flagged `location_unresolved` and the job is still stored (it may be remote and still matchable) but never scores location points. `remote_mode` comes from a phrase list applied to title, location string, and the first 500 characters of the description, in that priority.
- **Salary.** Parse from structured fields when present; otherwise from the description via a conservative pattern set (₹ and $ ranges, LPA, "per annum", "k"), and **only** when unambiguous. `salary.source` is `listing` when structured, `parsed` when from text, `null` when absent. An ambiguous parse yields null, because a wrong salary is worse than no salary — it silently mis-scores and misleads.
- **Employment type** from a phrase list, defaulting to `full_time` only when the source's own field says so; otherwise `unknown`.
- **Dates.** `posted_at` normalized to UTC; a relative date ("3 days ago") is resolved against `fetched_at`, not the current time, so a re-processed payload does not drift. A future `posted_at` is clamped to `fetched_at` and flagged.
- Every normalizer is a pure function in `jobs/normalize.py`, testable with plain dicts, with no clock access except an injected `fetched_at`.

**Inputs.** `JobDraft`.

**Outputs.** Normalized fields; unmatched-title and unresolved-location reports.

**Acceptance criteria.**
- `AC-JOB-04.1` A 300-title fixture maps to expected `(title_family, seniority)` pairs, including 20 deliberately awkward cases (SDE II, Member of Technical Staff, Full Stack Dev - MERN, Java/J2EE Developer).
- `AC-JOB-04.2` An unmatched title yields `other` and one row in the unmatched report with a count.
- `AC-JOB-04.3` A 200-location fixture resolves to expected `(city, region, country, remote_mode)`, including "Bengaluru/Bangalore", "NCR", "Remote (India)", "Hybrid - 3 days Gurgaon".
- `AC-JOB-04.4` No location resolution makes a network request (asserted with respx in strict mode).
- `AC-JOB-04.5` "₹25–35 LPA" parses to `{2500000, 3500000, INR, year, parsed}`; "competitive salary" and "as per industry standards" parse to null; "up to 40k" parses to null (ambiguous currency and period).
- `AC-JOB-04.6` "3 days ago" against a `fetched_at` of 2026-09-05 resolves to 2026-09-02 regardless of when the test runs.
- `AC-JOB-04.7` A `posted_at` in the future is clamped and flagged.
- `AC-JOB-04.8` Every function in `normalize.py` is pure (static check plus double-call equality).

**Tests.**
- `T-JOB-04.1`/`.2` `tests/unit/test_title_normalization.py`.
- `T-JOB-04.3`/`.4` `tests/unit/test_location_normalization.py`.
- `T-JOB-04.5` `tests/unit/test_salary_parsing.py`.
- `T-JOB-04.6`/`.7` `tests/unit/test_date_normalization.py`.
- `T-JOB-04.8` `tests/spec/test_normalize_purity.py` (shared).

---

## 5. Skill extraction and enrichment — `JOB-05`

**Objective.** Know what a job actually requires, cheaply, and be honest about how confidently we know it.

**Constraints.**
- **Stage 1, always: dictionary.** Match the canonical skill vocabulary (`03-profile.md` §4) against title and description using whole-word matching with alias support. Cheap, deterministic, no AI. Sets `skills_source: "dictionary"`.
- **Requirement vs nice-to-have** is decided by section detection: text under a "requirements"/"must have"/"qualifications" heading is required; under "nice to have"/"preferred"/"bonus" is nice-to-have; unsectioned text defaults to **nice-to-have**, not required. Defaulting to required inflates every `missing_required` list and makes the explain payload alarming and wrong.
- **Stage 2, gated: LLM enrichment.** Only for jobs that pass a relevance gate — the job is in a `title_family` that at least one active user wants, and either fewer than 3 skills were found by the dictionary or no section structure was detected. Produces `{required[], nice[], seniority, remote_mode, experience_years}` at the `fast` tier, cached by description hash (`05-ai-layer.md` §3), and sets `skills_source: "llm"`. One enrichment serves every user who sees the job, which is what makes it affordable.
- Enrichment **may not** override a value the source supplied structurally. It fills gaps only.
- Enrichment output skills are canonicalized; unmapped ones are kept with `canonical: null` and counted (they score as non-matches).
- On budget exhaustion, enrichment is skipped and the job keeps dictionary skills (`05-ai-layer.md` §3). No job waits for enrichment to become visible.
- `experience_years` comes from a regex pass first (`"3+ years"`, `"3-5 years"`, `"minimum 4 years"`) with `source: "regex"`, and from enrichment only if the regex found nothing.
- **Embedding.** After skills, embed a composed text (title + company + first 2,000 characters of description) via the embedding provider, quantized per `17-data-model.md` §6, keyed by `source_hash`. Skipped on budget exhaustion and backfilled later.

**Inputs.** The job document; the canonical vocabulary; active-user demand.

**Outputs.** `required_skills`, `nice_to_have_skills`, `skills_source`, `experience_years`, `enrichment`, `embedding`.

**Acceptance criteria.**
- `AC-JOB-05.1` Dictionary matching finds "React", "react.js" and "ReactJS" in a description as the single canonical `react`, and does not match "reactive" or "React Native" as `react` (React Native is its own canonical).
- `AC-JOB-05.2` Skills under a "Nice to have" heading land in `nice_to_have_skills`; unsectioned skills land in `nice_to_have_skills`, not `required_skills`.
- `AC-JOB-05.3` The enrichment gate skips a job in an unwanted `title_family` and skips a job with 5 dictionary skills and clear sections; it fires for a job with 1 skill and no sections.
- `AC-JOB-05.4` Enrichment does not overwrite a structurally supplied `experience_years` or `remote_mode`.
- `AC-JOB-05.5` Two jobs with identical descriptions produce one enrichment call and one embedding call (cache hit recorded).
- `AC-JOB-05.6` With the AI budget exhausted, the job is stored, visible, and scoreable with `skills_source: "dictionary"` and no embedding, and a later backfill adds the embedding without changing anything else.
- `AC-JOB-05.7` `experience_years.source` is `regex` when the pattern matched and `llm` only otherwise.

**Tests.**
- `T-JOB-05.1` `tests/unit/test_skill_dictionary_match.py`.
- `T-JOB-05.2` `tests/unit/test_requirement_sectioning.py`.
- `T-JOB-05.3` `tests/unit/test_enrichment_gate.py`.
- `T-JOB-05.4` `tests/unit/test_enrichment_no_override.py`.
- `T-JOB-05.5` `tests/ai/test_response_cache.py` (shared).
- `T-JOB-05.6` `tests/integration/test_enrichment_degraded.py`.
- `T-JOB-05.7` `tests/unit/test_experience_parsing.py`.

---

## 6. Staleness and expiry — `JOB-08`

**Objective.** Do not send a user to a dead posting, and do not delete the record of one they applied to.

**Constraints.**
- Each run increments `unseen_runs` for every active job of that `primary_source` not returned in the run, and resets it to 0 for those seen. At 3 (or 2 under storage pressure, `AC-DATA-06.3`), the job becomes `status: expired` with `expired_at`, and `JobExpired` is published.
- **Only the source's own runs count.** A job seen only by Adzuna is not expired because a Greenhouse run did not return it. `unseen_runs` is tracked per `source_refs` entry, and a job expires only when every one of its sources has stopped returning it.
- A run that fetched an unrepresentative slice must not expire everything: expiry is skipped entirely for a run with `status: partial` or with a fetched count below 50% of the trailing 3-run median. This one rule prevents the worst failure mode of this subsystem — a throttled run silently expiring the entire catalogue.
- Expired jobs are excluded from search and from new scoring, remain visible in the Tracker with an "expired listing" marker (TRACK-01: a flag, not a status), and are purged per `17-data-model.md` §5 unless referenced by an application.
- A previously expired job returned again is revived: `status: active`, `expired_at: null`, `unseen_runs: 0`, and the revival is logged.
- `apply_deadline`, when supplied, expires the job independently of runs.

**Inputs.** Run results; existing jobs.

**Outputs.** `status`, `expired_at`, `unseen_runs`; `JobExpired`.

**Acceptance criteria.**
- `AC-JOB-08.1` A job missing from 3 consecutive runs of its only source expires; missing from 2 does not.
- `AC-JOB-08.2` A job carried by two sources expires only when both have missed it 3 times.
- `AC-JOB-08.3` A partial run performs no expiry; a run fetching 40% of the trailing median performs no expiry and logs the reason.
- `AC-JOB-08.4` An expired job is absent from search results and present in the Tracker with the expired marker.
- `AC-JOB-08.5` A revived job returns to `active` with `expired_at: null` and its `first_seen_at` unchanged.
- `AC-JOB-08.6` A job past its `apply_deadline` expires regardless of run outcomes.
- `AC-JOB-08.7` An expired job referenced by an application is never deleted; its description is cleared at 90 days and the rest is retained.

**Tests.**
- `T-JOB-08.1`/`.2` `tests/integration/test_staleness.py`.
- `T-JOB-08.3` `tests/integration/test_expiry_safety.py`.
- `T-JOB-08.4` `tests/integration/test_expired_visibility.py`.
- `T-JOB-08.5` `tests/integration/test_job_revival.py`.
- `T-JOB-08.6` `tests/unit/test_apply_deadline.py`.
- `T-JOB-08.7` `tests/integration/test_job_purge.py` (shared).

---

## 7. Search, filters and feed controls — `JOB-06`, `JOB-09`

**Objective.** Find a job by words and narrow it by facts, fast, and never show a job the user has dismissed.

**Constraints.**
- Text search on the compound text index (`title` weight 10, `company.name` 5, `description_text` 1). Filters: `title_family`, `seniority`, `country`, `city`, `remote_mode`, `employment_type`, `salary_min`, `posted_within_days`, `source`, `has_salary`, `min_score` (joins `match_scores`).
- Default sort is `posted_at desc` for search and `score desc` for the matches feed (`08-matching.md` §5). Text-relevance sort is available explicitly; it is never the default, because relevance-by-keyword competes confusingly with the match score.
- Cursor pagination (`01-foundations.md` §7). No `total`.
- `status: active` is always applied unless an operator asks otherwise.
- **Hidden and not-interested jobs are excluded server-side**, by an anti-join against `user_job_actions`, in the query — not filtered in the client, which would leave holes in pages. For a user with many hidden jobs, the exclusion set is loaded once per request (bounded, and above a threshold the query switches to a `$nin` on a capped recent set with the rest applied post-filter and the page topped up).
- Hiding is idempotent (unique index) and reversible. `reason` comes from a fixed enum (`salary_too_low`, `location`, `seniority_mismatch`, `not_my_field`, `company`, `already_applied`, `scam_suspected`, `other`) plus optional free text — an enum because this is training data for MATCH-06 in R2 and free text is not.
- Search latency budget: p95 < 500 ms; the matches feed of 50 scored jobs p95 < 800 ms with scores precomputed.

**Inputs.** Query parameters; the user's action set.

**Outputs.** `Page[JobSummary]`; `user_job_actions` rows.

**Acceptance criteria.**
- `AC-JOB-06.1` A search for a term in a title outranks the same term appearing only in a description (weighting works).
- `AC-JOB-06.2` Every filter narrows correctly and combines correctly; a fixture matrix covers each filter alone and three combinations.
- `AC-JOB-06.3` Search p95 < 500 ms at 100k jobs; the matches feed p95 < 800 ms for 50 items.
- `AC-JOB-06.4` A hidden job never appears in search or feed results, and pages remain exactly `limit` long (no holes) when hidden jobs fall inside a page.
- `AC-JOB-06.5` Hiding the same job twice succeeds and creates one row; unhiding restores it to results.
- `AC-JOB-06.6` A user with 500 hidden jobs still gets full, correctly-sized pages within the latency budget.
- `AC-JOB-06.7` Expired jobs are absent by default and present with an explicit operator flag.

**Tests.**
- `T-JOB-06.1` `tests/integration/test_text_search_weights.py`.
- `T-JOB-06.2` `tests/integration/test_search_filters.py`.
- `T-JOB-06.3` `tests/integration/test_search_latency.py` (nightly, seeded).
- `T-JOB-06.4`/`.6` `tests/integration/test_hidden_exclusion.py`.
- `T-JOB-06.5` `tests/integration/test_hide_idempotence.py`.
- `T-JOB-06.7` `tests/integration/test_expired_visibility.py` (shared).

**Feed controls, stated against their own requirement so the track table maps cleanly.**
- `AC-JOB-09.1` Hiding a job excludes it from search and from the matches feed server-side, for that user only — another user still sees it.
- `AC-JOB-09.2` `reason` is accepted only from the fixed enum, with optional free text alongside; a free-text-only reason is rejected.
- `AC-JOB-09.3` Hide is idempotent and reversible (`AC-JOB-06.5` shared).
- `T-JOB-09.1`–`.3` `tests/integration/test_hidden_exclusion.py`, `tests/unit/test_hide_reasons.py`.

### 7.1 Saved searches — `JOB-07` — **Track: R2**

Named filter sets with `notify: bool`. A saved search with notification on triggers an on-demand refresh of the connectors that can serve it (rate-limit permitting) and feeds the digest (`11-notifications.md` §5). Cap 10 per user.

**Acceptance criteria.** `AC-JOB-07.1` A saved search returns the same results as the equivalent ad-hoc query. `AC-JOB-07.2` Refresh respects connector rate limits and is capped per user per day. `AC-JOB-07.3` The cap is enforced.
**Tests.** `T-JOB-07.1`–`.3` `tests/integration/test_saved_searches.py`.

### 7.2 Reporting a listing — `JOB-10` — **Track: R2**

`POST /jobs/{id}/report` with a reason enum (`scam`, `fee_requested`, `misleading`, `duplicate`, `expired`, `offensive`). Increments `flagged.count`, appends the reason, and at 3 distinct reporters sets `status: flagged`, which removes it from search and applies the −50 penalty in scoring (`08-matching.md` §2). Enters the operator queue (`12-admin.md` §5).

**Acceptance criteria.** `AC-JOB-10.1` A report is idempotent per user. `AC-JOB-10.2` Three distinct reporters flag the job and it leaves search. `AC-JOB-10.3` A flagged job carries the scoring penalty. `AC-JOB-10.4` Operator dismissal restores it and records the decision.
**Tests.** `T-JOB-10.1`–`.4` `tests/integration/test_job_reporting.py`.
