# 17 — Data Model

**Module:** `apps/api/app/modules/*/models.py`, `17` is the shared contract between them
**Track:** R1 (fields marked `[R2]` / `[R3]` are added in that track)
**Depends on:** `01-foundations.md` §3 (primitives)
**Requirements:** `DATA-01` … `DATA-06`

This is the one file every module reads. A field defined here is defined nowhere else; a module that needs a new field on another module's collection asks for it here first.

---

## 1. Global conventions — `DATA-01`

**Objective.** Every document in every collection obeys the same rules for identity, time, ownership, and deletion, so a query written for one collection is correct in shape for all of them.

**Constraints.**
- `_id` is a 26-character ULID string (`01-foundations.md` §3). No `ObjectId` anywhere.
- Every document has `created_at` and `updated_at`, UTC-aware, set by a Beanie pre-save hook, never by a caller.
- Every user-owned document has `user_id` as its **first** field in every compound index, except for the system-scan indexes enumerated in `core/documents.py`, each of which serves a scheduled job or an entity narrower than a user and carries a stated reason (ADR-012). A query on a user-owned collection without a `user_id` predicate is a defect; the repository layer is the only place such a query may exist and only under `/admin`.
- Soft delete is `deleted_at: datetime | None`. Every repository read filters `deleted_at: None` by default; reading deleted documents requires an explicit `include_deleted=True` argument.
- Schema changes are additive. A field is added optional with a default, backfilled by a script in `infra/scripts/migrations/NNNN_*.py`, and only then made required. A rename is add + backfill + dual-read + drop, never an in-place rename.
- Every collection's indexes are declared in its Beanie `Settings.indexes`. No index is created by hand in Atlas. A required index that is missing fails `/readyz`.
- Documents are never embedded past one level of nesting where the nested item can grow unbounded. `applications.interviews` is bounded (a handful); `job.description_text` is a scalar; anything unbounded gets its own collection.

**Inputs.** Module model definitions.

**Outputs.** 19 collections (§2), their indexes (§3), retention rules (§5).

**Acceptance criteria.**
- `AC-DATA-01.1` Every Beanie document class inherits the shared `BaseDoc` providing `_id`, `created_at`, `updated_at`, and, where applicable, `UserOwnedDoc` adding `user_id` and `deleted_at`.
- `AC-DATA-01.2` A write with a naive datetime raises; a write with a missing `user_id` on a `UserOwnedDoc` raises.
- `AC-DATA-01.3` `/readyz` returns 503 listing any declared index that is absent from the live database.
- `AC-DATA-01.4` Every repository read method on a user-owned collection either takes `user_id` or is decorated `@admin_scope`, checked by a contract test.
- `AC-DATA-01.5` Every repository read filters `deleted_at: None` unless `include_deleted=True` is passed.

**Tests.**
- `T-DATA-01.1` `tests/unit/test_base_doc.py`.
- `T-DATA-01.2` `tests/unit/test_doc_hooks.py`.
- `T-DATA-01.3` `tests/integration/test_readyz_indexes.py`.
- `T-DATA-01.4` `tests/spec/test_repo_user_scoping.py`.
- `T-DATA-01.5` `tests/integration/test_soft_delete_default.py`.

---

## 2. Collections — `DATA-02`

**Objective.** Nineteen collections, each with a single clear owner module, covering every R1 requirement with no field defined twice.

**Constraints.** Ownership is exclusive: only the owning module's repository writes to a collection. Another module reads it through the owner's public service, never directly.

| Collection | Owner | Purpose | Track |
|---|---|---|---|
| `users` | auth | Identity, role, settings, consent | R1 |
| `refresh_tokens` | auth | Rotating refresh families | R1 |
| `email_tokens` | auth | Verification and reset tokens, hashed | R1 |
| `devices` | notifications | Push tokens per device | R2 |
| `resumes` | resume | Uploaded files and extraction state | R1 |
| `profiles` | profile | The candidate profile, one per user | R1 |
| `profile_audit` | profile | Field-level change history | R2 |
| `skill_aliases` | profile | Alias → canonical skill | R1 |
| `jobs` | jobs | Canonical, deduplicated listings | R1 |
| `raw_listings` | jobs | Untouched connector payloads, TTL 30 d | R1 |
| `connector_runs` | jobs | Per-run ingestion statistics | R1 |
| `user_job_actions` | jobs | Hide / not-interested / report | R1 |
| `saved_searches` | jobs | Named filter sets with notification opt-in | R2 |
| `match_scores` | matching | Score + explain per (user, job) | R1 |
| `answer_bank` | apply | Reusable Q&A | R1 |
| `application_packs` | apply | Generated artifacts and approval state | R1 |
| `applications` | tracker | The tracked application | R1 |
| `reminders` | notifications | Scheduled reminder occurrences | R1 |
| `notifications` | notifications | In-app inbox | R1 |
| `audit_log` | apply (append-only, shared) | Immutable record of consequential actions | R1 |
| `ai_usage` | ai | Per-call token and cost accounting | R1 |
| `feature_flags` | admin | DB overrides for flags | R1 |
| `failed_tasks` | core | Dead-lettered ARQ jobs | R1 |

(Twenty-three including the R2 ones and the two infrastructure collections; nineteen are R1.)

### 2.1 `users`

