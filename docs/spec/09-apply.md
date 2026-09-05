# 09 — Application Engine

**Module:** `apps/api/app/modules/apply`
**Track:** R1 except §7 (`APPLY-06`, R3) and §8 (`APPLY-08`, R3)
**Depends on:** `03-profile.md` §2, `08-matching.md` §3, `05-ai-layer.md`, `17-data-model.md` §2.9, §2.12
**Requirements:** `APPLY-01` … `APPLY-08`
**Public API:** `ApplyService.generate_pack`, `.get_pack`, `.patch_item`, `.approve`, `.regenerate`, `.confirm_applied`, `.followup_draft`, `AnswerBankService.*`
**Publishes:** `PackApproved`, `AppliedConfirmed`. **Consumes:** none.

This module writes text that a user sends to an employer under their own name. That single fact sets every constraint here: nothing is asserted that the user has not confirmed (HR-4, HR-7), nothing is sent without an explicit approval (HR-1), and every artifact is recorded immutably (`APPLY-07`).

---

## 1. Answer Bank — `APPLY-01`

**Objective.** Answer the same twelve screening questions once instead of forty times.

**Constraints.**
- Canonical taxonomy in `apply/questions.yaml`: ~40 entries, each with a `key`, a canonical question text, variant phrasings, an `answer_type` (`text`, `boolean`, `money`, `duration`, `date`, `url`, `enum`), and whether it is `sensitive`. Seeded categories: work authorization, notice period, current and expected compensation, relocation, start date, years with a named technology, why this company, reason for change, portfolio and profile URLs, referral source, disability/veteran/EEO-style questions.
- **Sensitive questions are opt-in and never AI-suggested.** EEO-style demographic questions, disability status, and current salary are marked `sensitive: true`: the product stores an answer only if the user types one, never proposes one, and flags in the UI that these are usually optional on real forms. Suggesting an answer to a demographic question would be both useless and offensive.
- Matching a detected question to the bank: normalized exact → `rapidfuzz.token_set_ratio ≥ 85` against canonical text and variants → embedding nearest neighbour ≥ 0.80 → otherwise `needs_user`. Every match records which stage matched and its score, so a bad match is diagnosable.
- AI suggestion (`POST /answer-bank/suggest`) proposes answers **only** for non-sensitive keys, **only** from confirmed profile fields, each arriving `confirmed: false` and requiring the user to accept. An unaccepted suggestion is never used in a pack (HR-7).
- `answer_type` is enforced: a `money` answer stores a `Money`, a `duration` stores days. Free text for a structured question is rejected, because a pack that writes "60" into a currency field is worse than no answer.
- Cap 100 entries per user. Uniqueness per `(user_id, question_key)` for keyed entries.

**Inputs.** User input; confirmed profile; detected questions.

**Outputs.** `answer_bank` documents; question-match results.

**Acceptance criteria.**
- `AC-APPLY-01.1` The seeded taxonomy loads with no duplicate keys and every entry carrying an `answer_type` and a `sensitive` flag.
- `AC-APPLY-01.2` A 60-question fixture of real-world phrasings matches to the expected key with the expected match stage; each of the three stages is exercised, and 5 deliberately unmatchable questions yield `needs_user`.
- `AC-APPLY-01.3` `POST /answer-bank/suggest` proposes nothing for any `sensitive: true` key, across the whole taxonomy.
- `AC-APPLY-01.4` Every suggestion arrives `source: ai, confirmed: false`; using an unconfirmed suggestion in a pack is impossible (asserted on the rendered prompt).
- `AC-APPLY-01.5` A free-text answer to a `money` question is rejected `422 answer_type_mismatch`.
- `AC-APPLY-01.6` The 101st entry is rejected; a second entry for the same `question_key` updates rather than duplicating.
- `AC-APPLY-01.7` Each match result records the stage and score.

**Tests.**
- `T-APPLY-01.1` `tests/unit/test_question_taxonomy.py`.
- `T-APPLY-01.2` `tests/unit/test_question_matching.py`.
- `T-APPLY-01.3` `tests/integration/test_sensitive_questions.py`.
- `T-APPLY-01.4` `tests/integration/test_pack_prompt_excludes_unconfirmed.py` (shared).
- `T-APPLY-01.5` `tests/unit/test_answer_types.py`.
- `T-APPLY-01.6` `tests/integration/test_answer_bank_limits.py`.
- `T-APPLY-01.7` `tests/unit/test_match_diagnostics.py`.

