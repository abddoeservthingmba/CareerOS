# 08 — Matching Engine

**Module:** `apps/api/app/modules/matching`
**Track:** R1 except §6 (`MATCH-06`, R2), §7 (`MATCH-08`, R3), and the *enablement* of §4 (`MATCH-02b`, R2)
**Depends on:** `03-profile.md`, `07-ingestion-and-jobs.md`, `05-ai-layer.md`, `17-data-model.md` §2.8
**Requirements:** `MATCH-01` … `MATCH-08`
**Public API:** `MatchService.feed`, `.explain`, `.set_threshold`, `.feedback`, `ScoringService.score`
**Publishes:** none. **Consumes:** `JobsIngested`, `ProfileUpdated`.

Two rules govern this module and everything in it follows from them. **A number is deterministic** — the same profile and the same job produce the same score forever, given a weights version. **A model never touches the number** (HR-3) — the rationale paragraph is decoration on a calculation the user could redo by hand.

---

## 1. Design commitments — `MATCH-03`

**Objective.** A score that can be recomputed, explained, and compared across time.

**Constraints.**
- `matching/scoring.py` holds the entire calculation as **pure functions**: inputs are plain dataclasses (`ScoringProfile`, `ScoringJob`, `Weights`), no I/O, no clock (freshness takes an injected `now`), no randomness, no database, no AI. This is what makes 30 fixture cases a meaningful test suite.
- The scorer's input type **has no field capable of carrying a rationale, a model name, or any LLM output** (HR-3). This is structural, not disciplinary, and is asserted (`AC-MATCH-03.4`).
- Every stored score carries `weights_version`, `profile_version`, and `scorer_build` (the git SHA of the scoring module). A score whose provenance is unknown is worthless a month later when a user asks why a job scored 62.
- Weights are versioned configuration in `matching/weights/w1.yaml`, loaded at startup and immutable at runtime. Changing a weight means a new version file and a rescore, never an edit.
- Rounding is defined once: components are computed in floating point, summed, clamped to 0–100, then rounded **half-up** to an integer. Each component is also stored rounded for display, and the stored components need not sum exactly to the score — a note in the explain payload says so, rather than fudging the arithmetic to make it look tidy.
- No score is computed at read time. The feed reads stored rows (ADR-005).

**Inputs.** `ScoringProfile`, `ScoringJob`, `Weights`, `now`.

**Outputs.** `MatchResult{score, band, components, explain, embedding_sim}`.

**Acceptance criteria.**
- `AC-MATCH-03.1` Scoring the same fixture 1,000 times yields byte-identical results, including component values.
- `AC-MATCH-03.2` `scoring.py` imports nothing from `app.infra`, `app.ai`, `app.modules.*.models`, or `app.modules.*.repository` (static check).
- `AC-MATCH-03.3` Every stored `match_scores` row has non-null `weights_version`, `profile_version`, and `scorer_build`.
- `AC-MATCH-03.4` The scorer's input dataclasses have no field whose name or type could hold LLM output; a test introspects them and fails if one is added (HR-3).
- `AC-MATCH-03.5` Freshness uses the injected `now`; scoring the same job with two different `now` values differs only in the freshness component.
- `AC-MATCH-03.6` Loading a malformed or incomplete weights file fails at startup, naming the missing key.

**Tests.**
- `T-MATCH-03.1` `tests/unit/test_scoring_determinism.py` (hypothesis).
- `T-MATCH-03.2` `tests/spec/test_scoring_purity.py`.
- `T-MATCH-03.3` `tests/integration/test_score_provenance.py`.
- `T-MATCH-03.4` `tests/unit/test_scorer_input_type.py` (shared with `T-DATA-02.5`).
- `T-MATCH-03.5` `tests/unit/test_freshness_component.py`.
- `T-MATCH-03.6` `tests/unit/test_weights_loading.py`.

---

## 2. Score composition, weights `w1` — `MATCH-01`

