# 03 — Candidate Profile

**Module:** `apps/api/app/modules/profile`
**Track:** R1 except §5 (R2), §6 (R2), §7 (R3)
**Depends on:** `01-foundations.md`, `17-data-model.md` §2.5, `05-ai-layer.md` (embeddings)
**Requirements:** `PROF-01` … `PROF-07`
**Public API:** `ProfileService.get`, `.patch`, `.patch_preferences`, `.confirm_fields`, `.stage_extraction`, `.apply_staged`, `.canonicalize`, `.embedding_for`
**Publishes:** `ProfileUpdated`, `ProfileConfirmed`. **Consumes:** `ResumeExtracted`.

The profile is the input to everything downstream. Two properties matter more than any feature here: every field knows **where it came from**, and every skill is **canonical**. Without the first, HR-7 is unenforceable; without the second, every match score is silently wrong.

---

## 1. Profile document and versioning — `PROF-01`

**Objective.** One structured, editable representation of the candidate that downstream modules can consume without re-parsing anything.

**Constraints.**
- Shape as in `17-data-model.md` §2.5. Sections: `identity`, `contact`, `skills[]`, `experience[]`, `education[]`, `certifications[]`, `projects[]`, `languages[]`, plus derived `total_experience_months` and `seniority`, plus `preferences`.
- Exactly one profile per user, created empty at registration so no code path has to handle "profile missing".
- `version` increments on every accepted mutation and is stamped onto `match_scores` (`17-data-model.md` §2.8), so any score is attributable to the profile that produced it.
- Derived fields are computed, never user-set: `total_experience_months` from `experience[]` with **overlap collapsing** (two concurrent jobs are not double-counted — this is a common source of inflated seniority), and `seniority` from months plus titles via a documented table.
- Empty is a valid state. The profile API never 404s for an authenticated user.
- Section arrays are ordered and the order is user-controlled and preserved; `resume_suggestions` in `09-apply.md` reference items by index, so reordering must renumber those references or invalidate the pack (see `AC-PROF-01.6`).

**Inputs.** `PATCH /profile` partial bodies; staged extractions.

**Outputs.** `profiles` document; `ProfileUpdated{user_id, profile_version, changed_paths}`.

**Acceptance criteria.**
- `AC-PROF-01.1` `GET /profile` for a brand-new user returns a valid empty profile with `version: 1`, not 404.
- `AC-PROF-01.2` Any accepted mutation increments `version` by exactly one and publishes `ProfileUpdated` with the changed dotted paths.
- `AC-PROF-01.3` Two overlapping experience entries (Jan–Dec and Jun–Dec of the same year) yield 12 months, not 19.
- `AC-PROF-01.4` `seniority` follows the documented table for boundary cases at 0, 24, 60, 96, and 144 months, and a title containing "Lead" or "Principal" raises it by one level at most.
- `AC-PROF-01.5` A `PATCH` with an unknown field is rejected `422` (strict mode), not silently ignored.
- `AC-PROF-01.6` Reordering `experience[]` invalidates any `draft` pack whose `resume_suggestions` target a moved index, setting the pack back to `draft` with a `stale_targets` flag; an `approved` pack is never mutated (it is immutable) but is marked `superseded` if its targets moved.
- `AC-PROF-01.7` Concurrent `PATCH` requests are serialized by an optimistic check on `version`; the loser gets `409 profile_version_conflict` with the current version.

**Tests.**
- `T-PROF-01.1` `tests/integration/test_profile_empty.py`.
- `T-PROF-01.2` `tests/integration/test_profile_versioning.py`.
- `T-PROF-01.3` `tests/unit/test_experience_months.py` (hypothesis: total ≤ span of the union).
- `T-PROF-01.4` `tests/unit/test_seniority_table.py`.
- `T-PROF-01.5` `tests/integration/test_profile_strict.py`.
- `T-PROF-01.6` `tests/integration/test_pack_target_staleness.py`.
- `T-PROF-01.7` `tests/integration/test_profile_concurrency.py`.