---

## 2. Pack generation — `APPLY-02`

**Objective.** Produce a first draft of everything the user has to write, grounded entirely in what they have confirmed.

**Constraints.**
- Inputs to the prompt, and nothing else: **confirmed** profile fields only (HR-7), the job (title, company, description within the 8,000-character cap), the relevant answer-bank entries, the tone, the match explain payload's `missing_required` list, and optional user notes. Unconfirmed extractions are excluded from the prompt entirely, not merely deprioritized.
- Output schema `ApplicationPack` (§2.1). `quality` tier (`05-ai-layer.md` §2).
- Every factual claim in generated prose carries a `source_path` pointing at the profile field or the job that supports it. The prompt requires this per claim; the anti-fabrication check (§4) verifies it independently rather than trusting it.
- Length limits are hard: summary ≤80 words, cover letter ≤250 words. A model exceeding them is retried once with the count in the repair prompt, then truncated at a sentence boundary with a flag.
- The `missing_required` skills from matching are passed so the letter can **address a gap honestly** ("I have not used Kubernetes in production, though I have run containerised services with Docker Compose") rather than ignoring or bluffing it. The prompt forbids claiming a missing skill.
- Tone presets: `concise`, `warm`, `formal`. Tone changes wording only; it never changes which facts are asserted, and a test asserts the claim set is identical across tones for the same inputs.
- Async, idempotent by `Idempotency-Key` (`01-foundations.md` §8), streamed by SSE with stages `gathering → generating → checking → ready`.
- Regeneration creates a new draft; it never edits an approved pack (§3).
- On budget exhaustion, `503 ai_budget_exceeded` with `Retry-After`, and any user edits already made are preserved (`05-ai-layer.md` §3).

### 2.1 `ApplicationPack` schema

Carried from BRD v1.0 Appendix C with two additions marked:

```json
{
  "summary": { "text": "<=80 words", "claims": [ { "span": "...", "source_path": "profile.experience.0.bullets.2" } ] },
  "cover_letter": { "text": "<=250 words", "claims": [ ... ] },
  "answers": [ { "question": "str", "question_key": "str|null", "answer": "str",
                 "source": "answer_bank:<id>|generated", "confidence": "0-1", "needs_user": "bool" } ],
  "resume_suggestions": [ { "type": "reorder|emphasize|reword",
                            "target": "profile.experience.1.bullets.0",
                            "suggestion": "str", "reason": "str" } ],
  "unanswerable_questions": ["str"],
  "gap_acknowledgements": [ { "skill": "kubernetes", "phrasing": "str" } ],
  "suspected_injection": "bool"
}
```

Additions: `gap_acknowledgements`, so the honest handling of a missing skill is a first-class, reviewable output rather than buried in prose; and `suspected_injection` per HR-11 (a job description that tries to manipulate the letter is worth flagging to the user before they send it). Removal: `tone` no longer appears inside `cover_letter` — it lives once, at the top level of the pack document, as the parameter generation was run with (`17-data-model.md` §2.9, consistency finding F6).

**Inputs.** Confirmed profile, job, answer bank, tone, notes, `missing_required`.

**Outputs.** `application_packs` document with `status: draft`; `audit_log` `pack_generated`; SSE events.

**Acceptance criteria.**
- `AC-APPLY-02.1` The rendered prompt contains no unconfirmed profile value, asserted by seeding a profile with distinctive unconfirmed strings and searching the captured prompt (HR-7).
- `AC-APPLY-02.2` Every claim in `summary` and `cover_letter` has a `source_path` that resolves to an existing confirmed profile field or to a job field.
- `AC-APPLY-02.3` A missing required skill never appears as a possessed skill in the letter; where addressed, it appears in `gap_acknowledgements` with phrasing that does not claim experience (checked over the golden set).
- `AC-APPLY-02.4` The three tones produce identical claim sets (same `source_path` multiset) for the same inputs.
- `AC-APPLY-02.5` Word limits hold after generation, including in the truncated-fallback path.
- `AC-APPLY-02.6` A question with no answer-bank match appears in `answers` with `needs_user: true` **or** in `unanswerable_questions`, never silently answered.
- `AC-APPLY-02.7` The same `Idempotency-Key` twice produces one pack and one AI charge.
- `AC-APPLY-02.8` A budget-exhausted request returns 503 with `Retry-After` and preserves prior edits.
- `AC-APPLY-02.9` An injection payload in the job description yields `suspected_injection: true` and no instruction-following in the output.