**Objective.** A 0–100 number whose parts a non-technical user can read.

**Constraints.**

`score = round_half_up(clamp(Σ components − penalties, 0, 100))`

| Component | Max | Computation |
|---|---|---|
| **Skills** | 40 | `required_coverage × 30 + nice_coverage × 10`, where coverage is `|matched| / |listed|` over **canonical** skills (`03-profile.md` §4). If the job lists no skills at all, substitute `embedding_sim × 40` and set `explain.skills_basis: "semantic"` |
| **Experience** | 15 | Against `job.experience_years.min`: meets or exceeds → 15; within 1 year below → 10; 1–2 years below → 5; more than 2 below → 0; overqualified by more than 4 years → 10 (not 15 — being far over the band genuinely reduces the chance of a callback, and pretending otherwise misleads the user). Job states no requirement → 12 (mildly positive, not neutral: an unstated requirement is usually not a barrier) |
| **Title / role** | 15 | Same `title_family` → 15; adjacent family per `adjacency.yaml` → 8; else `rapidfuzz.token_set_ratio(job.title, best of preferences.titles) / 100 × 15` |
| **Location / remote** | 15 | Remote job and user accepts remote → 15; city in `preferences.locations` → 15; same country and `open_to_relocation` → 8; same country, no relocation, job is hybrid → 4; else 0. `location_unresolved` → 0 with an explicit verdict |
| **Salary** | 8 | Unknown → 4 (neutral, and the explain payload says "not stated"); at or above `salary_min` → 8; within 15% below → 4; further below → 0. Cross-currency via `shared/fx.py`, with the rate and its date in the explain payload |
| **Seniority** | 4 | Exact match → 4; one level adjacent → 2; `unknown` on either side → 2; two or more levels apart → 0 |
| **Freshness** | 3 | ≤3 days → 3; ≤14 → 2; ≤30 → 1; older → 0 |
| **Penalties** | — | An `exclude_keywords` whole-word hit in title, company, or description → **−25**; an `exclude_industries` hit → −25; employment-type mismatch against a non-empty preference → −15; `status: flagged` → −50; `quality_flags` containing `pay_to_apply` or `suspicious_contact` → −30 |

- Maxima sum to 100. Penalties can drive the score to 0, which is the point.
- **Embedding similarity is not a weighted component in `w1`.** It serves two roles: the skills fallback above, and a **tie-break** in feed ordering. It is displayed in the explain payload as "semantic fit" so the user sees it, but it does not silently move the number, because "we think it feels similar" is not explainable. Revisit in `w2` once feedback data exists (`MATCH-06`).
- A component whose inputs are missing records an explicit verdict (`unknown`, `not_stated`, `unresolved`) rather than a zero that looks like a judgement.
- `band` is derived and stored: `strong ≥80`, `good 65–79`, `partial 50–64`, `weak <50`.

**Inputs.** `ScoringProfile`, `ScoringJob`, `w1`.

**Outputs.** `score`, `band`, `components`, `explain`.

**Acceptance criteria.**
- `AC-MATCH-01.1` Thirty hand-built `(profile, job, expected components)` fixtures pass exactly, covering: perfect match, no skills listed, no salary, remote/onsite mismatch, overqualified, underqualified by 1 and by 3 years, excluded keyword, flagged job, unresolved location, cross-currency salary, adjacent title family, unknown seniority on each side.
- `AC-MATCH-01.2` Component maxima sum to 100, asserted from the weights file rather than hard-coded in the test.
- `AC-MATCH-01.3` Score is monotonic in required-skill coverage: adding a matched required skill never decreases the score (hypothesis).
- `AC-MATCH-01.4` A job listing no skills scores skills via `embedding_sim` and sets `skills_basis: "semantic"`; with no embedding either, skills score 0 and the verdict says why.
- `AC-MATCH-01.5` An excluded keyword produces exactly one −25 penalty even if the word appears five times.
- `AC-MATCH-01.6` A whole-word exclusion does not fire on a substring (`AC-PROF-02.4` shared).
- `AC-MATCH-01.7` Overqualification by 5 years scores 10, not 15, and the explain payload states it.
- `AC-MATCH-01.8` `embedding_sim` never appears in `components` and changing it alone (with skills listed) does not change `score`.
- `AC-MATCH-01.9` Every score in 0–100 inclusive across 10,000 hypothesis-generated inputs; no exception, no NaN.