---

## 2. Provenance: source, confidence, confirmed — `PROF-03`

**Objective.** Never let a machine's guess masquerade as something the user said (HR-7).

**Constraints.**
- Every item in `skills`, `experience`, `education`, `certifications`, `projects`, `languages`, and every scalar in `identity`/`contact`, carries `source ∈ {ai, user}`, `confidence: 0..1` (1.0 when `source: user`), and `confirmed: bool`.
- Rules, all enforced in the service, not the router:
  - A field the user typed or edited becomes `source: user`, `confidence: 1.0`, `confirmed: true`, in one operation. There is no way to type a value and leave it unconfirmed.
  - An AI-extracted field starts `confirmed: false` regardless of confidence. High confidence is not consent.
  - Confirming is explicit and per-field or per-section; there is a "confirm all" but it names the count and is a deliberate action.
  - Re-extraction may **never** overwrite a field with `confirmed: true`. It stages a suggestion (`staged_extraction`) and the user chooses.
  - `confirmed: false` fields are excluded from pack generation entirely (HR-7) and are visually flagged in both clients until reviewed.
- `evidence` — a verbatim span of ≤15 words from the resume — is stored for every AI-extracted item, so the review screen can show *why* the machine believes it.

**Inputs.** Extraction output; user edits; confirm actions.

**Outputs.** Provenance triples on every field; `ProfileConfirmed` when the last unconfirmed field is resolved.

**Acceptance criteria.**
- `AC-PROF-03.1` Every leaf field in a seeded extracted profile carries all three provenance keys; a schema test enumerates them.
- `AC-PROF-03.2` A user edit sets `source: user, confidence: 1.0, confirmed: true` atomically; no state exists where a user-typed value is unconfirmed.
- `AC-PROF-03.3` An extraction with `confidence: 0.99` still yields `confirmed: false`.
- `AC-PROF-03.4` Re-extraction against a profile with confirmed fields leaves every confirmed value byte-identical and places the alternatives in `staged_extraction`.
- `AC-PROF-03.5` A pack generation request on a profile whose relevant fields are unconfirmed excludes them from the prompt — asserted by inspecting the rendered prompt, not the output.
- `AC-PROF-03.6` Both clients render an "unconfirmed" affordance for every such field (component test).
- `AC-PROF-03.7` Every AI-extracted item has non-empty `evidence` of ≤15 words, and the evidence is a verbatim substring of the resume text.

**Tests.**
- `T-PROF-03.1` `tests/spec/test_provenance_coverage.py`.
- `T-PROF-03.2` `tests/unit/test_provenance_rules.py`.
- `T-PROF-03.3` `tests/unit/test_confidence_not_consent.py`.
- `T-PROF-03.4` `tests/integration/test_reextraction_safety.py`.
- `T-PROF-03.5` `tests/integration/test_pack_prompt_excludes_unconfirmed.py`.
- `T-PROF-03.6` `apps/web/.../profile-field.test.tsx`, `apps/mobile/test/profile_field_test.dart`.
- `T-PROF-03.7` `tests/unit/test_evidence_spans.py`.

---

## 3. Preferences — `PROF-02`

**Objective.** Capture enough intent to build a candidate set and to penalize what the user does not want.

**Constraints.**
- Fields and caps: `titles` (≤10 free text), `title_families` (derived from titles, ≤5, user-overridable), `locations` (≤10 structured), `remote_mode ∈ {onsite, hybrid, remote, any}`, `open_to_relocation: bool`, `salary_min: Money | null`, `notice_period_days`, `employment_types[]`, `company_size_pref`, `exclude_industries[]` (≤20), `exclude_keywords[]` (≤30, each ≤40 chars).
- `title_families` is what the candidate-set query indexes on (`17-data-model.md` §3), so a free-text title must map to at least one family or the user gets no feed. If mapping yields nothing, the API returns `422 unmappable_title` naming the title and offering the family list — silently producing an empty feed is the worst possible outcome here.
- Preference changes publish `ProfileUpdated` and therefore trigger a debounced rescore (`01-foundations.md` §9).
- `exclude_keywords` are matched case-insensitively against title, company, and description as **whole words**, not substrings — "IT" must not exclude "audit".
- `salary_min` currency is the user's, and comparison across currencies goes through `shared/fx.py` with the rate recorded in the explain payload (`08-matching.md` §2).
- Defaults on first save: `remote_mode: any`, `open_to_relocation: false`, `employment_types: [full_time]`, `match_threshold: 60`.