```json
{
  "_id": "01J...",
  "email": "a@b.com",
  "email_normalized": "a@b.com",
  "email_verified": true,
  "password_hash": "$argon2id$...",
  "oauth": [{ "provider": "google", "sub": "1078...", "linked_at": "..." }],
  "role": "user",
  "tz": "Asia/Kolkata",
  "consent": [{ "version": "2026-09-01", "accepted_at": "...", "ip": "…", "items": ["ai_processing", "third_party_sources"] }],
  "settings": {
    "match_threshold": 60,
    "notif": { "email": true, "in_app": true, "push": false, "digest": "off", "quiet_hours": null }
  },
  "status": "active",
  "deletion_requested_at": null,
  "deleted_at": null
}
```
- `email_normalized` is lowercased and, for Gmail-family domains, dot-stripped — it is the uniqueness key. `email` preserves what the user typed.
- `consent` is an **array**: a new consent version appends, never overwrites. `16-security-and-compliance.md` §4.
- `role ∈ {user, operator}`. There is no third role in R1.
- `status ∈ {active, suspended, pending_deletion}`.
- `settings.notif.digest ∈ {off, weekly}` — `weekly` unreachable until R2.

### 2.2 `refresh_tokens`

```json
{ "_id": "01J...", "user_id": "01J...", "family_id": "01J...", "token_hash": "sha256+pepper",
  "expires_at": "...", "revoked_at": null, "revoked_reason": null,
  "replaced_by": null, "device": { "ua": "…", "ip_prefix": "203.0.113.0/24" } }
```
- Only `ip_prefix` (network, not host) is stored. `01-foundations.md` §14 forbids storing full IPs against a person beyond the consent record.
- `revoked_reason ∈ {rotated, logout, reuse_detected, password_changed, admin, deletion}`.

### 2.3 `email_tokens`

```json
{ "_id": "01J...", "user_id": "01J...", "kind": "verify_email",
  "token_hash": "sha256('verify:'+token)", "expires_at": "...", "used_at": null, "attempts": 0 }
```
- `kind ∈ {verify_email, reset_password}`. Domain-separated hash prefix per kind so a token for one purpose cannot be replayed for the other.

### 2.4 `resumes`

```json
{ "_id": "01J...", "user_id": "01J...", "label": "Backend",  
  "r2_key": "u/{user_id}/resumes/{resume_id}.pdf", "mime": "application/pdf", "size_bytes": 184320,
  "sha256": "…",
  "status": "ready", "progress": 100,
  "text_chars": 4812, "text_source": "pdf",
  "text_r2_key": "u/{user_id}/resumes/{resume_id}.txt", "text_excerpt": "first 500 chars, admin debugging only",
  "extraction": { /* ProfileExtraction, see 04-resume-pipeline.md §4 */ },
  "extraction_model": "…", "prompt_version": "resume_extract/v3",
  "quality_feedback": [],
  "is_default": true,
  "error": null
}
```
- `status ∈ {uploaded, extracting_text, structuring, ready, failed}` — **one** enum, not two. v2.0 carried both a coarse `status` and a finer `stage` whose members were the same four steps under different names (`extracting` vs `extracting_text`), which is how a client ends up switching on a value the server never sends. The SSE event carries `status` plus `progress`; there is no `stage` field (consistency finding F1).
- `text_source ∈ {pdf, docx, ocr}` — `ocr` reachable only in R2 (`RES-02b`). The extraction prompt is told which, because OCR input needs different handling of garbled tokens.
- Extracted **text lives in R2**, not Mongo — a 5 MB resume's text can approach Mongo's 16 MB document ceiling once paired with the extraction, and Atlas M0 is 512 MB total. Mongo keeps `text_chars` and a 500-character `text_excerpt` for admin debugging only.
- `quality_feedback` empty until R2 (RES-04).
- `label` and `is_default` exist in R1 with exactly one resume per user; multi-version semantics are R3 (PROF-04).

### 2.5 `profiles`

One per user. The full shape is in `03-profile.md` §2; the persistence contract is:

```json
{ "_id": "01J...", "user_id": "01J...", "version": 12,
  "identity": {...}, "contact": {...},
  "skills": [ { "raw": "ReactJS", "canonical": "react", "years": 3, "level": "advanced",
                "source": "ai", "confidence": 0.92, "confirmed": true, "evidence": "built React dashboards" } ],
  "experience": [...], "education": [...], "certifications": [...], "projects": [...], "languages": [...],
  "total_experience_months": 40, "seniority": "mid",
  "preferences": {...},
  "completeness": null,
  "embedding": { "model": "…", "dims": 768, "vector": [], "source_hash": "sha256…", "computed_at": "…" },
  "staged_extraction": { "resume_id": "…", "extraction": {...}, "staged_at": "…" }
}
```
- `version` increments on every accepted change and is stamped onto every `match_scores` row, so a score can be attributed to the profile that produced it.
- Every extracted item carries `source ∈ {ai, user}`, `confidence: 0..1`, `confirmed: bool` (PROF-03, HR-7).
- `embedding.dims` and `embedding.model` are stored **with** the vector. A vector is never compared against one from a different model (`05-ai-layer.md` §2).
- `staged_extraction` holds a pending review; applying it clears the field and bumps `version`.
- `completeness` null until R2.

### 2.5.1 `profile_audit` [R2] and `skill_aliases`

```json
// profile_audit [R2] — one row per changed leaf, batched per mutation
{ "_id": "01J...", "user_id": "…", "field_path": "skills.3.years", "old": "2", "new": "3",
  "actor": "user", "at": "…", "request_id": "…" }

// skill_aliases — the alias IS the _id, normalized
{ "_id": "reactjs", "canonical": "react", "category": "frontend", "source": "seed" }
```
- `profile_audit.actor ∈ {user, ai, system}`. Contact-field rows store a masked value, never a second copy of the PII (`03-profile.md` §6).
- `skill_aliases.source ∈ {seed, admin}`. No chains: a `canonical` value may not itself be an alias (`AC-PROF-06.6`).
- Both collections had prose in v2.0 and no declared shape (consistency finding F9).

### 2.6 `jobs` — the canonical listing

Carried forward from BRD v1.0 Appendix A, with track markers and three changes noted below.

