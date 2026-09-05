# 04 — Resume Pipeline

**Module:** `apps/api/app/modules/resume`
**Track:** R1 except §3.1 (R2), §6 (R2), §7 (R2)
**Depends on:** `01-foundations.md` §10–11, `05-ai-layer.md`, `17-data-model.md` §2.4, `03-profile.md` §2
**Requirements:** `RES-01` … `RES-07`
**Public API:** `ResumeService.upload`, `.get`, `.status`, `.reanalyze`, `.set_default`, `.delete`, `.download_url`
**Publishes:** `ResumeExtracted`. **Consumes:** none.

This is the first thing a new user does that takes real time, and the first place the product can lose their trust. Two rules shape everything here: the user always knows what stage it is at, and the machine's output is a **proposal**, never an assignment.

---

## 1. Upload and validation — `RES-01`

**Objective.** Accept a resume file safely, or reject it with a message that tells the user what to do instead.

**Constraints.**
- Accepted: PDF (`application/pdf`) and DOCX (`…wordprocessingml.document`). Nothing else in R1 — no DOC, no RTF, no ODT, no images. Each rejection names the accepted formats.
- Size cap 5 MB, enforced by streaming and aborting at the limit, not by trusting `Content-Length`.
- Type is determined by **magic bytes**, not by the extension or the client's declared content type (`17-data-model.md` §4). A `.pdf` that is really a ZIP is rejected `unsupported_file_type`.
- A DOCX is a ZIP: it is checked for zip-bomb characteristics (entry count, total uncompressed size, compression ratio) before any parsing, and rejected `file_rejected_suspicious` beyond the thresholds.
- Requires `email_verified` (`02-auth-and-account.md` §3) — this is the gate on AI spend.
- Streamed straight to R2 under `u/{user_id}/resumes/{resume_id}.{ext}`; the API never holds the whole file in memory (`AC-DATA-04.3`).
- `sha256` of the bytes is stored; re-uploading an identical file returns the existing resume rather than re-extracting (idempotency by content, which matters because users double-submit).
- R1 permits one resume per user. A second upload replaces the first: the old `r2_key` is deleted after the new extraction succeeds, never before.
- Rate limited: 5 uploads per hour per user.

**Inputs.** `POST /profile/resumes` multipart, optional `label`.

**Outputs.** `resumes` document with `status: uploaded`; enqueued `resume.process`; `202 {task_id, status, status_url, events_url}`.

**Acceptance criteria.**
- `AC-RES-01.1` A 5.1 MB file is rejected with `413 file_too_large` and no object is written to storage.
- `AC-RES-01.2` A `.png` renamed `.pdf` is rejected `415 unsupported_file_type`; a real PDF with a `.txt` name is accepted.
- `AC-RES-01.3` A DOCX with 10,000 entries or a 100:1 compression ratio is rejected `file_rejected_suspicious` before parsing.
- `AC-RES-01.4` An unverified user gets `403 email_not_verified` and no object is written.
- `AC-RES-01.5` Uploading the same bytes twice returns the same `resume_id` and runs extraction once.
- `AC-RES-01.6` Uploading a second, different resume leaves the first object in place until the new extraction reaches `ready`, then deletes it.
- `AC-RES-01.7` The 6th upload in an hour returns 429.

**Tests.**
- `T-RES-01.1`–`.3` `tests/integration/test_upload_validation.py`.
- `T-RES-01.4` `tests/integration/test_email_verification.py` (shared).
- `T-RES-01.5` `tests/integration/test_upload_idempotency.py`.
- `T-RES-01.6` `tests/integration/test_resume_replacement.py`.
- `T-RES-01.7` `tests/integration/test_rate_limits.py` (shared).

---

## 2. The stage machine and progress reporting — `RES-06`

**Objective.** During the 20–60 seconds this takes, the user sees which of four things is happening and never wonders whether it is stuck.

**Constraints.**
- Stages, in order, each with a user-facing label: `uploaded` → `extracting_text` → `structuring` → `ready`, plus terminal `failed`. These five values **are** `resumes.status` — one enum, not a coarse status plus a finer stage (`17-data-model.md` §2.4, consistency finding F1). `status` and `progress` (0–100) are stored on the document and emitted over SSE (`01-foundations.md` §11).
- Every stage transition is persisted **before** the event is emitted, so a client that reconnects and polls sees the same truth.
- The whole flow must be completable by polling `status_url` alone (`AC-FOUND-11.2`).
- The pipeline is a single ARQ task (`resume.process(resume_id)`), idempotent on `(resume_id, status)`: re-running it from any non-terminal stage resumes rather than restarting, because re-running extraction costs money.
- A stage that exceeds its budget (text extraction 30 s, structuring 90 s) fails that stage with a specific code rather than hanging.
- `failed` always carries a user-facing reason from a fixed set: `no_text_layer`, `text_too_short`, `extraction_invalid`, `ai_unavailable`, `internal`. A raw exception message is never shown.
- On `ai_unavailable` (budget or provider outage, `05-ai-layer.md` §3), the task retries with backoff for up to 24 h and the user sees "finishing shortly" — it does **not** become `failed`.
- p95 for the whole pipeline < 60 s (BRD NFR).