**Inputs.** `PATCH /profile/preferences`.

**Outputs.** `profiles.preferences`; `ProfileUpdated`.

**Acceptance criteria.**
- `AC-PROF-02.1` Each cap is enforced with a `422` naming the field and the limit.
- `AC-PROF-02.2` A title that maps to no family returns `422 unmappable_title` with the available families; the preferences are not saved.
- `AC-PROF-02.3` Saving preferences enqueues exactly one rescore per 60-second debounce window regardless of how many saves occur in it.
- `AC-PROF-02.4` `exclude_keywords: ["IT"]` does not exclude a job whose description contains "audit" or "digital"; it does exclude one titled "IT Support".
- `AC-PROF-02.5` A `salary_min` in USD compared against an INR listing produces a verdict plus the rate and its date.
- `AC-PROF-02.6` First save applies the documented defaults for omitted fields.

**Tests.**
- `T-PROF-02.1` `tests/integration/test_preference_caps.py`.
- `T-PROF-02.2` `tests/integration/test_unmappable_title.py`.
- `T-PROF-02.3` `tests/integration/test_rescore_debounce.py`.
- `T-PROF-02.4` `tests/unit/test_exclude_keywords.py`.
- `T-PROF-02.5` `tests/unit/test_salary_currency.py`.
- `T-PROF-02.6` `tests/integration/test_preference_defaults.py`.

---

## 4. Skill canonicalization — `PROF-06`

**Objective.** "ReactJS", "React.js", "react" and "React 18" are one skill, everywhere, or scoring is fiction.

**Constraints.**
- `skill_aliases` (`17-data-model.md` §2) maps `_id` (the alias, normalized) → `canonical` → `category`. Seeded with ~600 technology skills and their common aliases, committed as a reviewable YAML in `profile/skills_seed.yaml` and loaded by a migration.
- Normalization before lookup: lowercase, trim, collapse internal whitespace, strip version numbers and trailing punctuation, strip a leading "experience with"/"knowledge of", NFKC-normalize. Deterministic and pure.
- Lookup order: exact alias → exact canonical → `rapidfuzz` ratio ≥92 against canonicals (guarding against typos) → **unmapped**.
- An unmapped skill is **kept**, not dropped: stored with `canonical: null` and surfaced in the admin unmapped-skills report (`12-admin.md` §4, R2) so the alias table grows from real data. It scores as a non-match, which is honest.
- Comparison anywhere in the product uses `canonical`. Comparing `raw` is a defect (`01-foundations.md` §3).
- The same function canonicalizes job skills (`07-ingestion-and-jobs.md` §4) — one implementation, called from both, living in `profile/skills.py` and exposed on the module's public API.
- Categories exist so the explain payload can say "you are missing 2 of 3 required *infrastructure* skills", which is more useful than a flat list.

**Inputs.** Raw skill strings from extraction, from job descriptions, and from user input.

**Outputs.** `canonicalize(raw) -> SkillName | None`; `skill_aliases`; the unmapped report.