```json
{
  "_id": "01J...",
  "dedup_key": "sha1(norm_company|norm_title|norm_locus)",
  "simhash": "u64 as string",
  "source_refs": [{ "source": "adzuna", "external_id": "123", "url": "https://…", "apply_url": "https://…",
                    "first_seen_at": "…", "last_seen_at": "…", "attribution": "Jobs by Adzuna" }],
  "primary_source": "adzuna",
  "title": "Senior Backend Engineer",
  "title_family": "backend_engineer",
  "seniority": "senior",
  "company": { "name": "Acme", "normalized": "acme", "url": null, "logo_url": null, "size": null, "industry": null },
  "location": { "raw": "Bengaluru, India (Hybrid)", "city": "Bengaluru", "region": "KA", "country": "IN",
                "remote_mode": "hybrid", "remote_regions": ["IN"] },
  "employment_type": "full_time",
  "salary": { "min": 2500000, "max": 3500000, "currency": "INR", "period": "year", "source": "listing" },
  "description_text": "…",
  "description_html_sanitized": "…",
  "required_skills": ["python", "fastapi", "postgresql"],
  "nice_to_have_skills": ["kubernetes"],
  "skills_source": "dictionary",
  "experience_years": { "min": 4, "max": 8, "source": "regex" },
  "education_required": null,
  "visa_sponsorship": null,
  "apply_deadline": null,
  "posted_at": "…", "first_seen_at": "…", "last_seen_at": "…", "unseen_runs": 0, "expired_at": null,
  "revision": 1,
  "status": "active",
  "enrichment": { "model": "…", "prompt_version": "job_enrich/v2", "enriched_at": "…" },
  "embedding": { "model": "…", "dims": 768, "vector": [], "source_hash": "…", "computed_at": "…" },
  "quality_flags": ["no_salary"],
  "flagged": { "count": 0, "reasons": [], "reviewed_at": null }
}
```

Changes from v1.0 Appendix A, each with a reason:
1. **`apply_url` moved into `source_refs[]`.** After a cross-source merge there is more than one apply URL, and the user must be able to apply via the source they trust. A top-level single `apply_url` loses that. `primary_source` names the default.
2. **`simhash` and `unseen_runs` are stored fields.** Dedup (§JOB-03) and staleness (JOB-08) both need them at query time; recomputing a simhash to compare is pointless.
3. **`revision` is a stored field.** `07-ingestion-and-jobs.md` §1 increments it when a description changes materially (simhash distance >6) and re-runs enrichment and embedding; v2.0 asserted that behaviour in `AC-JOB-01.4`/`.5` against a field this schema never declared (consistency finding F2).
4. **`skills_source` and `experience_years.source` added.** `dictionary | llm | listing` tells the matcher — and the user — whether a "required skill" came from the employer's own structured field or from our inference, which changes how confidently the explain payload should phrase it.

Enumerations are as in v1.0 Appendix A; `title_family` values live in `jobs/title_families.yaml` with regex and keyword rules and are extendable without a code change.

### 2.7 `raw_listings`, `connector_runs`, `user_job_actions`, `saved_searches`

```json
// raw_listings — TTL 30 d on fetched_at
{ "_id": "01J...", "connector": "adzuna", "external_id": "123", "run_id": "01J…",
  "payload": { }, "fetched_at": "…" }

// connector_runs
{ "_id": "01J...", "connector": "adzuna", "started_at": "…", "finished_at": "…",
  "queries": 12, "fetched": 480, "new": 61, "updated": 402, "deduped_into_existing": 17,
  "normalize_failures": 0, "errors": [{ "stage": "fetch", "code": "http_429", "at": "…" }],
  "status": "success", "circuit_state": "closed" }

// user_job_actions
{ "_id": "01J...", "user_id": "…", "job_id": "…", "action": "not_interested",
  "reason": "salary_too_low", "at": "…" }

// saved_searches [R2]
{ "_id": "01J...", "user_id": "…", "name": "Remote Python", "filters": { }, "notify": true, "last_run_at": "…" }
```
- `user_job_actions.action ∈ {hidden, not_interested, reported}`; `reason` from a fixed enum plus optional free text, because a free-text-only reason is useless as a matching signal (MATCH-06, R2).

### 2.8 `match_scores`

```json
{ "_id": "01J...", "user_id": "…", "job_id": "…",
  "score": 82, "band": "strong",
  "weights_version": "w1", "profile_version": 12, "scorer_build": "sha-abc1234",
  "components": { "skills": 34, "experience": 14, "title": 12, "location": 10,
                  "salary": 6, "seniority": 4, "freshness": 2, "penalties": 0 },
  "explain": {
    "matched_required": ["react","typescript"], "missing_required": ["kubernetes"],
    "matched_nice": ["docker"], "missing_nice": ["terraform"],
    "skills_basis": "dictionary",
    "experience": { "required_min_years": 3, "candidate_years": 3.3, "verdict": "meets" },
    "location": { "verdict": "remote_ok", "detail": "Remote (India) allowed" },
    "salary": { "verdict": "unknown", "detail": "Listing gives no salary" },
    "seniority": { "verdict": "match" },
    "red_flags": []
  },
  "embedding_sim": 0.71,
  "rationale": null, "rationale_model": null, "rationale_prompt_version": null, "rationale_at": null,
  "user_feedback": null,
  "computed_at": "…"
}
```
- `explain.skills_basis ∈ {listing, dictionary, llm, semantic, none}`, and it is **not** the same enum as `jobs.skills_source ∈ {listing, dictionary, llm}`: the job field records where the requirement list came from, while the explain field additionally admits `semantic` (the embedding fallback used when the listing named no skills) and `none` (no skills and no embedding). v2.0 gave `skills_basis` three members that lined up with neither case (consistency finding F7).
- **`rationale` is a sibling of `explain`, not a field inside it.** HR-3: the scorer reads `explain` and `components`; it must be structurally incapable of reading `rationale`. A test asserts the scoring function's input type has no rationale field (`AC-MATCH-03.4`).
- `scorer_build` is the git SHA of the scoring module, so a score computed by a build with a bug is identifiable and re-computable.
- `band` is derived and stored so the feed can index on it: `strong ≥80`, `good 65–79`, `partial 50–64`, `weak <50`.
- `user_feedback` null until R2 (MATCH-06).