**Tests.**
- `T-MATCH-01.1` `tests/unit/test_scoring_fixtures.py` with fixtures in `tests/fixtures/scoring/`.
- `T-MATCH-01.2` `tests/unit/test_weights_sum.py`.
- `T-MATCH-01.3`/`.9` `tests/unit/test_scoring_properties.py`.
- `T-MATCH-01.4` `tests/unit/test_skills_fallback.py`.
- `T-MATCH-01.5`/`.6` `tests/unit/test_penalties.py`.
- `T-MATCH-01.7` `tests/unit/test_experience_component.py`.
- `T-MATCH-01.8` `tests/unit/test_embedding_not_weighted.py`.

---

## 3. The explainability contract — `MATCH-02a`

**Objective.** The UI can render a complete, honest explanation from the stored row with no further computation and no second request.

**Constraints.** `explain` must be sufficient to render all six of these, and a client-side test asserts each renders from the stored payload alone:

1. **Headline verdict** from `band`, phrased plainly ("Strong match", "Partial match").
2. **Matched and missing required skills**, as canonical names with display labels, grouped by category where more than four are missing ("missing 2 infrastructure skills") — `03-profile.md` §4.
3. **One line each** for experience, location, salary, seniority, each carrying a `verdict` enum **and** a human `detail` string. The verdict is what the client styles on; the detail is what it shows.
4. **Red flags** derived from `quality_flags` and penalties, each with a plain-language string ("This listing asks for a fee", "Posted 52 days ago", "Reported by 3 users").
5. **Semantic fit**, shown as a labelled secondary signal, explicitly marked as not affecting the score.
6. **Score composition**, as the component breakdown with each component's max, so the arithmetic is inspectable.

- Additional required properties: `skills_basis ∈ {listing, dictionary, llm, semantic, none}` (`17-data-model.md` §2.8 — five members, aligned with `jobs.skills_source` plus the two cases only the explain payload has) so the UI can say "requirements inferred from the description" when they were not stated by the employer — a distinction that changes how much the user should trust a `missing_required` list. And `weights_version` echoed so a support question is answerable.
- Every `verdict` value is a member of an enum exported to OpenAPI; a client never string-matches on `detail`.
- `explain` is capped in size (no full description, no embedding vector) — it is rendered in a feed of 50.
- `rationale` is a **sibling field, not part of `explain`** (`17-data-model.md` §2.8), so the explain contract is complete without it and the UI degrades to a full explanation when the flag is off.

**Inputs.** `MatchResult`.

**Outputs.** `match_scores.explain`.

**Acceptance criteria.**
- `AC-MATCH-02.1` A schema test asserts every field the six renderings need is present and non-null for every one of the 30 scoring fixtures.
- `AC-MATCH-02.2` Both clients render all six sections from a stored payload with the network disabled after load (component tests with a fixture payload).
- `AC-MATCH-02.3` Every `verdict` is an enum member; a test asserts no client code branches on `detail`.
- `AC-MATCH-02.4` `skills_basis: "llm"` causes the UI to show the "inferred from the description" qualifier; `"dictionary"` does not.
- `AC-MATCH-02.5` `explain` serialized is under 4 KB for every fixture.
- `AC-MATCH-02.6` With `FLAG_LLM_RATIONALE_ENABLED=false`, the job detail view is complete and shows no empty rationale placeholder.

