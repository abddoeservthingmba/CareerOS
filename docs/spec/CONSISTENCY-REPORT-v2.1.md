# Consistency report — v2.0 → v2.1

**Run:** 5 September 2026 · **Scope:** all 19 v2.0 specification files · **Method:** scripted extraction of the field and enum registry from `17-data-model.md`, cross-referenced against every `` `collection.field` `` and `∈ {…}` occurrence in the other files, plus a targeted read of the eight highest-risk schema seams (resume lifecycle, job merge fields, pack items, explain payload, usage accounting, reminder occurrence keys, answer-bank keys, retention).

This is a one-off record of the first run. The standing mechanism that replaces it is `DATA-07` (`17-data-model.md` §7) — the generated `fields.yaml` and `enums.yaml` plus a CI check, so the next drift is caught on the PR that introduces it rather than by a review months later.

---

## Data-model findings

| # | Severity | Finding | Resolution in v2.1 |
|---|---|---|---|
| **F1** | **High** | `resumes` carried two lifecycle fields — `status ∈ {uploaded, extracting, structuring, ready, failed}` (§2.4) and a "finer-grained" `stage` whose members `04-resume-pipeline.md` §2 gave as `uploaded → extracting_text → structuring → ready`. Same four steps, two fields, and `extracting` vs `extracting_text` differ. A client switching on `status` would never see `extracting_text`; one switching on `stage` would never see `extracting`. | Collapsed to **one** field. `resumes.status ∈ {uploaded, extracting_text, structuring, ready, failed}` — `04`'s more descriptive naming wins. `stage` is deleted. SSE carries `status` + `progress`. |
| **F2** | **High** | `jobs.revision` was asserted by `AC-JOB-01.4` and `AC-JOB-01.5` and described in `07` §1, but never declared in the `jobs` schema. Two acceptance criteria tested a field that did not exist. | `revision` added to §2.6 as a stored field, listed among the deliberate changes from BRD v1.0 Appendix A with its reason. |
| **F3** | **Medium** | `resumes.text_source ∈ {pdf, docx, ocr}` appeared in `04` §3 outputs and in `AC-RES-02.8`, absent from the schema. | Added to §2.4 with its enum and the note that `ocr` is reachable only in R2. |
| **F4** | **Low** | `resumes.text_excerpt` was described in §2.4 prose ("a 500-character excerpt") but missing from the JSON block, so the schema snapshot would not have covered it. | Added to the block. |
| **F5** | **Medium** | `ai_usage` stored both a `cached` boolean and `outcome: cache_hit` — two representations of one fact, which will eventually disagree. `AC-AI-03.5` asserted the boolean; `AC-AI-04.1` asserted the outcome. | `outcome` is authoritative; the stored boolean is removed and `cached` is derived as `outcome == "cache_hit"` where displayed. `AC-AI-03.5` now asserts the outcome. `deny_reason` added alongside, for the budget matrix. |
| **F6** | **Medium** | `tone` existed at the top level of `application_packs` (§2.9) *and* inside `items.cover_letter` (`09` Appendix C). The nested copy can drift from the parameter that actually generated the text. | Top-level only. `09` §2.1 no longer declares it inside `cover_letter`, and the removal is noted there. |
| **F7** | **Medium** | `explain.skills_basis` was given as `{dictionary, llm, semantic}` in `08` §3, while `jobs.skills_source` is `{listing, dictionary, llm}`. Neither set covered a listing that named its own skills *and* the embedding-fallback case, and the two were easy to mistake for the same enum. | `explain.skills_basis ∈ {listing, dictionary, llm, semantic, none}`, documented in §2.8 as explicitly **not** the same enum as `jobs.skills_source`, with what each extra member means. |
| **F8** | **Medium** | Enum members were defined in module files rather than in the data model: `user_job_actions.reason` (`07` §7), `reminders.type` (`11` §1), `interviews.type`/`outcome` and `salary_log.kind` (`10` §4), `jobs.quality_flags` (`07` §1), `fabrication_flags.status` (`09` §4). Nothing prevented two files disagreeing about a set. | New `DATA-07` (§7): a generated `enums.yaml` owns every member list, the module file keeps the prose explaining what each member means, and CI fails on a member used but unregistered. A 40-row inventory table gives the orientation. |
| **F9** | **Low** | `profile_audit` and `skill_aliases` appeared in the collection ownership table and the index table but had no declared shape — the only two of 23 collections without one. | JSON blocks added as §2.5.1, with their enums. |
| **F10** | **Low** | `description_text` was capped at 8,000 characters; `description_html_sanitized` was uncapped, on a 512 MB database. | Capped at 16,000 after sanitization, recorded in §6's capacity budget. |