### 2.9 `answer_bank`, `application_packs`

```json
// answer_bank
{ "_id": "01J...", "user_id": "…",
  "question_key": "notice_period",  
  "question_text": "What is your notice period?",
  "variants": ["notice period", "when can you start"],
  "answer": "60 days, negotiable to 45",
  "tags": ["logistics"], "source": "user", "confirmed": true,
  "embedding": { "model": "…", "dims": 768, "vector": [], "source_hash": "…" } }

// application_packs
{ "_id": "01J...", "user_id": "…", "application_id": "…", "job_id": "…",
  "status": "approved", "supersedes": "01J…",
  "tone": "concise",
  "items": {
    "summary": { "text": "…", "claims": [{ "span": "…", "source_path": "profile.experience.0.bullets.2" }], "edited_by_user": false },
    "cover_letter": { "text": "…", "claims": [...], "edited_by_user": true },
    "answers": [{ "question": "…", "question_key": "notice_period", "answer": "…",
                  "source": "answer_bank:01J…", "confidence": 0.9, "needs_user": false, "edited_by_user": false }],
    "resume_suggestions": [{ "type": "emphasize", "target": "profile.experience.1.bullets.0",
                             "suggestion": "…", "reason": "…" }],
    "unanswerable_questions": ["Do you have a security clearance?"]
  },
  "fabrication_flags": [{ "item": "cover_letter", "span": "led a team of 12", "entity_type": "number",
                          "status": "overridden", "overridden_at": "…" }],
  "model": "…", "prompt_version": "pack/v4",
  "generated_at": "…", "approved_at": "…", "content_hash": "sha256 of items at approval" }
```
- `tone` lives **only** at the top level of the pack, because it is the parameter the pack was generated with. v2.0 also carried it inside `items.cover_letter`, where it could drift from the value that actually produced the text (consistency finding F6). `09-apply.md` §2.1 no longer declares it there.
- `question_key` is from the canonical taxonomy in `apply/questions.yaml`; free questions get `question_key: null` and match by embedding.
- `status ∈ {draft, approved, superseded}`. Editing an approved pack creates a new document and sets the old one to `superseded` — approvals are immutable (APPLY-07).
- `edited_by_user` per item is what lets the UI honestly label which text is AI-generated and which the user wrote (HR-9).
- `fabrication_flags[].status ∈ {open, resolved, overridden}`. A pack with an `open` flag cannot be approved (`AC-APPLY-04.4`).

### 2.10 `applications`

```json
{ "_id": "01J...", "user_id": "…",
  "job_id": "01J…", "manual_job": null,
  "status": "applied",
  "status_history": [{ "from": "preparing", "to": "applied", "at": "…", "by": "user", "reason": null }],
  "applied_at": "…", "applied_via": "external_link",
  "current_pack_id": "01J…",
  "notes_md": "",
  "contacts": [{ "name": "…", "role": "…", "email": "…", "notes": "" }],
  "documents": [{ "r2_key": "u/{uid}/applications/{aid}/{doc_id}.pdf", "name": "…", "kind": "resume", "size_bytes": 1, "uploaded_at": "…" }],
  "interviews": [{ "id": "01J…", "round": 1, "type": "technical", "at": "…", "duration_min": 60,
                   "location": "…", "notes": "", "outcome": null }],
  "salary_log": [{ "at": "…", "kind": "expectation_given", "money": {...}, "note": "" }],
  "next_action_at": "…", "last_activity_at": "…",
  "listing_expired": false,
  "source": "match"
}
```
- Exactly one of `job_id` and `manual_job` is set (TRACK-05). A partial index enforces uniqueness of `(user_id, job_id)` only where `job_id` exists.
- `listing_expired` is a **flag, not a status** (TRACK-01) — an expired listing does not change where the application sits on the board.
- `source ∈ {match, search, manual}` — tells you later whether matching was actually the thing driving applications.

### 2.11 `reminders`, `notifications`, `devices`

```json
// reminders
{ "_id": "01J...", "user_id": "…", "application_id": "…",
  "type": "follow_up", "due_at": "…", "channels": ["email","in_app"],
  "status": "scheduled", "dedup_key": "follow_up:{application_id}:{applied_at_epoch}",
  "sent_at": null, "attempts": 0, "cancelled_reason": null,
  "payload": { "job_title": "…", "company": "…" } }

// notifications (in-app inbox)
{ "_id": "01J...", "user_id": "…", "title": "…", "body": "…",
  "deep_link": "app://applications/01J…", "kind": "reminder", "read_at": null }

// devices [R2]
{ "_id": "01J...", "user_id": "…", "platform": "android", "fcm_token": "…",
  "app_version": "…", "last_seen_at": "…", "invalidated_at": null }
```
- `dedup_key` is unique — it is the whole idempotency mechanism (NOTIF-05). It embeds the occurrence, so rescheduling after a status change produces a genuinely different key rather than silently colliding.
- `payload` denormalizes the few strings the message needs, so dispatch does not join to `jobs` for 200 reminders in a batch, and so a message about a since-deleted job still renders.

### 2.12 `audit_log`, `ai_usage`, `feature_flags`, `failed_tasks`