**Inputs.** `resume_id`.

**Outputs.** Stage transitions; SSE events `{stage, progress, status, detail, at}`; `ResumeExtracted` on success.

**Acceptance criteria.**
- `AC-RES-06.1` A successful run emits the four stages in order, each with monotonically non-decreasing `progress`, ending at 100.
- `AC-RES-06.2` Killing the worker during `structuring` and restarting completes the resume exactly once, with one `ai_usage` row for the extraction (or two only if the first was never billed).
- `AC-RES-06.3` The stage stored in Mongo always equals or precedes the last emitted event (never the reverse).
- `AC-RES-06.4` A resume with no text layer reaches `failed` with `no_text_layer` and a message naming what the user can do.
- `AC-RES-06.5` With the AI budget exhausted, the resume stays `structuring` with detail "finishing shortly" and completes once the budget resets, without user action.
- `AC-RES-06.6` p95 of the pipeline over 20 sample resumes is under 60 s on staging.
- `AC-RES-06.7` The full onboarding flow completes with SSE blocked at the proxy, using polling only.

**Tests.**
- `T-RES-06.1` `tests/integration/test_resume_stages.py`.
- `T-RES-06.2` `tests/integration/test_worker_restart.py` (shared).
- `T-RES-06.3` `tests/integration/test_stage_ordering.py`.
- `T-RES-06.4` `tests/integration/test_resume_failures.py`.
- `T-RES-06.5` `tests/ai/test_degradation.py` (shared).
- `T-RES-06.6` `tests/integration/test_resume_latency.py` (nightly).
- `T-RES-06.7` `tests/integration/test_poll_fallback.py` (shared).

---

## 3. Text extraction — `RES-02`

**Objective.** Get the resume's text out with enough layout fidelity that a language model can tell a heading from a bullet.

**Constraints.**
- PDF via PyMuPDF, DOCX via `python-docx`. Both run **in the worker**, never in the API process.
- Layout preservation matters more than raw text: extract in reading order, preserve paragraph breaks, keep bullet markers, and keep table cells separated by a delimiter rather than collapsed. A two-column resume flattened into interleaved lines destroys extraction accuracy, so column detection (by x-coordinate clustering) is part of R1, not an enhancement.
- Output is normalized: NFKC, ligatures expanded, non-breaking spaces to spaces, repeated blank lines collapsed to two, control characters stripped, hyphenated line-breaks rejoined.
- The text is written to R2 at `u/{user_id}/resumes/{resume_id}.txt`; Mongo keeps `text_chars` and a 500-character excerpt only (`17-data-model.md` §2.4).
- **Guardrails.** `text_chars < 200` → `failed: text_too_short` (a scanned page or an empty document). `text_chars > 60,000` → truncated at a paragraph boundary with a recorded flag; no resume needs more.
- Untrusted content: the extracted text is a prompt input and is handled per HR-11 (`05-ai-layer.md` §6). Any embedded PDF JavaScript, form actions, and annotations are discarded, never executed and never included in the text.
- Parsing runs with a wall-clock and memory cap; a malformed file that hangs the parser must fail the stage, not the worker.

### 3.1 OCR fallback — **Track: R2**

Tesseract on rasterized pages when `text_chars < 200` and the PDF has ≥1 image covering >60% of a page. Capped at 10 pages, 120 s, and marked `text_source: ocr` so the extraction prompt can be told the input is OCR (which changes how it should treat garbled tokens). Adds ~200 MB to the image, which is why it is R2 and behind `FLAG_OCR_ENABLED`.

**Inputs.** The stored file.

**Outputs.** Normalized text in R2; `text_chars`; `text_source ∈ {pdf, docx, ocr}`.

**Acceptance criteria.**
- `AC-RES-02.1` A two-column PDF fixture extracts with each column's text contiguous, verified against a hand-written expected ordering.
- `AC-RES-02.2` A table in a DOCX extracts with cell boundaries preserved, not concatenated.
- `AC-RES-02.3` Bullet markers survive; a bulleted list of 6 items yields 6 lines.
- `AC-RES-02.4` A hyphenated word broken across lines is rejoined without a hyphen.
- `AC-RES-02.5` A PDF with embedded JavaScript and an annotation yields text containing neither, and nothing is executed.
- `AC-RES-02.6` A 120-character resume fails `text_too_short`; a 70,000-character one is truncated at a paragraph boundary with the flag set.
- `AC-RES-02.7` A deliberately malformed PDF fails the stage within the time cap and the worker survives to process the next job.
- `AC-RES-02.8` (R2) An image-only PDF with OCR enabled reaches `ready` with `text_source: ocr`; with OCR disabled it fails `no_text_layer`.