**Tests.**
- `T-APPLY-02.1` `tests/integration/test_pack_prompt_excludes_unconfirmed.py`.
- `T-APPLY-02.2` `tests/unit/test_claim_paths.py`.
- `T-APPLY-02.3` `tests/ai/test_gap_honesty.py`.
- `T-APPLY-02.4` `tests/ai/test_tone_claim_invariance.py`.
- `T-APPLY-02.5` `tests/unit/test_pack_lengths.py`.
- `T-APPLY-02.6` `tests/unit/test_answer_coverage.py`.
- `T-APPLY-02.7` `tests/integration/test_idempotency.py` (shared).
- `T-APPLY-02.8` `tests/ai/test_degradation.py` (shared).
- `T-APPLY-02.9` `tests/ai/test_injection_corpus.py` (shared).

---

## 3. Editing, approval and immutability — `APPLY-03`

**Objective.** The user is the author. Approval is a deliberate act, and what was approved can be proven later.

**Constraints.**
- Every item is editable: `PATCH /applications/{id}/pack/items/{key}` where key is `summary`, `cover_letter`, `answers.<index>`, or `resume_suggestions.<index>`. An edit sets `edited_by_user: true` on that item and **clears the item's claims** — once the user has rewritten it, our claim mapping no longer describes it, and pretending otherwise would let a fabrication check pass on text it never examined.
- An edited item is re-run through the anti-fabrication check (§4) on approval, not on every keystroke.
- `status: draft → approved` only, and only when: no `fabrication_flags` remain `open` (§4), and every `answers[].needs_user` is resolved (answered or explicitly skipped). Otherwise `409 pack_not_approvable` with the specific blockers listed.
- **An approved pack is immutable.** Editing one creates a new pack document with `supersedes` set and the old one moved to `superseded`. The approved content and its `content_hash` are never rewritten (`APPLY-07`).
- `content_hash` is `sha256` over the canonicalized items at the moment of approval, recorded in `audit_log` — so "what did I send them" is answerable months later even after five revisions.
- Only an `approved` pack can be used in the apply flow (§5) and referenced by `applications.current_pack_id`.
- Approval is idempotent: approving an already-approved pack returns the same result.
- `PackApproved{user_id, application_id, pack_id, content_hash}` is published.

**Inputs.** Item patches; the approve call.

**Outputs.** `status`, `content_hash`, `approved_at`; `audit_log` `pack_approved`; `PackApproved`.

**Acceptance criteria.**
- `AC-APPLY-03.1` Editing an item sets `edited_by_user: true` and clears that item's claims.
- `AC-APPLY-03.2` Approval with an open fabrication flag returns `409` naming the flag; with an unresolved `needs_user` answer, `409` naming the question.
- `AC-APPLY-03.3` A `PATCH` against an approved pack returns `409 pack_immutable`; the revise endpoint creates a new pack with `supersedes` set and the original byte-identical.
- `AC-APPLY-03.4` `content_hash` recomputed from the stored items equals the audited hash, for every approved pack in a seeded set.
- `AC-APPLY-03.5` The apply flow rejects a `draft` pack.
- `AC-APPLY-03.6` Double approval yields one `pack_approved` audit row.
- `AC-APPLY-03.7` An edited item is re-checked for fabrication at approval time (a fabricated edit blocks approval).

**Tests.**
- `T-APPLY-03.1` `tests/integration/test_pack_editing.py`.
- `T-APPLY-03.2` `tests/integration/test_pack_approval_gates.py`.
- `T-APPLY-03.3` `tests/integration/test_pack_immutability.py`.
- `T-APPLY-03.4` `tests/integration/test_content_hash.py`.
- `T-APPLY-03.5` `tests/integration/test_apply_requires_approved.py`.
- `T-APPLY-03.6` `tests/integration/test_approval_idempotence.py`.
- `T-APPLY-03.7` `tests/integration/test_edit_refabrication_check.py`.

---

## 4. Anti-fabrication — `APPLY-04`, HR-4

**Objective.** No sentence the user sends asserts something their confirmed profile does not support. This is the highest-consequence control in the product: a fabricated claim in a cover letter is a withdrawn offer.

**Constraints.**

Three layers, deliberately redundant, because any one of them can fail.