```json
// audit_log — append-only, no updates, no deletes
{ "_id": "01J...", "user_id": "…", "kind": "pack_approved", "ref_id": "01J…",
  "content_hash": "sha256…", "at": "…", "ip_prefix": "…", "request_id": "…", "detail": {} }

// ai_usage
{ "_id": "01J...", "at": "…", "provider": "gemini", "model": "…", "feature": "resume_extract",
  "user_id": "…", "input_tokens": 4120, "output_tokens": 812, "est_cost_usd": 0.00193,
  "latency_ms": 3412, "outcome": "ok", "prompt_version": "resume_extract/v3",
  "deny_reason": null }

// feature_flags
{ "_id": "llm_rationale_enabled", "value": false, "updated_at": "…", "updated_by": "…" }

// failed_tasks
{ "_id": "01J...", "task": "resume.process", "args": ["01J…"], "attempts": 3,
  "error_type": "…", "traceback": "…", "first_failed_at": "…", "last_failed_at": "…", "resolved_at": null }
```
- `audit_log.kind ∈ {pack_generated, pack_approved, pack_superseded, fabrication_overridden, applied_confirmed, consent_accepted, data_export, deletion_requested, deletion_completed, admin_action}`.
- `ai_usage.outcome ∈ {ok, invalid_json, repaired, provider_error, budget_denied, cache_hit}` — needed for `12-admin.md` §2 and to know whether repair retries are eating the budget. **There is no stored `cached` boolean**: v2.0 had both, and two fields that can disagree about one fact eventually will. `cached` is derived as `outcome == "cache_hit"` wherever it is displayed (consistency finding F5).
- `ai_usage.deny_reason ∈ {user, feature, global, null}` — which cap denied the call, in the fixed precedence of `05-ai-layer.md` §3.1. Null unless `outcome == "budget_denied"`.

**Acceptance criteria for §2.**
- `AC-DATA-02.1` Every collection above exists with the exact field names given; a schema-snapshot test fails on drift.
- `AC-DATA-02.2` Only the owning module's repository writes to each collection, verified by a static check on Beanie document imports.
- `AC-DATA-02.3` `applications` enforces "exactly one of `job_id`, `manual_job`" at write time and by a JSON-schema validator on the collection.
- `AC-DATA-02.4` `audit_log` rejects updates and deletes: the repository exposes only `append` and `find`, and the Atlas role used by the app has no `update`/`remove` privilege on that collection.
- `AC-DATA-02.5` `match_scores.rationale` is not reachable from the scoring function's input type (HR-3).
- `AC-DATA-02.6` `profiles.embedding` and every other embedding carry `model` and `dims`; a comparison between vectors of differing `model` raises `EmbeddingModelMismatch`.

