# 16 — Security, Privacy and Compliance

**Module:** cross-cutting; `apps/api/app/core/security`, `docs/compliance/`
**Track:** R1 except items marked R2 in §2
**Requirements:** `SEC-01` … `SEC-06`

Two things in this product are genuinely dangerous: it holds a complete professional history for each user, and it writes text those users send to employers under their own name. The first makes it a target; the second makes a defect reputational for the user rather than for us. Everything here follows from those two facts.

---

## 1. Threat model — `SEC-01`

**Objective.** Name what is actually being defended against, so controls can be judged against something.

**Constraints.** Assets, in order of consequence:

1. **A user's resume and profile.** A complete employment history, contact details, and often a current-employer name. Leakage is a privacy harm and, for someone job-hunting quietly, a professional one.
2. **The application record.** That someone applied to a competitor is more sensitive than the applications themselves.
3. **Credentials and sessions.** Account takeover exposes 1 and 2 and allows text to be sent as the user.
4. **The AI budget.** Abusable for cost, and it is a shared resource across users.
5. **The job corpus.** Low sensitivity, but its integrity matters: a poisoned corpus produces bad scores and, via prompt injection, bad letters.

Adversaries and the controls that answer them:

| Adversary | Goal | Primary control |
|---|---|---|
| Credential stuffer | Account takeover at scale | Argon2id, breach check, two-dimension rate limits (`02-auth-and-account.md` §9), enumeration-safe responses |
| Another user of the product | Read someone else's profile or applications | Ownership-only authorization, **404 not 403**, and the generated cross-tenant sweep (`02-auth-and-account.md` §6) |
| A malicious job listing | Manipulate extraction, scoring, or a cover letter; or attack the browser | Untrusted-content delimiting and the injection corpus (`05-ai-layer.md` §6), HTML allowlist sanitization, no model-driven control flow |
| An abusive signup | Consume the AI budget | Email verification before spend, per-user daily caps, invite-only R1 (D10) |
| A stolen device | Read tokens | In-memory access tokens, Keystore refresh, `allowBackup=false`, family revocation |
| A compromised dependency | Anything | Lockfiles, `pip-audit`/`npm audit`, Dependabot, no HTML parser or headless browser in the API image |
| Us, by accident | Leak PII into logs, prompts, or an AI provider | The log-privacy assertion (`AC-FOUND-14.1`), the file-boundary assertion (`AC-RES-05.2`), the contacts assertion (`AC-TRACK-03.3`) |

Explicitly **not** defended against in R1, recorded so the choice is deliberate: a compromised host (no HSM, no envelope encryption of the whole database); a malicious operator (there is one operator, and admin reads are audited rather than prevented); a targeted state-level adversary; access-token revocation before its 15-minute expiry (`AC-AUTH-04.7`).

**Acceptance criteria.**
- `AC-SEC-01.1` `docs/compliance/threat-model.md` exists containing the asset list, the adversary table, and the explicit non-goals, reviewed within 180 days.
- `AC-SEC-01.2` Every control named in the table maps to a passing test elsewhere in this specification (checked by the traceability gate).
- `AC-SEC-01.3` Every accepted risk has a named compensating control or an explicit "none".

**Tests.** `T-SEC-01.1`–`.3` `tests/spec/test_threat_model_doc.py`, `tests/spec/test_traceability.py` (shared).

---

## 2. Controls — `SEC-02`

**Objective.** OWASP ASVS L2 as the baseline, with each control stated as something checkable rather than as a principle.