## Dependency findings

Produced by the first run of the `DEP-03`/`DEP-04` closure checks (`18-dependency-closure.md` §5). **Track closure passed with no violations** — no R1 requirement transitively depends on R2 or R3 work. All four findings are phase-order, the dimension v2.0 had no way to express.

| # | Severity | Finding | Resolution in v2.1 |
|---|---|---|---|
| **V1** | **High** | `AUTH-01`, `AUTH-03` and `AUTH-05` (phase P1) all send email, but email existed only inside `NOTIF-02a` (phase P6). P1 was unbuildable as written; the likely improvisation is an inline SMTP call in `modules/auth` that `notifications` later duplicates. | Transport extracted to foundations as `FOUND-16` (`01-foundations.md` §16), owned by `infra/email`, phase P0. `NOTIF-02a` keeps templates, channel preferences, the inbox and delivery accounting. |
| **V2** | **High** | `PROF-01` stores `profiles.embedding` in P2; every stored embedding is quantized by the `DATA-06` codec, which had no phase at all. Storing float32 in P2 and quantizing in P4 is a migration over every profile and job for no reason. | The codec (`shared/embedding.py`) is assigned to **P0** and listed in P0's deliverables. The capacity-measurement half of `DATA-06` stays as a nightly job. |
| **V3** | **Medium** | `JOB-07` (saved searches, S2) was written as "ships with the digest", and `NOTIF-04` (digest) is S4 — S2 depending on S4. | The edge was stated backwards. A saved search stores a `notify` flag; the digest is what reads it. `NOTIF-04 → JOB-07`, which is phase-legal, and `JOB-07` stays in S2. |
| **V4** | **Medium** | `APPLY-09` (follow-up draft) sat in P5, but its prompt reads interview rounds and contacts — `TRACK-03`, phase P6. | `APPLY-09` moves to **P6**, where it also belongs on product grounds: the follow-up draft is the action a follow-up reminder prompts. |

## What was checked and found clean

- Every one of the 23 collections has exactly one owning module, and no requirement declares a write outside its module's collections.
- The `applications` XOR (`job_id` vs `manual_job`), the `reminders.dedup_key` occurrence scheme, and the `match_scores` unique index are consistent across `10`, `11`, `17` and the phase plan.
- `audit_log`'s append-only property is stated identically in `09` §6 and `17` §2.12, including the database-privilege half.
- Retention: every collection appears in either the `17` §5 table or the explicit indefinite-retention allowlist. No orphans.
- Band thresholds (`strong ≥80`, `good 65–79`, `partial 50–64`, `weak <50`) agree between `08` §2 and `17` §2.8.
- The aggressive staleness threshold under storage pressure (2 unseen runs instead of 3) is stated consistently in `07` §6 and `17` §6.
- `question_key` is used consistently in `09` and `17`; BRD v1.0's `question_canonical` appears nowhere.
- Hard rules HR-1 … HR-12 each resolve to at least one acceptance criterion in the file they name.
- 756 acceptance criteria, every one resolving to a named test; no orphaned test identifiers.

## Standing mechanisms this run produced

| Mechanism | Requirement | What it prevents recurring |
|---|---|---|
| `fields.yaml` + reference check | `DATA-07` | F2, F3, F4 — asserting against a field that does not exist |
| `enums.yaml` + member check | `DATA-07` | F1, F5, F7, F8 — two files disagreeing about a set |
| `dependencies.yaml` + closure checks | `DEP-01`…`DEP-04` | V1–V4 — a phase or track that cannot be built from what precedes it |
| `BUILD-ORDER.md`, generated | `DEP-04` | Hand-maintained order drifting from the graph |
| `make bundle REQ=<id>` | `DEP-06` | Handing an agent the wrong set of files |
| Implementation-status registry | `FOUND-15` | "Is this built, off, or absent?" being unanswerable |