**Tests.**
- `T-MATCH-02.1` `tests/spec/test_explain_completeness.py`.
- `T-MATCH-02.2` `apps/web/.../match-explain.test.tsx`, `apps/mobile/test/match_explain_test.dart`.
- `T-MATCH-02.3` `tests/spec/test_verdict_enums.py` + a web lint rule.
- `T-MATCH-02.4` `apps/web/.../skills-basis.test.tsx`.
- `T-MATCH-02.5` `tests/unit/test_explain_size.py`.
- `T-MATCH-02.6` `apps/web/.../rationale-off.test.tsx`.

---

## 4. The LLM rationale — `MATCH-02b` — **code R1, enabled R2**

**Objective.** A short paragraph that reads like a person summarising the breakdown, adding nothing the breakdown does not already contain.

**Constraints.**
- Input to the prompt is the **profile summary, the job summary, and the computed component breakdown**. The model is told the score and is instructed to explain it, never to assess it. It never returns a number, and any number in its output that is not already in the breakdown is a test failure.
- Output schema `{rationale: str (≤80 words), red_flags: [str]}`. `red_flags` from the model are **merged into** the deterministic flags, deduplicated, and marked as AI-sourced; they never remove a deterministic flag.
- Written to `match_scores.rationale` with `rationale_model` and `rationale_prompt_version` (HR-9). Labelled as AI-generated in both clients.
- Selection: top-N per user per day by score, `AI_RATIONALE_TOP_N` default 20, only for scores at or above the user's threshold, only for jobs the user has not hidden, and only once per `(user, job, prompt_version)` — cached, so a rescore does not re-buy it.
- **Gate.** `FLAG_LLM_RATIONALE_ENABLED`, default **false in production** at R1 (`README.md` §1, Call 1). The R1 test suite runs it against the fake provider so the code is proven; production enables it at R2 after two weeks of budget data.
- On budget exhaustion, `rationale` stays null and nothing else changes (`05-ai-layer.md` §3).
- HR-3 restated as a property: deleting every `rationale` field from the database must not change any score, and a test does exactly that.

**Inputs.** Profile summary, job summary, components.

**Outputs.** `rationale`, `rationale_model`, `rationale_prompt_version`, `rationale_at`.