| # | Area | Control | Track | Verified by |
|---|---|---|---|---|
| 1 | Passwords | Argon2id `m=64MiB, t=3, p=1`; breach check by k-anonymity; 10–128 chars; parameters stored with the hash and rehashed on login when raised | R1 | `AC-AUTH-01.2`, `AC-AUTH-01.6` |
| 2 | Tokens | RS256 access 15 min with no PII; opaque refresh, peppered hash, rotation, family revoke on reuse; 30 s skew | R1 | `AC-AUTH-04.1`–`.6` |
| 3 | Web session | Refresh in `Secure; HttpOnly; SameSite=Lax` host-scoped cookie; access in memory; **double-submit CSRF** on every state-changing route while cookie auth is in use | R1 | `AC-AUTH-04.4`, `AC-WEB-02.1`, `AC-WEB-02.4` |
| 4 | Authorization | Ownership-only; `user_id` in every query; **404 on failure**; generated cross-tenant sweep over every id-addressed route | R1 | `AC-AUTH-10.1`–`.5` |
| 5 | Transport | TLS and HSTS at Cloudflare; origin accepts Cloudflare ranges only | R1 | `AC-OPS-02.1` |
| 6 | Headers | Strict CSP (no inline script, no `eval`, connect to the API origin only), `X-Content-Type-Options`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy` denying camera/mic/geolocation | R1 | `AC-WEB-04.5` |
| 7 | CORS | Explicit origin allowlist, credentials true, **never** a wildcard outside local | R1 | `AC-SEC-02.1` |
| 8 | Input validation | Pydantic v2 strict, unknown keys rejected, DB CHECK-equivalents via collection validators as a backstop | R1 | `AC-FOUND-05.4`, `AC-PROF-01.5` |
| 9 | NoSQL injection | No user-supplied dict reaches a query; keys beginning `$` or containing `.` are rejected at the boundary; every query built from typed parameters | R1 | `AC-SEC-02.2` |
| 10 | Rate limits | Redis token bucket; two dimensions on auth; AI endpoints 20/hour/user; general 300/min/user; **fail closed** on auth when Redis is down | R1 | `AC-AUTH-09.1`–`.6` |
| 11 | Uploads | Magic-byte type detection, 5 MB cap, ZIP-bomb checks, ULID object keys, presigned 5-minute GETs, ownership before signing | R1 | `AC-RES-01.1`–`.3`, `AC-DATA-04.1`–`.4` |
| 12 | Malware scanning | ClamAV on uploads | **R2** | `AC-SEC-02.3` |
| 13 | SSRF | Every outbound URL derived from user input (manual-entry enrichment, `rss_generic`) resolves through a guard: host allowlist where applicable, DNS resolution with private/link-local/loopback/metadata ranges blocked, no redirect to a new host, 5 s timeout, capped response size | R1 | `AC-TRACK-01.4`, `AC-CONN-06.6` |
| 14 | Prompt injection | Untrusted content delimited with a nonce by the AI layer; the 25-payload corpus; no model-driven control flow; model output escaped and never linked | R1 | `AC-AI-06.1`–`.6` |
| 15 | Secrets | Environment only; Docker secrets in production; `gitleaks` in CI and on the history; no secret in an image layer or a client artifact | R1 | `AC-OPS-05.4`, `AC-OPS-02.6`, `AC-AI-05.5` |
| 16 | Log privacy | No email, token, code, PII, request body, resume text, or job text in any log; provider errors as codes | R1 | `AC-FOUND-14.1`, `AC-FOUND-14.5` |
| 17 | Dependencies | Lockfiles committed; `pip-audit` and `npm audit` in CI; Dependabot; **no HTML parser and no headless browser in the API image** | R1 | `AC-CONN-02.4` |
| 18 | Admin | Role-gated, 404 to others, separate lazy bundle, no mobile surface, every mutation and every individual-user read audited, optional IP allowlist | R1 | `AC-ADMIN-06.1`–`.7` |
| 19 | Field encryption | Application-level AES-GCM for `contact.phone` and document metadata, key from config | **R2** | `AC-SEC-02.4` |
| 20 | Audit integrity | `audit_log` append-only in code **and** by database privilege | R1 | `AC-DATA-02.4` |

**Additional acceptance criteria for this section.**
- `AC-SEC-02.1` No environment outside local permits a wildcard CORS origin; a regression test asserts the configured allowlist and rejects `*`.
- `AC-SEC-02.2` A payload containing `{"$ne": null}`, a key with a dot, and a nested `$where` is rejected at the boundary and never reaches a query — tested against every endpoint accepting an object.
- `AC-SEC-02.3` (R2) An EICAR test file is rejected on upload.
- `AC-SEC-02.4` (R2) `contact.phone` is unreadable in a raw database dump and readable through the API for its owner.
- `AC-SEC-02.5` The ASVS L2 checklist is completed with each item marked implemented, not applicable, or accepted-with-reason, and no item left blank.

**Tests.**
- `T-SEC-02.1` `tests/integration/test_cors.py`.
- `T-SEC-02.2` `tests/integration/test_nosql_injection.py`.
- `T-SEC-02.3` `tests/integration/test_clamav.py` (R2).
- `T-SEC-02.4` `tests/integration/test_field_encryption.py` (R2).
- `T-SEC-02.5` `tests/spec/test_asvs_checklist.py`.

---

## 3. AI-specific privacy — `SEC-03`

**Objective.** Be able to state, exactly and truthfully, what leaves our infrastructure and where it goes.

**Constraints.**
- **What is sent to an AI provider, exhaustively:** normalized resume text (extraction, quality feedback); job title, company, and up to 8,000 characters of description (enrichment, rationale, pack); confirmed profile fields (pack, answer suggestions, follow-up); answer-bank entries relevant to a job (pack); the application's job title, company, dates, and interview types (follow-up).
- **What is never sent, exhaustively:** any file's bytes (HR-8); the user's email address, phone number, or physical address; any contact's name, email, or phone (`AC-TRACK-03.3`); any password, token, or session identifier; any other user's data; `sensitive`-flagged answer-bank content (`09-apply.md` §1); unconfirmed profile fields (HR-7).
- Both lists are enforced by tests over captured outbound requests, not by review, and both appear verbatim in the consent copy (§4) and in `docs/compliance/ai-providers.md`.
- The user's identity is not sent: prompts carry no email and no name unless the name is a confirmed profile field the pack legitimately needs (a cover letter signature), in which case it is the name the user confirmed and nothing more.
- Provider selection, credentials, and billing isolation: `05-ai-layer.md` §5 (HR-6). The dedicated Cloud project and its own billing account are a procurement control with a named owner, checked at the R1 gate.
- The free-vs-paid tier decision (D5) determines the consent wording and must be settled before public sign-up.
- `docs/compliance/ai-providers.md` records, per provider: the endpoint, the credential type, the data-use terms as of a dated review, whether prompts may be used for training on the tier in use, retention, and the region.

**Acceptance criteria.**
- `AC-SEC-03.1` An outbound capture across every AI feature contains exactly the "what is sent" list and nothing from the "never sent" list, item by item, using distinctive seeded values for each forbidden item.
- `AC-SEC-03.2` The consent copy's data-sharing paragraph is generated from or asserted equal to the two lists above, so they cannot drift.
- `AC-SEC-03.3` `docs/compliance/ai-providers.md` contains every required field with a review date within 90 days (`AC-AI-05.1` shared).
- `AC-SEC-03.4` No prompt contains the user's email address or phone number (a dedicated assertion, because this is the likeliest accidental leak).
- `AC-SEC-03.5` A `sensitive` answer-bank entry never appears in a prompt.

**Tests.**
- `T-SEC-03.1` `tests/integration/test_ai_data_boundary.py`.
- `T-SEC-03.2` `tests/spec/test_consent_data_parity.py`.
- `T-SEC-03.3` `tests/spec/test_compliance_docs.py` (shared).
- `T-SEC-03.4` `tests/integration/test_no_pii_in_prompts.py`.
- `T-SEC-03.5` `tests/integration/test_sensitive_questions.py` (shared).

---

## 4. Consent, privacy notice and data rights — `SEC-04`

**Objective.** DPDP Act 2023 (India) and GDPR-aligned handling, implemented as product features rather than as a policy page.

**Constraints.**
- **Consent at registration**, not after, with itemized purposes the user can read in under a minute, above the fold, in plain language:
  1. What is stored: the resume file, its extracted text, the structured profile, preferences, applications, generated drafts, and reminders.
  2. What is sent to an AI provider: the §3 "what is sent" list, naming the provider, and — per D5 — whether prompts may be used to improve that provider's service.
  3. What is fetched from third parties: job listings from named sources, with the note that we contact them and they do not learn who is searching.
  4. Retention: the table from `17-data-model.md` §5, including that backups persist for 14 days after a deletion request.
  5. Rights: export (R2) and deletion, both as in-product actions with the 7-day clock stated.
- `consent` is an **array** on the user document (`17-data-model.md` §2.1): a new version appends with its timestamp and item keys. It never overwrites, because "what did this user agree to in September" must remain answerable.
- **A change to what we do requires re-consent, not a quiet policy edit.** The governing precedent is explicit: if a future feature sends something not on the §3 list, the consent version increments, the affected item is re-presented, and the user must accept before that feature applies to them. Existing consent is not silently widened.
- The privacy notice is a document in the repository, versioned with the code, rendered by both clients from one source so web and mobile cannot show different promises. Rendered with the scheme-allowlist markdown renderer.
- Data residency: Atlas Mumbai (`ap-south-1`, D2). R2 has no regional pinning; data is encrypted at rest and this is disclosed.
- Deletion (`AUTH-07`) and export (`AUTH-08`, R2) are user-facing features with the enforcement in `17-data-model.md` §5 and `02-auth-and-account.md` §7.
- The Play Store data-safety declaration is generated from the same source (`AC-MOB-08.4`).
- **AI transparency**, per HR-9: every generated artifact is labelled in the UI, stores its model and prompt version, and the match breakdown links to a "how this score was computed" explanation of the components — which the deterministic scorer makes genuinely possible rather than a gesture.

**Acceptance criteria.**
- `AC-SEC-04.1` Registration cannot complete without the current consent version, and a stale version is rejected (`AC-AUTH-01.7` shared).
- `AC-SEC-04.2` `consent` is append-only: a second acceptance adds an entry and preserves the first.
- `AC-SEC-04.3` Both clients render the notice from one source; a test asserts the rendered text is identical.
- `AC-SEC-04.4` The notice's data-sharing section matches the §3 lists (`AC-SEC-03.2` shared).
- `AC-SEC-04.5` A simulated new-purpose feature gated on a new consent version does not apply to a user who has not accepted it.
- `AC-SEC-04.6` The retention section matches `17-data-model.md` §5, asserted programmatically against the retention registry.
- `AC-SEC-04.7` Deletion and export are reachable in three taps or fewer from settings in both clients.
- `AC-SEC-04.8` Every AI-generated artifact in the UI carries its label, and the score view links to the component explanation (`AC-WEB-04.1`, `AC-MATCH-02.1` shared).

**Tests.**
- `T-SEC-04.1` `tests/integration/test_consent_capture.py` (shared).
- `T-SEC-04.2` `tests/integration/test_consent_append_only.py`.
- `T-SEC-04.3` `tests/spec/test_notice_parity.py`.
- `T-SEC-04.4` `tests/spec/test_consent_data_parity.py` (shared).
- `T-SEC-04.5` `tests/integration/test_consent_gating.py`.
- `T-SEC-04.6` `tests/spec/test_retention_coverage.py` (shared).
- `T-SEC-04.7` `apps/web/e2e/data-rights.spec.ts`, `apps/mobile/integration_test/data_rights_test.dart`.
- `T-SEC-04.8` component tests (shared).

---

## 5. Connector compliance process — `SEC-05`

**Objective.** Keep HR-2 true over time, not just on the day each connector is written.

**Constraints.**
- Every connector carries `COMPLIANCE.md` with the fixed heading set, validated at registry load (`06-connectors.md` §4). No document, no connector.
- `connectors/EXCLUDED.md` names every source we deliberately do not integrate, with the terms clause that prohibits it and a checked date. Its presence is what makes the exclusion a decision rather than an oversight.
- **Review cadence**: the admin dashboard shows review age; over 180 days warns, over 365 days auto-disables the connector at load. A source's terms changing without our noticing is the realistic failure, and an auto-disable is a safe default.
- Source terms are re-read, not assumed, at each review, and the review records what changed.
- Attribution is rendered on every card and detail view in both clients (`AC-CONN-04.4`).
- Cached listing content is retained only while the listing is active plus 30 days, or a shorter source-imposed limit (`meta.listing_ttl_days`), whichever is less.
- **A source that adds a term we cannot meet is removed, not worked around.** The connector is disabled, its jobs age out by the staleness rule, and applications referencing them keep working — which is exactly why the retention rule keeps referenced jobs.
- The legal review of the compliance files is an R2 gate item (`00-scope-and-phases.md` §3.2, item 3).

**Acceptance criteria.**
- `AC-SEC-05.1` Every registered connector has a valid, current compliance record (`AC-CONN-04.1`–`.3` shared).
- `AC-SEC-05.2` `EXCLUDED.md` covers every source in HR-2's list with a clause reference and a date within 180 days.
- `AC-SEC-05.3` Disabling a connector for a terms change leaves its jobs viewable via existing applications and removes them from search within the staleness window.
- `AC-SEC-05.4` No HTML parser or headless browser is present in the API's production dependencies (`AC-CONN-02.4` shared).
- `AC-SEC-05.5` A source-imposed listing TTL is enforced (`AC-CONN-04.5` shared).

**Tests.**
- `T-SEC-05.1` `tests/connectors/test_compliance_records.py` (shared).
- `T-SEC-05.2` `tests/spec/test_excluded_sources_doc.py` (shared).
- `T-SEC-05.3` `tests/integration/test_connector_removal.py`.
- `T-SEC-05.4` `tests/spec/test_no_scraping_deps.py` (shared).
- `T-SEC-05.5` `tests/integration/test_source_ttl.py` (shared).

---

## 6. Application-assistance ethics — `SEC-06`

**Objective.** State the product's ethical commitments as enforced properties, because they are the reason a user can trust it with their name.

**Constraints.**
- **Human in the loop, always** (HR-1). Nothing is submitted without an explicit per-application approval. There is no bulk apply, no unattended apply, no flag that enables one, and no HTTP client in `modules/apply` capable of submitting. The extension (R3) fills but never presses submit and never touches a CAPTCHA.
- **No fabrication** (HR-4). Generated content may reframe and emphasize what the user has confirmed; it may never invent an employer, a date, a degree, a certification, a title, a tool, or a number. The three-layer checker (`09-apply.md` §4) has 100% recall on its positive corpus as a hard gate, and a user may always override with an audited record — the product never overrides for them.
- **Only confirmed facts** (HR-7). Unconfirmed extractions never enter a prompt, so an extraction error cannot become a claim in a letter.
- **Honesty about gaps.** Where a required skill is missing, the letter may acknowledge it truthfully (`gap_acknowledgements`) and may never claim it.
- **Respect for the target site.** No background navigation, no automated form submission, no CAPTCHA circumvention, no rate abuse of an employer's site. The product opens the posting in the user's own browser and gets out of the way.
- **No misrepresentation in marketing or store listings** (`AC-MOB-08.3`). "Assisted" is the claim because assisted is the product.
- **Sensitive questions are the user's alone** (`09-apply.md` §1): demographic, disability, and current-salary questions are never AI-suggested.
- These commitments are recorded in `docs/compliance/ethics.md` alongside the enforcing test for each, so a future change that breaks one breaks a test rather than a promise nobody remembers.

**Acceptance criteria.**
- `AC-SEC-06.1` No submission capability exists in the codebase (`AC-APPLY-05.1` shared).
- `AC-SEC-06.2` No flag or configuration enables automated submission (`AC-APPLY-05.2` shared).
- `AC-SEC-06.3` Fabrication recall on the positive corpus is 100% (`AC-APPLY-04.1` shared) and every override is audited (`AC-APPLY-04.5` shared).
- `AC-SEC-06.4` No unconfirmed field reaches a prompt (`AC-APPLY-02.1` shared).
- `AC-SEC-06.5` `docs/compliance/ethics.md` lists each commitment with its enforcing test identifier, and the traceability gate verifies each identifier exists.
- `AC-SEC-06.6` The store listing and the marketing copy in the repository contain no prohibited automation claim (`AC-MOB-08.3` shared).

**Tests.**
- `T-SEC-06.1`–`.4` shared, as named.
- `T-SEC-06.5` `tests/spec/test_ethics_doc.py`.
- `T-SEC-06.6` `tests/spec/test_store_listing_claims.py` (shared).