**Acceptance criteria.**
- `AC-PROF-06.1` A fixture of 200 raw strings maps to the expected canonical for each; the fixture includes casing, punctuation, versions, plurals, and the "experience with X" form.
- `AC-PROF-06.2` `canonicalize` is pure: no I/O beyond an injected alias map, and identical output for identical input across 1,000 hypothesis-generated strings.
- `AC-PROF-06.3` An unmapped skill is retained with `canonical: null` and appears in the unmapped report exactly once with a count.
- `AC-PROF-06.4` A one-character typo of a canonical ("pyhton") maps correctly; a genuinely different skill ("puppet" vs "puppeteer") does **not** collapse — both directions asserted.
- `AC-PROF-06.5` A grep finds no comparison of a `raw` skill string outside `skills.py` and its tests.
- `AC-PROF-06.6` The seed file loads without duplicate aliases and without an alias whose value is itself an alias (no chains).

**Tests.**
- `T-PROF-06.1` `tests/unit/test_canonicalize_fixtures.py`.
- `T-PROF-06.2` `tests/unit/test_canonicalize_purity.py`.
- `T-PROF-06.3` `tests/integration/test_unmapped_skills.py`.
- `T-PROF-06.4` `tests/unit/test_fuzzy_skill_boundaries.py`.
- `T-PROF-06.5` `tests/spec/test_no_raw_skill_comparison.py`.
- `T-PROF-06.6` `tests/unit/test_skill_seed_integrity.py`.

---

## 5. Completeness score — `PROF-05` — **Track: R2**

**Objective.** Tell the user what is missing in a way that predicts better matches, not a vanity percentage.

**Constraints.** Weighted checklist, each item worth points and each mapped to a concrete prompt: preferences set (25), ≥5 confirmed skills (20), ≥1 confirmed experience with bullets (20), headline and summary (10), education (5), all extracted fields confirmed (10), answer bank ≥5 entries (10). The prompt text names the benefit ("adding a salary floor lets us tell you when a listing is below it"), never a bare instruction. Recomputed on `ProfileUpdated`, cached on the document.

**Acceptance criteria.** `AC-PROF-05.1` Score is deterministic from the profile and sums to 100 when complete. `AC-PROF-05.2` Each incomplete item yields exactly one prompt naming its benefit. `AC-PROF-05.3` It is recomputed within one debounce window of a change. `AC-PROF-05.4` A user with 100 has no prompts.
**Tests.** `T-PROF-05.1`–`.4` `tests/unit/test_completeness.py`, `tests/integration/test_completeness_recompute.py`.

---

## 6. Field audit history — `PROF-07` — **Track: R2**

**Objective.** Be able to answer "why does my profile say that" a month later.

**Constraints.** `profile_audit` row per changed leaf: `field_path`, `old`, `new`, `actor ∈ {user, ai, system}`, `at`, `request_id`. Batched per mutation. Values are stored **redacted for contact fields** (phone, email) — the audit records that a change happened, not a second copy of the PII. Retained with the profile; purged with the account. Read-only API, cursor-paginated.

**Acceptance criteria.** `AC-PROF-07.1` Every leaf change writes exactly one row with the correct actor. `AC-PROF-07.2` Contact-field rows store a masked value. `AC-PROF-07.3` No API can modify or delete a row. `AC-PROF-07.4` Rows are purged with the account.
**Tests.** `T-PROF-07.1`–`.4` `tests/integration/test_profile_audit.py`.

---

## 7. Multiple resume versions — `PROF-04` — **Track: R3**

**Objective.** Let a user keep a Backend resume and a Full-stack resume and apply with the right one.

**Constraints (design only, do not build in R1/R2).** The profile skill set becomes the **union** across versions, each skill recording which versions evidence it. One version is `is_default`. A pack references the version used. Match scoring uses the union (a job matching any version is worth showing) but the explain payload names which version is the better fit. `experience[]` stays single — a person has one work history; only emphasis differs, which is what `resume_suggestions` already expresses. The migration from R1 is additive: the single existing resume becomes the default version.

**Acceptance criteria.** `AC-PROF-04.1` (R3) Union semantics documented in an ADR before implementation. `AC-PROF-04.2` (R3) R1 data migrates without a rescore.
**Tests.** `T-PROF-04.1`–`.2` `tests/spec/test_adr_present.py` (the ADR must exist) and `tests/integration/test_multi_resume_migration.py` (R3 only).