**Acceptance criteria.**
- `AC-MATCH-02.7` Rationale text contains no numeric claim absent from the component breakdown (checked by extracting numerals and comparing against the breakdown's values, over the golden set).
- `AC-MATCH-02.8` A model-supplied red flag is added and labelled AI-sourced; a deterministic flag is never removed by the model.
- `AC-MATCH-02.9` Only the top-N above threshold receive a rationale; the (N+1)th does not, and a hidden job never does.
- `AC-MATCH-02.10` A rescore of an unchanged profile and job does not issue a second rationale call.
- `AC-MATCH-02.11` Deleting all `rationale` fields leaves every `score` and every `components` value unchanged (HR-3).
- `AC-MATCH-02.12` With the flag false, no rationale call is made and no `ai_usage` row for `match_rationale` is written.
- `AC-MATCH-02.13` The rationale is rendered with an AI label in both clients (HR-9).

**Tests.**
- `T-MATCH-02.7` `tests/ai/test_rationale_no_new_numbers.py`.
- `T-MATCH-02.8` `tests/unit/test_red_flag_merge.py`.
- `T-MATCH-02.9`/`.10` `tests/integration/test_rationale_selection.py`.
- `T-MATCH-02.11` `tests/integration/test_rationale_independence.py`.
- `T-MATCH-02.12` `tests/integration/test_rationale_flag_off.py`.
- `T-MATCH-02.13` `apps/web/.../ai-label.test.tsx`, `apps/mobile/test/ai_label_test.dart`.

---

## 5. Candidate selection, incremental scoring and the feed — `MATCH-04`, `MATCH-05`, `MATCH-07`

**Objective.** Score only what needs scoring, and serve a feed of 50 in under 800 ms.

**Constraints.**
- **New job → users.** Candidate users are those whose `preferences.title_families` intersects the job's family, **or** whose canonical profile skills overlap ≥3 of the job's required skills, then filtered by country/remote compatibility. Served by the profile indexes in `17-data-model.md` §3. Users inactive for 90 days are excluded (they are not reading the feed, and scoring them is pure cost).
- **Changed profile → jobs.** Rescore that user's candidate jobs from the last 45 days matching the same gate, debounced 60 s (`01-foundations.md` §9), chunked at 200 jobs per task, and skipped if a newer `profile_version` is already queued.
- **Never a full-table scan for one user.** The gate is mandatory; a code path that scores all jobs for a user fails a test.
- Scoring writes are upserts on the `(user_id, job_id)` unique index, so concurrent scoring of the same pair converges rather than duplicating.
- **Embeddings** (`MATCH-04`): cosine similarity between the profile embedding and the job embedding, both quantized (`17-data-model.md` §6), computed only when both exist and the models match (`EmbeddingModelMismatch` otherwise). A missing embedding on either side yields `embedding_sim: null` and the dictionary skills path.
- **Threshold** (`MATCH-07`): `users.settings.match_threshold`, default 60, range 0–95. It filters the feed at **read** time, not at score time — lowering it must not require a rescore. Scores below the threshold are still stored, because the user may lower it.
- **Feed**: reads `match_scores` on the `(user_id, score desc, job_id)` index, joins the job summaries, excludes hidden and expired, ties broken by `embedding_sim` then `posted_at`. Cursor-paginated. The join fetches only the summary projection, never `description_text`.
- The feed must be correct when scores are missing: a job with no score yet is simply absent, not shown as zero.

**Inputs.** `JobsIngested`, `ProfileUpdated`, the threshold, cursors.

**Outputs.** `match_scores` rows; `Page[MatchCard]`.

**Acceptance criteria.**
- `AC-MATCH-05.1` A new job in family X is scored for exactly the users whose gate it passes, and for none others, verified with 20 seeded users across 6 families.
- `AC-MATCH-05.2` A profile change enqueues one rescore per 60-second window and processes only jobs within the 45-day gate.
- `AC-MATCH-05.3` No code path scores all jobs for one user (static check on the repository's query builders plus an integration assertion on documents examined).
- `AC-MATCH-05.4` Concurrent scoring of the same pair results in one row, last write winning, no duplicate-key error surfaced.
- `AC-MATCH-05.5` A user inactive for 91 days is not scored for new jobs; signing in resumes scoring within one debounce window.
- `AC-MATCH-05.6` Lowering the threshold from 60 to 40 immediately reveals stored scores in that range with no rescore and no new AI calls.
- `AC-MATCH-05.7` Feed p95 < 800 ms for 50 items at 100k jobs and 5,000 scores per user; `explain()` shows an index scan.
- `AC-MATCH-05.8` A mismatched embedding model raises rather than silently comparing incompatible vectors.
- `AC-MATCH-05.9` The feed excludes hidden and expired jobs and returns full pages (shared with `AC-JOB-06.4`).

**Tests.**
- `T-MATCH-05.1` `tests/integration/test_candidate_selection.py`.
- `T-MATCH-05.2` `tests/integration/test_rescore_debounce.py` (shared).
- `T-MATCH-05.3` `tests/spec/test_no_full_scan_scoring.py`.
- `T-MATCH-05.4` `tests/integration/test_score_upsert_concurrency.py`.
- `T-MATCH-05.5` `tests/integration/test_inactive_user_scoring.py`.
- `T-MATCH-05.6` `tests/integration/test_threshold_read_time.py`.
- `T-MATCH-05.7` `tests/integration/test_feed_latency.py` (nightly).
- `T-MATCH-05.8` `tests/unit/test_embedding_guard.py` (shared).
- `T-MATCH-05.9` `tests/integration/test_hidden_exclusion.py` (shared).

**Embeddings and the threshold, stated against their own requirements.**
- `AC-MATCH-04.1` Cosine similarity is computed only between vectors of the same model and dimension, from the quantized form, and matches the float32 value within 0.01 (`AC-DATA-06.1`, `AC-MATCH-05.8` shared).
- `AC-MATCH-04.2` A job or profile without an embedding yields `embedding_sim: null` and scores by the dictionary path, with no error and no blocked feed.
- `AC-MATCH-07.1` The threshold filters at read time only: changing it issues no scoring work and no AI call (`AC-MATCH-05.6` shared).
- `AC-MATCH-07.2` The threshold is clamped to 0–95; a value of 100 is rejected, because a threshold that can hide every job is a support ticket.
- `T-MATCH-04.1`–`.2` `tests/unit/test_embedding_similarity.py`, `tests/unit/test_skills_fallback.py` (shared).
- `T-MATCH-07.1`–`.2` `tests/integration/test_threshold_read_time.py` (shared), `tests/unit/test_threshold_bounds.py`.

---

## 6. Feedback loop — `MATCH-06` — **Track: R2**

**Objective.** Let a user's corrections nudge their own scores, within bounds tight enough that the score stays explainable.

**Constraints.**
- Capture: thumbs up/down plus a reason enum (`wrong_skills`, `wrong_seniority`, `wrong_location`, `salary_wrong`, `not_my_field`, `good_match`), stored on `match_scores.user_feedback`. `user_job_actions` from R1 (`JOB-09`) is the same signal in cheaper form and is included in the aggregate.
- Adjustment: **per-user component offsets** `Δw ∈ [−5, +5]`, nudged 0.5 per feedback event, applied at score time and recorded as `weights_version: "w1+user"`. Bounded so no user's scores drift into a different scale, and so the displayed component maxima remain honest (the UI shows the adjusted max).
- The offsets are **visible and resettable** by the user. An invisible personalization that changes numbers is precisely the opacity this product exists to avoid.
- A feedback event triggers a debounced rescore of that user only.
- v2 (R3) trains a ranker on `(components, embedding_sim) → applied/interviewed`; nothing in R2 may make that harder, so feedback rows retain the full component vector at the time of feedback.

**Acceptance criteria.** `AC-MATCH-06.1` An offset never exceeds ±5 across 100 consecutive feedback events. `AC-MATCH-06.2` A score computed with offsets records `w1+user` and the UI shows the adjusted maxima. `AC-MATCH-06.3` Reset restores `w1` scores exactly. `AC-MATCH-06.4` Feedback rows store the component vector as it was. `AC-MATCH-06.5` One feedback event causes at most one rescore per debounce window.
**Tests.** `T-MATCH-06.1`–`.5` `tests/unit/test_weight_offsets.py`, `tests/integration/test_feedback_loop.py`.

---

## 7. Gap analysis — `MATCH-08` — **Track: R3**

**Objective.** Tell a user what would take a 62 to an 80.

**Constraints (design only).** Computed from the stored components: which missing required skills carry the most points, whether experience or seniority is the binding constraint (and therefore not addressable), and what the ceiling is without them. It must be honest about immovable gaps — telling someone with 2 years of experience that they need 5 is useful; implying a course fixes it is not. Aggregated across a `title_family` it becomes "the three skills most often missing across your matches", which is the genuinely valuable version and the reason this deserves proper design rather than a corner of R2.

**Acceptance criteria.** `AC-MATCH-08.1` (R3) Recommendations are derived only from stored components, with no new AI call per job. `AC-MATCH-08.2` (R3) Immovable constraints are labelled as such.
**Tests.** `T-MATCH-08.1`–`.2` `tests/unit/test_gap_analysis.py` (R3).

---

## 8. The feed sufficiency invariant — `MATCH-09` — **added in v2.1**

**Objective.** Turn "sees at least fifty jobs scored against that profile" from a sentence into a checkable invariant, and specify what the product does when fifty do not exist — which for a real user with narrow preferences is the common case, not the edge case.

### 8.1 Three different claims, separated

v2.0's exit sentence could be read three ways, and an agent implementing the feed would have had to guess. The terms are now fixed:

| Term | Definition | Where it lives |
|---|---|---|
| **scored** | A `match_scores` row exists for `(user, job)` with a complete `explain` payload (§3) | `match_scores` |
| **eligible** | `scored` **and** `score ≥ user.settings.match_threshold` **and** `job.status == "active"` **and** no `user_job_actions` row of `hidden`/`not_interested` for that pair | Computed by the feed query |
| **shown** | `eligible` **and** returned within the pages the user has actually requested | The response |

The exit sentence means **eligible**, at the default threshold of 60. It does not mean "scored" (which would let a feed of 50 rows at score 12 pass) and it does not mean "shown on page one" (the page size is 25).

### 8.2 The gate invariant

**Constraints.** Measured against two named fixtures, so the gate is reproducible rather than dependent on whatever staging happens to hold:

- **The reference profile** — `tests/fixtures/profiles/reference.json`: a mid-level full-stack engineer, 40 months' experience, 12 confirmed canonical skills, two title families, two Indian metros plus `remote_mode: any`, `salary_min` set, no exclusions. Committed, scrubbed, and deliberately *ordinary*: a profile chosen to make the gate pass would make the gate meaningless.
- **The reference corpus** — the seeded staging database: ≥5,000 `active` jobs from ≥3 connectors, produced by `make seed` from committed connector fixtures, with a recorded dedup ratio.

`INV-FEED-1`, the gate invariant: for the reference profile against the reference corpus, at the default threshold, **`|eligible| ≥ 50`**, the first page returns 25 items each carrying a complete explain payload, and 50 items are reachable within two pages.

- The gate is a statement about the **seeded corpus**, not a promise to every user (§8.5). It proves the pipeline produces enough signal end to end; it does not claim every profile will find fifty matches.
- The gate is asserted at the R1 gate (`00-scope-and-phases.md` §3.1) and re-asserted nightly, so a normalization or scoring change that quietly thins the feed is caught by a number rather than by someone noticing.

### 8.3 Scoring freshness — the invariant that makes the feed honest

**Constraints.** A feed can be thin for two entirely different reasons: nothing matches, or scoring has not caught up. The second is a defect and must be measurable.

`INV-FEED-2`: for a user active in the last 30 days, **≥99% of jobs that passed the candidate-set gate (§5) and were ingested more than 15 minutes ago have a `match_scores` row**. The 1% allowance covers in-flight chunks, not a backlog.

- Measured by a nightly job comparing candidate-set membership against `match_scores`, reported as `scoring_coverage{user_cohort}` on `/metrics`, and alerting below 95%.
- A profile change resets the clock for that user: coverage is measured against the current `profile_version`, so a stale score is not counted as coverage.
- This is what makes the "still scoring" state in §8.4 honest rather than a permanent excuse.

### 8.4 What the product does when fifty do not exist

**Constraints.** An ordered ladder. The product never pads the feed, never silently relaxes a filter, and never presents a low score as a match.

1. **Show what exists.** The feed returns every eligible job, in order, however few. No padding with sub-threshold jobs, no injected "you might also like".
2. **Distinguish the two empty states, because they mean opposite things.**
   - *Still scoring* — `scored == 0` for this `profile_version` **and** a scoring task for this user is queued or running. The UI says scoring is in progress and polls; this is a normal state for the first minutes after onboarding, and v2.0 never specified it.
   - *Nothing matches* — scoring is complete for this `profile_version` and `eligible == 0`. The UI says so plainly and offers the widening panel below.
3. **Offer widening, computed from stored rows.** When `eligible < 20`, the feed response carries a `widen` block naming up to three highest-yield relaxations with the count each would add: lowering the threshold to a stated value, accepting `remote_mode: remote`, or adding a named adjacent title family. Counts come from **stored `match_scores` rows** — no rescore, no AI call, no extra request.
4. **Never auto-relax.** The threshold and the preferences are the user's. Widening is a suggestion with a count and a one-tap action that changes their settings explicitly.
5. **Say why a job is absent, when asked.** A job the user can find by search but not in the feed shows a reason on its detail view: below threshold (with its score), hidden, or expired. A feed that silently omits things is the failure this whole module exists to avoid.

### 8.5 What this invariant is not

Stated explicitly so no one turns it into an accidental SLA:

- **Not a per-user guarantee.** A user seeking "Rust roles in Kochi, onsite, ₹60L+" will not have fifty eligible jobs and the product must not pretend otherwise. `INV-FEED-1` is a gate on the reference fixtures.
- **Not a reason to lower the threshold's default.** If the gate fails, the fix is corpus coverage or scoring correctness, never a cheaper default that manufactures matches.
- **Not a claim about quality.** Fifty eligible jobs at score 60 is a floor on volume. Whether they are *good* is what the feedback loop (`MATCH-06`, R2) is for.

**Inputs.** The reference profile; the reference corpus; stored `match_scores`; the user's threshold and actions.

**Outputs.** `GET /matches` with a `widen` block and an explicit `feed_state ∈ {scoring, empty, sparse, full}`; `scoring_coverage` metric; the gate assertion.

**Acceptance criteria.**
- `AC-MATCH-09.1` `INV-FEED-1` holds: the reference profile against the reference corpus yields ≥50 eligible jobs, 25 on the first page, 50 within two pages, every item with a complete explain payload.
- `AC-MATCH-09.2` The three terms are distinguishable in the API: the response reports `scored_count`, `eligible_count`, and the returned page, and a fixture with 60 scored / 30 eligible reports exactly that.
- `AC-MATCH-09.3` `INV-FEED-2` holds on the seeded database: ≥99% coverage for active users at the current `profile_version`, and the metric is exposed.
- `AC-MATCH-09.4` `feed_state` is `scoring` when a task is in flight and nothing is scored, `empty` when scoring is complete and nothing is eligible, `sparse` below 20, `full` at or above 20 — each asserted from a seeded state.
- `AC-MATCH-09.5` The two empty states render different copy in both clients, and the `scoring` state polls and resolves without a manual refresh.
- `AC-MATCH-09.6` The `widen` block names at most three relaxations with counts derived only from stored rows; the endpoint issues no scoring work and no AI call while producing it.
- `AC-MATCH-09.7` No code path lowers a user's threshold or alters their preferences without an explicit user action.
- `AC-MATCH-09.8` The feed never returns a job below the user's threshold, verified by asserting the minimum score across a full traversal.
- `AC-MATCH-09.9` A job detail view for a job absent from the feed states which of the three reasons applies.
- `AC-MATCH-09.10` The reference profile and corpus are committed fixtures, and the gate assertion runs nightly as well as at the R1 gate.

**Tests.**
- `T-MATCH-09.1` `tests/integration/test_feed_sufficiency.py` (also the R1 gate evidence).
- `T-MATCH-09.2` `tests/integration/test_feed_counts.py`.
- `T-MATCH-09.3` `tests/integration/test_scoring_coverage.py` (nightly).
- `T-MATCH-09.4` `tests/integration/test_feed_states.py`.
- `T-MATCH-09.5` `apps/web/.../feed-states.test.tsx`, `apps/mobile/test/feed_states_test.dart`.
- `T-MATCH-09.6` `tests/integration/test_widen_block.py`.
- `T-MATCH-09.7` `tests/spec/test_no_auto_relax.py`.
- `T-MATCH-09.8` `tests/integration/test_threshold_floor.py`.
- `T-MATCH-09.9` `tests/integration/test_absence_reason.py`.
- `T-MATCH-09.10` `tests/spec/test_reference_fixtures.py`.