**Tests.**
- `T-RES-02.1`–`.4` `tests/unit/test_text_extraction.py` with fixtures in `tests/fixtures/resumes/`.
- `T-RES-02.5` `tests/unit/test_pdf_sanitization.py`.
- `T-RES-02.6` `tests/unit/test_text_guardrails.py`.
- `T-RES-02.7` `tests/integration/test_malformed_pdf.py`.
- `T-RES-02.8` `tests/integration/test_ocr_fallback.py` (R2).

---

## 4. Structured extraction — `RES-03`

**Objective.** Turn resume text into a `ProfileExtraction` that is honest about what it does and does not know.

**Constraints.**
- One `complete_json` call at the `fast` tier with the `ProfileExtraction` schema (§4.1). Prompt `resume_extract/vN` (`05-ai-layer.md` §7).
- Prompt rules, all enforced by the schema and by the golden tests: extract only what is present; never infer an employer, a date, or a degree; `evidence` must be a verbatim span of ≤15 words; unknown is `null`, never a guess; every item carries a confidence.
- Invalid JSON: exactly one repair retry with the validation error included, then `failed: extraction_invalid` (`AC-AI-05.6`).
- Chunking above 30,000 characters: split on section boundaries, extract per chunk, merge with a documented conflict rule (later chunks lose on `identity`; arrays concatenate then deduplicate by a natural key). Chunked runs are flagged so precision can be measured separately.
- The result is written to `resumes.extraction` and published as `ResumeExtracted`. It is **never written into the profile by this module** — `profile.stage_extraction` does the staging (`03-profile.md` §2), and only the user applies it.
- Every skill in the extraction is canonicalized through `profile.canonicalize` before staging, keeping unmapped skills with `canonical: null`.

### 4.1 `ProfileExtraction` schema

Carried forward from BRD v1.0 Appendix B unchanged in shape, with two additions:

```json
{
  "identity": { "full_name": "str|null", "headline": "str|null", "summary": "str|null",
                "location": { "city": "str|null", "country": "ISO2|null" } },
  "contact": { "email": "str|null", "phone": "str|null",
               "links": [ { "type": "github|linkedin|portfolio|other", "url": "str" } ] },
  "skills": [ { "name": "str", "years": "number|null",
                "level": "beginner|intermediate|advanced|expert|null",
                "confidence": "0-1", "evidence": "verbatim <=15 words" } ],
  "experience": [ { "company": "str", "title": "str", "start": "YYYY-MM|null", "end": "YYYY-MM|null",
                    "current": "bool", "bullets": ["str"], "skills": ["str"], "confidence": "0-1",
                    "evidence": "verbatim <=15 words" } ],
  "education": [ { "institution": "str", "degree": "str|null", "field": "str|null",
                   "start": "YYYY|null", "end": "YYYY|null", "confidence": "0-1" } ],
  "certifications": [ { "name": "str", "issuer": "str|null", "year": "int|null" } ],
  "projects": [ { "name": "str", "description": "str", "skills": ["str"], "url": "str|null" } ],
  "languages": [ { "name": "str", "level": "str|null" } ],
  "warnings": ["str"],
  "suspected_injection": "bool"
}
```

Additions: `evidence` on `experience` (v1.0 had it only on skills) so the review screen can justify a job entry; `suspected_injection` per HR-11.

**Inputs.** Normalized resume text; the prompt; the schema.

**Outputs.** `resumes.extraction`; `extraction_model`; `prompt_version`; `ResumeExtracted`.