**Layer 1 — prompt.** The system prompt forbids new facts and requires a `source_path` per claim. Necessary but not sufficient; a model's promise is not a control.

**Layer 2 — claim verification.** Every `claims[].source_path` must resolve to an existing **confirmed** profile field or a job field, and the claim's `span` must appear in the item's text. An unresolvable path, a path to an unconfirmed field, or a span not present in the text is a flag.

**Layer 3 — independent entity extraction.** The generated text is parsed **without reference to the model's claims** for: organizations, dates and durations, degrees and institutions, job titles, named tools and technologies, and numbers (team sizes, percentages, currency amounts, years). Each extracted entity must be traceable to a confirmed profile field (exact, alias-normalized for skills, or numeric equality) or to the job posting. Untraceable entities are flagged with their span and type.

- Extraction is deterministic: regex and dictionary based, plus the canonical skill vocabulary. **No LLM in the checker** — a model checking a model's output shares its failure modes, and the checker must be auditable.
- The checker errs toward flagging. A false positive costs the user one click ("keep anyway"); a false negative costs them a job.
- **Numbers are the highest-risk category** and are checked strictly: any number in the text that is not present in a confirmed profile field, in the job, or in a small allowlist of harmless constructions (a year that matches an employment date, "one of", ordinals in list phrasing) is flagged. "Led a team of 12" where no profile field says 12 is exactly the failure this exists to catch.
- `fabrication_flags[].status ∈ {open, resolved, overridden}`. `resolved` means the user edited the text and the re-check passes. `overridden` means the user explicitly chose to keep it and is recorded in `audit_log` as `fabrication_overridden` with the span — the user may always override; the product may never do it for them.
- A pack with an `open` flag cannot be approved (`AC-APPLY-03.2`).
- The UI highlights each flagged span in place with its reason, and offers edit or override. A flag the user cannot see is not a control.

**Inputs.** Generated or edited item text; confirmed profile; the job.

**Outputs.** `fabrication_flags[]`; `audit_log` `fabrication_overridden`.

**Acceptance criteria.**
- `AC-APPLY-04.1` A corpus of 40 crafted fabrications is caught: an invented employer, an inflated tenure, a degree not held, a team size absent from the profile, a percentage improvement not in any bullet, a skill absent from the profile, a certification not held, a title never held, an invented client name, a fabricated award. Recall on the corpus is 100% — this is a hard gate, not a target.
- `AC-APPLY-04.2` A corpus of 40 legitimate texts produces a false-positive rate under 15%, and every false positive is overridable in one action.
- `AC-APPLY-04.3` A claim whose `source_path` points to an **unconfirmed** field is flagged even though the path resolves.
- `AC-APPLY-04.4` A pack with an open flag cannot be approved.
- `AC-APPLY-04.5` An override writes an audit row containing the span and the entity type, and the flag becomes `overridden`, never disappearing.
- `AC-APPLY-04.6` The checker makes no AI call (asserted with respx in strict mode over the check path).
- `AC-APPLY-04.7` Editing flagged text so it is supportable re-checks to `resolved` without an override.
- `AC-APPLY-04.8` Both clients render each flagged span highlighted with its reason and both actions (component tests).
- `AC-APPLY-04.9` The checker is deterministic: the same text and profile yield the same flags across 1,000 runs.

**Tests.**
- `T-APPLY-04.1` `tests/unit/test_fabrication_recall.py`, corpus at `tests/fixtures/fabrication/positive/`.
- `T-APPLY-04.2` `tests/unit/test_fabrication_precision.py`, corpus at `.../negative/`.
- `T-APPLY-04.3` `tests/unit/test_claim_confirmation.py`.
- `T-APPLY-04.4` `tests/integration/test_pack_approval_gates.py` (shared).
- `T-APPLY-04.5` `tests/integration/test_fabrication_override.py`.
- `T-APPLY-04.6` `tests/unit/test_checker_no_ai.py`.
- `T-APPLY-04.7` `tests/integration/test_edit_refabrication_check.py` (shared).
- `T-APPLY-04.8` `apps/web/.../fabrication-flag.test.tsx`, `apps/mobile/test/fabrication_flag_test.dart`.
- `T-APPLY-04.9` `tests/unit/test_checker_determinism.py`.

---

## 5. Assisted apply — `APPLY-05`, HR-1