**Tests.**
- `T-DATA-02.1` `tests/spec/test_schema_snapshot.py` (golden JSON of every model's schema).
- `T-DATA-02.2` `tests/spec/test_collection_ownership.py`.
- `T-DATA-02.3` `tests/integration/test_application_job_xor.py`.
- `T-DATA-02.4` `tests/integration/test_audit_append_only.py`.
- `T-DATA-02.5` `tests/unit/test_scorer_input_type.py`.
- `T-DATA-02.6` `tests/unit/test_embedding_guard.py`.

---

## 3. Indexes — `DATA-03`

**Objective.** Every query in the product served by an index, declared in code, verified at boot.

**Constraints.** Declared in each document's `Settings.indexes`. Partial indexes carry their filter. Every compound index on a user-owned collection starts with `user_id`, except for the system-scan indexes enumerated in `core/documents.py` (ADR-012) — `reminders (status, due_at)` serves the dispatch scan and `profiles (preferences.locations.country, preferences.remote_mode)` serves candidate-set selection, both deliberately cross-user, and `application_packs (application_id, status)` keys on an entity that belongs to exactly one user. A text index is outside the rule entirely: Mongo replaces the declared fields with its own `(_fts, _ftsx)` pair, so the key order the rule speaks of does not survive into the index.

| Collection | Index | Kind | Serves |
|---|---|---|---|
| `users` | `email_normalized` | unique | login, registration collision |
| `users` | `oauth.provider, oauth.sub` | unique, sparse | Google sign-in |
| `users` | `status, deletion_requested_at` | plain | `account.purge_deleted` cron |
| `refresh_tokens` | `token_hash` | unique | refresh |
| `refresh_tokens` | `family_id` | plain | family revoke |
| `refresh_tokens` | `expires_at` | TTL | cleanup |
| `email_tokens` | `token_hash` | unique | verify / reset |
| `email_tokens` | `expires_at` | TTL | cleanup |
| `resumes` | `user_id, created_at desc` | plain | list |
| `resumes` | `user_id, is_default` | partial `is_default: true` | default lookup |
| `profiles` | `user_id` | unique | everything |
| `profiles` | `preferences.title_families` | multikey | candidate-set selection |
| `profiles` | `preferences.locations.country, preferences.remote_mode` | compound multikey | candidate-set selection |
| `skill_aliases` | `_id` (the alias itself) | primary | canonicalization |
| `jobs` | `dedup_key` | unique | exact dedup |
| `jobs` | `source_refs.source, source_refs.external_id` | unique multikey | per-source upsert |
| `jobs` | `status, posted_at desc` | compound | feed and search default sort |
| `jobs` | `title_family, location.country, remote_mode, status` | compound | candidate-set selection |
| `jobs` | `title, company.name, description_text` | text, weights 10/5/1 | JOB-06 search |
| `jobs` | `simhash` | plain | fuzzy dedup shortlist |
| `jobs` | `primary_source, last_seen_at` | compound | staleness sweep |
| `raw_listings` | `fetched_at` | TTL 30 d | retention |
| `raw_listings` | `connector, external_id` | plain | debugging |
| `connector_runs` | `connector, started_at desc` | compound | admin dashboard |
| `user_job_actions` | `user_id, job_id, action` | unique | idempotent hide |
| `match_scores` | `user_id, job_id` | unique | upsert |
| `match_scores` | `user_id, score desc, job_id` | compound | the feed |
| `match_scores` | `user_id, band, computed_at desc` | compound | digest, top-N selection |
| `answer_bank` | `user_id, question_key` | unique sparse | lookup |
| `answer_bank` | `question_text, variants` | text | fuzzy match |
| `application_packs` | `application_id, status` | compound | current pack |
| `applications` | `user_id, status, last_activity_at desc` | compound | Kanban and list |
| `applications` | `user_id, job_id` | unique partial `job_id: {$exists: true}` | one application per job |
| `applications` | `user_id, next_action_at` | compound | dashboards |
| `reminders` | `dedup_key` | unique | NOTIF-05 |
| `reminders` | `status, due_at` | compound | dispatch scan |
| `notifications` | `user_id, created_at desc` | compound | inbox |
| `notifications` | `user_id, read_at` | partial `read_at: null` | unread badge |
| `audit_log` | `user_id, at desc` | compound | timeline, export |
| `audit_log` | `kind, at desc` | compound | compliance queries |
| `ai_usage` | `at` | plain | daily aggregation |
| `ai_usage` | `feature, at` | compound | per-feature cost |
| `ai_usage` | `at` | TTL 400 d | 13-month retention |
| `failed_tasks` | `task, last_failed_at desc` | compound | triage |

**Acceptance criteria.**
- `AC-DATA-03.1` Every index above is declared in code and present at `/readyz`.
- `AC-DATA-03.2` The feed query, the search query, the candidate-set query, the dispatch scan, and the Kanban query each show `IXSCAN` (not `COLLSCAN`) in `explain()` against a seeded 100k-job, 50-user database.
- `AC-DATA-03.3` No index exists in the live database that is not declared in code (drift in the other direction is also a failure).
- `AC-DATA-03.4` Total index size on the R1 index set stays under 120 MB at 50k jobs, leaving headroom in Atlas M0's 512 MB (measured, recorded in `docs/runbooks/atlas-capacity.md`).

**Tests.**
- `T-DATA-03.1` / `T-DATA-03.3` `tests/integration/test_index_declarations.py`.
- `T-DATA-03.2` `tests/integration/test_index_usage.py` with a seeded fixture database.
- `T-DATA-03.4` `tests/integration/test_index_size_budget.py` (nightly, not per-PR).

---

## 4. Storage layout (R2 object store) — `DATA-04`

**Objective.** Every stored file addressable from a user prefix so that deletion is a prefix sweep, and no object key contains anything a person supplied.

**Constraints.**
- Bucket layout, one bucket per environment:
```
u/{user_id}/resumes/{resume_id}.{ext}
u/{user_id}/resumes/{resume_id}.txt          # extracted text
u/{user_id}/applications/{application_id}/{document_id}.{ext}
u/{user_id}/exports/{export_id}.zip          # [R2]
backups/{YYYY-MM-DD}/dump.archive.gz         # ops only, not under u/
```
- Keys contain **only ULIDs and fixed literals**. The user's filename is stored in Mongo as `documents[].name` and used only in the `Content-Disposition` of a presigned download, sanitized.
- No public bucket access. Every read is a presigned GET with a 5-minute TTL, issued only after an ownership check.
- Uploads are streamed to R2; the API never buffers a whole file in memory. Content type is determined by magic bytes, not by the client's claim.
- Versioning on. Lifecycle rule expires noncurrent versions after 30 days.
- Deletion (AUTH-07) deletes the `u/{user_id}/` prefix including all noncurrent versions, and the completion is verified by re-listing the prefix.

**Acceptance criteria.**
- `AC-DATA-04.1` No object key in any environment matches a pattern containing a character outside `[A-Za-z0-9/_.-]` or contains a user-supplied substring.
- `AC-DATA-04.2` A presigned URL expires in 5 minutes and a URL for another user's object is never issued (ownership checked before signing; 404 otherwise).
- `AC-DATA-04.3` Uploading a 5 MB file peaks under 32 MB of API process RSS growth.
- `AC-DATA-04.4` A file whose extension says `.pdf` but whose magic bytes say otherwise is rejected with `unsupported_file_type`.
- `AC-DATA-04.5` After a hard delete, listing `u/{user_id}/` with versions returns zero objects.

**Tests.**
- `T-DATA-04.1` `tests/unit/test_object_keys.py` + `tests/integration/test_key_audit.py` (lists MinIO in the integration environment).
- `T-DATA-04.2` `tests/integration/test_presigned_urls.py`.
- `T-DATA-04.3` `tests/integration/test_upload_memory.py`.
- `T-DATA-04.4` `tests/unit/test_magic_bytes.py`.
- `T-DATA-04.5` `tests/integration/test_deletion_sweep.py`.

---

## 5. Retention — `DATA-05`

**Objective.** Every class of data has one stated lifetime, enforced by a mechanism, not by intention.

| Data | Lifetime | Mechanism |
|---|---|---|
| `raw_listings` | 30 days | TTL index on `fetched_at` |
| `jobs`, expired | 90 days after `expired_at`, then deleted — **unless** referenced by an `applications` document, in which case retained indefinitely with `description_text` and `description_html_sanitized` cleared | Nightly `jobs.purge_expired` cron; the reference check is a lookup, not a guess |
| `jobs`, active | While the source keeps showing it, plus 30 days (§7.1 of BRD v1.0: cached content) | `unseen_runs` → `expired_at` → the rule above |
| `refresh_tokens` | Until `expires_at` | TTL index |
| `email_tokens` | Until `expires_at` | TTL index |
| `ai_usage` | 13 months | TTL index (400 d) |
| `connector_runs` | 180 days | Nightly cron |
| `notifications` | 180 days after `created_at`, read or unread | Nightly cron |
| `reminders`, sent or cancelled | 180 days | Nightly cron |
| `failed_tasks`, resolved | 90 days | Nightly cron |
| `audit_log` | 7 years, or until account hard-delete, whichever is first | No automatic deletion; account purge removes the user's rows |
| Everything user-owned, after a deletion request | 7-day grace, then hard delete including R2 | `account.purge_deleted` cron + `DATA-04` prefix sweep |
| Backups | 14 days | R2 lifecycle rule on `backups/` |

**Constraints.**
- A retention rule with no mechanism is a defect. Every row above names one.
- The 7-day deletion grace is the **only** period during which a soft-deleted user's data exists; nothing else keeps a copy, including backups older than the request — which is why backup retention (14 d) is disclosed in the consent text (`16-security-and-compliance.md` §4).
- Deleting a user's data must not orphan another user's data. `jobs` are shared and are never deleted by a user action.

**Acceptance criteria.**
- `AC-DATA-05.1` Each TTL index above exists with the stated `expireAfterSeconds`.
- `AC-DATA-05.2` `jobs.purge_expired` deletes an expired unreferenced job, and for an expired *referenced* job clears the description fields while keeping the document and its `title`, `company`, and `source_refs`.
- `AC-DATA-05.3` `account.purge_deleted` run with a frozen clock 7 days after a request removes every document carrying that `user_id` across all collections and every object under the prefix, and the run writes a `deletion_completed` audit row.
- `AC-DATA-05.4` A test enumerates every collection in §2 and fails if a collection is missing from both this retention table and an explicit "retained indefinitely" allowlist.
- `AC-DATA-05.5` Purging a user does not remove or modify any `jobs` document.

**Tests.**
- `T-DATA-05.1` `tests/integration/test_ttl_indexes.py`.
- `T-DATA-05.2` `tests/integration/test_job_purge.py`.
- `T-DATA-05.3` `tests/integration/test_account_purge.py`.
- `T-DATA-05.4` `tests/spec/test_retention_coverage.py`.
- `T-DATA-05.5` `tests/integration/test_purge_isolation.py`.

---

## 6. Capacity budget — `DATA-06`

**Objective.** Know before launch whether Atlas M0's 512 MB survives R1, and know the trigger for upgrading.

**Constraints.** Measured, not estimated, from the seeded staging database.

| Collection | Est. doc size | R1 target count | Est. total |
|---|---|---|---|
| `jobs` (with 768-dim float32 embedding ≈ 3 KB, description ≈ 4 KB) | ~8 KB | 50,000 | ~400 MB |
| `match_scores` | ~1.5 KB | 50 users × 2,000 = 100,000 | ~150 MB |
| everything else | — | — | ~20 MB |

That does not fit. Three mitigations, all R1, in order of preference:

1. **Embeddings are stored quantized.** `int8` with a stored scale factor: 768 bytes instead of 3 KB, cosine similarity error under 1% — irrelevant at the precision the score uses. Saves ~110 MB on jobs.
2. **`description_text` is truncated to 8,000 characters** at ingestion, and `description_html_sanitized` to 16,000 after sanitization (consistency finding F10), with the full text kept only in `raw_listings` for its 30-day window. No scoring input reads past 8,000 characters, and the UI links to the original.
3. **The R1 active-job ceiling is 25,000**, enforced by the staleness sweep running more aggressively (expire after 2 unseen runs instead of 3) when the count exceeds it.

With all three: jobs ≈ 25,000 × 5 KB ≈ 125 MB, scores ≈ 150 MB, indexes ≈ 120 MB, other ≈ 20 MB — about 415 MB, which fits with margin but not much. The M10 upgrade trigger is **75% of 512 MB sustained for 3 days**, alerted (`15-infra-and-ops.md` §4), and it is a tier change with no code change (ADR-004).

**Inputs.** Staging database statistics.

**Outputs.** `docs/runbooks/atlas-capacity.md` with measured figures; the alert; the quantization codec in `shared/embedding.py`.

**Acceptance criteria.**
- `AC-DATA-06.1` `shared/embedding.py` quantizes to int8 with a stored scale, and round-trip cosine similarity differs from the float32 value by <0.01 across 1,000 random vector pairs.
- `AC-DATA-06.2` No stored `description_text` exceeds 8,000 characters, and no scoring or prompt input reads a longer string.
- `AC-DATA-06.3` The staleness sweep switches to the aggressive threshold when active jobs exceed 25,000, and back below it.
- `AC-DATA-06.4` A nightly job records `dbStats` and index sizes into `docs/runbooks/atlas-capacity.md` (or an artifact) and alerts at 75% for 3 consecutive days.
- `AC-DATA-06.5` Total storage in staging with 25,000 jobs and 50 users measures under 450 MB.

**Tests.**
- `T-DATA-06.1` `tests/unit/test_embedding_quantization.py` (hypothesis).
- `T-DATA-06.2` `tests/integration/test_description_truncation.py`.
- `T-DATA-06.3` `tests/integration/test_staleness_pressure.py`.
- `T-DATA-06.4` `tests/integration/test_capacity_report.py`.
- `T-DATA-06.5` `tests/integration/test_storage_budget.py` (nightly).

---

## 7. The field and enum registry — `DATA-07` — **added in v2.1**

**Objective.** Make this file the single place a field or an enum member is defined, and make a reference to one from any other file checkable by machine rather than by memory.

**Constraints.**
- **Two generated artifacts, both committed:**
  - `docs/spec/fields.yaml` — every collection with its full field path list, generated by parsing the JSON blocks in §2. A field referenced anywhere in the specification as `collection.field` must appear here.
  - `docs/spec/enums.yaml` — every enum in the product, with its members, its owning collection or DTO, and the file that defines it. Generated from the `∈ {…}` declarations in §2 plus the explicitly registered API enums.
- **An enum is defined once, here, and referenced elsewhere.** v2.0 scattered enum members across module files — `user_job_actions.reason` in `07`, `reminders.type` in `11`, `interviews.type` and `outcome` in `10`, `quality_flags` in `07` — which is how two files come to disagree about a set (consistency finding F8). Those members now live in `enums.yaml`, with the module file describing what each member *means* and this file owning the list.
- The registry check is part of the traceability gate (`01-foundations.md` §6) and runs on every push: a `collection.field` reference that does not resolve, or an enum member used in a file but absent from `enums.yaml`, fails CI.
- The check is deliberately narrow to stay useful: it validates references written in the `` `collection.field` `` backticked form and enum members written in the `` `value` `` form inside a sentence naming the enum. Prose that describes a field in words is not parsed, and does not need to be.
- Field additions follow the additive rule (§1): a new field is added here first, in the same PR that uses it, or the check fails.

**Inputs.** §2 of this file; the registered API enum list.

**Outputs.** `fields.yaml`; `enums.yaml`; the CI check; the `fields` and `enums` blocks in `SPEC-METADATA.json`.

**The R1 enum inventory**, for orientation — `enums.yaml` is the authority:

| Enum | Members | Defined by |
|---|---|---|
| `users.role` | user, operator | §2.1 |
| `users.status` | active, suspended, pending_deletion | §2.1 |
| `refresh_tokens.revoked_reason` | rotated, logout, reuse_detected, password_changed, admin, deletion | §2.2 |
| `email_tokens.kind` | verify_email, reset_password | §2.3 |
| `resumes.status` | uploaded, extracting_text, structuring, ready, failed | §2.4 |
| `resumes.text_source` | pdf, docx, ocr | §2.4 |
| `profile.field.source` | ai, user | §2.5 |
| `profile_audit.actor` | user, ai, system | §2.5.1 |
| `skill_aliases.source` | seed, admin | §2.5.1 |
| `jobs.status` | active, expired, flagged, merged_into | §2.6 |
| `jobs.title_family` | 13 members, extendable via `title_families.yaml` | §2.6 |
| `jobs.seniority` | intern … executive, unknown | §2.6 |
| `jobs.remote_mode` | onsite, hybrid, remote, unknown | §2.6 |
| `jobs.employment_type` | full_time, part_time, contract, internship, freelance, unknown | §2.6 |
| `jobs.salary.source` | listing, parsed, null | §2.6 |
| `jobs.skills_source` | listing, dictionary, llm | §2.6 |
| `jobs.quality_flags` | no_salary, vague_description, no_skills_listed, stale_posting, suspicious_contact, pay_to_apply | §2.6 |
| `user_job_actions.action` | hidden, not_interested, reported | §2.7 |
| `user_job_actions.reason` | salary_too_low, location, seniority_mismatch, not_my_field, company, already_applied, scam_suspected, other | §2.7 |
| `match_scores.band` | strong, good, partial, weak | §2.8 |
| `explain.skills_basis` | listing, dictionary, llm, semantic, none | §2.8 |
| `explain.*.verdict` | per component, registered in `enums.yaml` | §2.8 |
| `answer_bank.answer_type` | text, boolean, money, duration, date, url, enum | §2.9 |
| `application_packs.status` | draft, approved, superseded | §2.9 |
| `application_packs.tone` | concise, warm, formal | §2.9 |
| `fabrication_flags.status` | open, resolved, overridden | §2.9 |
| `applications.status` | saved, preparing, applied, screening, interview, offer, accepted, rejected, withdrawn, ghosted | §2.10 |
| `applications.applied_via` | external_link, manual, extension | §2.10 |
| `applications.source` | match, search, manual | §2.10 |
| `interviews.type` | screening, technical, system_design, behavioural, hr, take_home, panel, final, other | §2.10 |
| `interviews.outcome` | pending, passed, failed, cancelled, no_show | §2.10 |
| `salary_log.kind` | expectation_given, offer_received, counter_made, revised_offer, accepted | §2.10 |
| `reminders.type` | follow_up, interview_24h, interview_1h, deadline_48h, custom | §2.11 |
| `reminders.status` | scheduled, sending, sent, cancelled, failed | §2.11 |
| `audit_log.kind` | 10 members | §2.12 |
| `ai_usage.outcome` | ok, invalid_json, repaired, provider_error, budget_denied, cache_hit | §2.12 |
| `ai_usage.deny_reason` | user, feature, global, null | §2.12 |
| `Feature` (AI) | 10 members | `05-ai-layer.md` §1, mirrored here |
| `ErrorCode` | the full API code registry | `01-foundations.md` §12, mirrored here |

**Acceptance criteria.**
- `AC-DATA-07.1` `fields.yaml` regenerates from §2 with no diff against the committed copy.
- `AC-DATA-07.2` Every `` `collection.field` `` reference in every specification file resolves against `fields.yaml`; an unresolved reference fails with the file and line.
- `AC-DATA-07.3` `enums.yaml` contains every enum in the inventory table, and every table row matches the generated file.
- `AC-DATA-07.4` An enum member used in any file but absent from `enums.yaml` fails the check.
- `AC-DATA-07.5` No enum is declared in two files with different member sets — the check compares every `∈ {…}` declaration against the registry.
- `AC-DATA-07.6` Adding a field to a Beanie model without adding it to §2 fails the schema-snapshot test (`AC-DATA-02.1`), and adding it to §2 without the model fails `AC-DATA-07.1`.
- `AC-DATA-07.7` Every Pydantic enum in the codebase appears in `enums.yaml`, and every registry entry maps to a real enum or to a documented DB-only value set.

**Tests.**
- `T-DATA-07.1`–`.5` `tests/spec/test_field_registry.py`.
- `T-DATA-07.6` `tests/spec/test_schema_snapshot.py` (shared with `T-DATA-02.1`).
- `T-DATA-07.7` `tests/spec/test_enum_registry.py`.