**Acceptance criteria.**
- `AC-RES-03.1` Output validates against `ProfileExtraction`; an invalid response triggers exactly one repair and then fails cleanly.
- `AC-RES-03.2` Every `evidence` string is a verbatim substring of the extracted text and is ≤15 words (checked programmatically, not by the model's promise).
- `AC-RES-03.3` A resume with no education section yields `education: []`, not an invented entry — asserted across the golden set.
- `AC-RES-03.4` A resume with an ambiguous date ("2021–present") yields `start: "2021-01"` only if the text says so, else `null` with a warning; no fabricated month.
- `AC-RES-03.5` Extraction precision on the 10-resume golden set is ≥90% field-level for skills and employers (`AC-AI-07.5`).
- `AC-RES-03.6` A resume containing an injection payload yields a valid extraction, `suspected_injection: true`, and no field whose value is the injected instruction.
- `AC-RES-03.7` A 45,000-character resume is chunked, merged per the documented rule, and flagged `chunked: true`.
- `AC-RES-03.8` No extraction result is written directly to `profiles`; the only writer is `profile.stage_extraction`.

**Tests.**
- `T-RES-03.1` `tests/ai/test_structured_repair.py` (shared).
- `T-RES-03.2` `tests/unit/test_evidence_spans.py` (shared with `T-PROF-03.7`).
- `T-RES-03.3`/`.4` `tests/ai/test_golden_fake.py` + `tests/ai/test_extraction_precision.py`.
- `T-RES-03.5` `tests/ai/test_extraction_precision.py`.
- `T-RES-03.6` `tests/ai/test_injection_corpus.py` (shared).
- `T-RES-03.7` `tests/unit/test_extraction_chunking.py`.
- `T-RES-03.8` `tests/spec/test_collection_ownership.py` (shared).

---

## 5. Storage and the AI boundary — `RES-05`

**Objective.** The file the user uploaded stays ours (HR-8).

**Constraints.**
- The original file goes to R2 and **never** to any AI provider — not as bytes, not as a base64 attachment, not via a file-upload API, not as a URL the provider could fetch. Only extracted text is sent.
- The provider request is constructed from `untrusted={"resume_text": ...}` (`05-ai-layer.md` §6) and the adapter renders it. There is no code path in `modules/resume` that can attach a file to an AI request, because the `LLMRequest` type has no field for one — which is the actual enforcement.
- Downloads are presigned, 5-minute TTL, issued only after an ownership check, with a sanitized `Content-Disposition` filename.
- The extracted text in R2 is subject to the same deletion sweep as the original.

**Inputs.** The stored object; the extracted text.

**Outputs.** Presigned download URLs; the AI request.

**Acceptance criteria.**
- `AC-RES-05.1` `LLMRequest` has no field capable of carrying bytes, a file handle, or a storage URL (type introspection).
- `AC-RES-05.2` An outbound-request capture over the whole pipeline shows no request to a provider host containing the file's bytes or its storage URL.
- `AC-RES-05.3` The only provider-bound payload derived from the resume is the normalized text, asserted by hashing the text and finding that hash's content in the captured request body and nothing else file-derived.
- `AC-RES-05.4` A download URL for another user's resume is never issued (404).
- `AC-RES-05.5` A filename containing `../`, a newline, or a quote produces a safe `Content-Disposition`.

**Tests.**
- `T-RES-05.1` `tests/unit/test_llm_request.py` (shared).
- `T-RES-05.2`/`.3` `tests/integration/test_no_file_to_provider.py` (respx capture across the pipeline).
- `T-RES-05.4` `tests/integration/test_presigned_urls.py` (shared).
- `T-RES-05.5` `tests/unit/test_content_disposition.py`.

---

## 6. Quality feedback — `RES-04` — **Track: R2**

**Objective.** Tell the user what a recruiter would notice, as suggestions they can ignore.

**Constraints.** A second `fast`-tier call producing `QualityFeedback[]` with `{category, severity, message, target_path|null}` where `category ∈ {missing_section, weak_bullet, length, contact, formatting, keyword}`. Deterministic checks run **first** and cheaply (no summary, no metrics in any bullet, missing contact, >2 pages, dates with gaps) and the model is asked only for bullet-level rewording suggestions. Never blocks anything. Rendered with an AI label (HR-9). Skipped silently on budget exhaustion.

**Acceptance criteria.** `AC-RES-04.1` Deterministic checks fire without any AI call. `AC-RES-04.2` Every item has a target path or is explicitly document-level. `AC-RES-04.3` Feedback never changes `status` or blocks progression. `AC-RES-04.4` Budget exhaustion yields deterministic items only, no error.
**Tests.** `T-RES-04.1`–`.4` `tests/unit/test_quality_checks.py`, `tests/integration/test_quality_feedback.py`.

---

## 7. Re-analysis and the diff view — `RES-07` — **Track: R2**

**Objective.** Re-run extraction on an improved resume without silently overwriting what the user has corrected.

**Constraints.** `POST /profile/resumes/{id}/reanalyze` (idempotent, rate limited 3/day) re-runs §3–§4 and writes `staged_extraction`. The client renders a three-way diff: current confirmed value, current unconfirmed value, proposed value — per field, with accept/reject per field and "accept all unconfirmed". Confirmed fields are never auto-changed (`AC-PROF-03.4`). Applying bumps `profile.version` once for the whole batch, publishing one `ProfileUpdated`, so one rescore follows rather than dozens.

**Acceptance criteria.** `AC-RES-07.1` Re-analysis never mutates a confirmed field. `AC-RES-07.2` The diff response contains all three values per changed field. `AC-RES-07.3` Applying a batch bumps `version` by one and emits one event. `AC-RES-07.4` A rejected suggestion is not re-proposed by the next re-analysis of the same text (recorded rejection).
**Tests.** `T-RES-07.1`–`.4` `tests/integration/test_reanalysis.py`.