**Objective.** Make applying on the employer's own site fast, while the product never touches the submit button.

**Constraints.**
- **The product performs no submission.** There is no code path that POSTs to an `apply_url`, and `modules/apply` has no HTTP client capable of it — the module's dependencies are checked (HR-1). This is not a policy toggle and there is no flag that enables it.
- Web: "Apply on {source}" opens `source_refs[].apply_url` in a new tab (`rel="noopener noreferrer"`). The product's own tab shows a persistent side panel with the approved pack: per-field copy buttons, the answers list, and the resume download. A "Mark as applied" action sits in the panel.
- Mobile: a bottom sheet with copy chips and "Open posting" (external browser, not an in-app webview — an in-app webview around an employer's login form is a phishing surface and a store-review risk). A local notification after 10 minutes asks whether the application was submitted.
- For a merged job, the user chooses which source to apply through; the default is `primary_source` and every source is offered with its attribution (`06-connectors.md` §4).
- Confirmation (`POST /applications/{id}/applied`) is explicit, idempotent, and carries `applied_via ∈ {external_link, manual, extension}`. It sets `applied_at`, transitions the application to `applied` (`10-tracker.md` §2), writes `audit_log` `applied_confirmed`, and publishes `AppliedConfirmed` which schedules the follow-up reminder.
- The prompt to confirm may be dismissed or deferred; it never auto-confirms. An application left unconfirmed stays `preparing`, and a nudge appears in the tracker rather than a status the user did not choose.
- Copying to the clipboard happens client-side only; no pack content is sent anywhere new.

**Inputs.** An approved pack; the chosen source.

**Outputs.** An opened external tab or browser; `applied_at`; `AppliedConfirmed`; audit row.

**Acceptance criteria.**
- `AC-APPLY-05.1` `modules/apply` contains no call capable of submitting to an external URL; a dependency and call-graph check asserts it (HR-1).
- `AC-APPLY-05.2` No flag, config value, or admin toggle enables automated submission — a search for such a flag finds none, and the absence is documented in ADR-009.
- `AC-APPLY-05.3` The web apply link carries `noopener noreferrer` and opens in a new tab; the side panel renders every approved item with a working copy action.
- `AC-APPLY-05.4` Mobile opens the posting in the external browser, never an in-app webview (asserted on the launch mode).
- `AC-APPLY-05.5` Confirmation is idempotent: two calls produce one transition, one audit row, one reminder.
- `AC-APPLY-05.6` Dismissing the confirmation leaves the application in `preparing` with a visible nudge and no `applied_at`.
- `AC-APPLY-05.7` For a merged job, each source's apply URL is offered with its attribution, and the chosen one is recorded on the application.
- `AC-APPLY-05.8` The end-to-end web and mobile journeys pass (the R1 exit sentence's apply clauses).

**Tests.**
- `T-APPLY-05.1` `tests/spec/test_no_submission_capability.py`.
- `T-APPLY-05.2` `tests/spec/test_no_autoapply_flag.py` + `tests/spec/test_adr_present.py`.
- `T-APPLY-05.3` `apps/web/.../apply-panel.test.tsx`.
- `T-APPLY-05.4` `apps/mobile/test/apply_sheet_test.dart`.
- `T-APPLY-05.5` `tests/integration/test_applied_confirmation.py`.
- `T-APPLY-05.6` `tests/integration/test_confirmation_dismissal.py`.
- `T-APPLY-05.7` `tests/integration/test_merged_apply_sources.py`.
- `T-APPLY-05.8` `apps/web/e2e/apply.spec.ts`, `apps/mobile/integration_test/apply_test.dart`.

---

## 6. Audit — `APPLY-07`

**Objective.** An immutable record of every artifact generated and every approval given.

**Constraints.**
- `audit_log` is append-only (`17-data-model.md` §2.12): the repository exposes only `append` and `find`, and the database role has no update or delete privilege on the collection (`AC-DATA-02.4`).
- Recorded kinds: `pack_generated`, `pack_approved`, `pack_superseded`, `fabrication_overridden`, `applied_confirmed`, plus the account-level kinds owned by other modules.
- Each row carries `user_id`, `kind`, `ref_id`, `content_hash` where applicable, `at`, `request_id`, and `ip_prefix` (network, not host).
- No row contains pack text — the hash plus the pack document is the record. An audit log that duplicates content doubles the deletion surface.
- The log is included in export (`AUTH-08`, R2) and purged with the account (`AUTH-07`), except the anonymized `deletion_completed` row.
- The tracker timeline (`10-tracker.md` §5) is rendered from `status_history` plus this log; the log is the source, not a copy.

**Inputs.** Module actions.

**Outputs.** `audit_log` rows.

**Acceptance criteria.**
- `AC-APPLY-07.1` Every one of the five apply kinds is written at the right moment, verified across a full journey.
- `AC-APPLY-07.2` No API or service path can update or delete a row; an attempt raises.
- `AC-APPLY-07.3` No row contains pack text (a test searches seeded rows for distinctive pack strings).
- `AC-APPLY-07.4` Rows carry `request_id` matching the originating request's logs.
- `AC-APPLY-07.5` `ip_prefix` is a network, never a full address.

**Tests.**
- `T-APPLY-07.1` `tests/integration/test_audit_coverage.py`.
- `T-APPLY-07.2` `tests/integration/test_audit_append_only.py` (shared).
- `T-APPLY-07.3` `tests/integration/test_audit_no_content.py`.
- `T-APPLY-07.4` `tests/integration/test_request_id_propagation.py` (shared).
- `T-APPLY-07.5` `tests/unit/test_ip_prefix.py`.

---

## 6.1 Follow-up draft

**Objective.** One tap turns "applied 7 days ago" into a sendable email.

**Constraints.** `POST /applications/{id}/follow-up-draft` at the `fast` tier from the application context (job, company, applied date, interview history, contacts) and confirmed profile only. Output is plain text plus a subject. Subject to the same anti-fabrication check (§4) — a follow-up that invents a conversation is as damaging as a fabricated letter. Rate limited 10/day. Degrades to a template with placeholders on budget exhaustion, rather than failing.

**Acceptance criteria.** `AC-APPLY-09.1` The draft passes the fabrication check or returns flags. `AC-APPLY-09.2` It references no interview or conversation not recorded on the application. `AC-APPLY-09.3` Budget exhaustion returns the template. `AC-APPLY-09.4` It is labelled AI-generated.
**Tests.** `T-APPLY-09.1`–`.4` `tests/integration/test_followup_draft.py`.

---

## 7. Browser extension — `APPLY-06` — **Track: R3**

**Objective.** Fill a form the user is looking at, with their approval, page by page.

**Constraints (design only; do not build in R1/R2).** Manifest v3, Chrome and Edge. Reads the approved pack via the API using the user's session. Detects fields by label, `aria-label`, `name`, and placeholder heuristics; proposes a mapping; **fills only after the user approves that page's mapping**; **never clicks submit**; never touches a CAPTCHA; never navigates in the background. Operates only on the tab the user is actively viewing, only on an operator-maintained site allowlist. Logs every fill event to `audit_log`. Its own threat model and store review are separate from the API's, which is why it is not R2. HR-1 applies unchanged: the extension is an autofill tool, not an applicant.

**Acceptance criteria.** `AC-APPLY-06.1` (R3) No code path clicks a submit control. `AC-APPLY-06.2` (R3) Fill occurs only after per-page approval. `AC-APPLY-06.3` (R3) The allowlist is enforced. `AC-APPLY-06.4` (R3) Every fill is audited.
**Tests.** `T-APPLY-06.1`–`.4` extension test suite (R3).

## 8. Tailored resume export — `APPLY-08` — **Track: R3**

**Objective.** A PDF resume, ATS-parseable, generated from the profile with the pack's emphasis applied.

**Constraints (design only).** One fixed single-column template: no tables, no text boxes, no columns, no images, standard section headings, embedded standard fonts — the constraints that make a PDF machine-readable. Content comes from **confirmed** profile fields only; `resume_suggestions` of type `reorder` and `emphasize` are applied, `reword` only where the user accepted the reworded text. Every generated PDF is round-tripped through the product's own text extractor (`04-resume-pipeline.md` §3) and the extracted text is asserted to contain every section and every employer — if our own parser cannot read it, an ATS will not either.

**Acceptance criteria.** `AC-APPLY-08.1` (R3) A generated PDF round-trips through the extractor with all sections and employers recovered. `AC-APPLY-08.2` (R3) Only confirmed fields appear. `AC-APPLY-08.3` (R3) No table, text box, or image in the output.
**Tests.** `T-APPLY-08.1`–`.3` `tests/integration/test_resume_export.py` (R3).
