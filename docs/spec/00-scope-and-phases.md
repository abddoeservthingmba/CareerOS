# 00 — Scope Split, Phases and Gates

**Depends on:** `README.md`
**Governs:** the `Track:` line on every section in every other file
**Machine-readable counterpart:** `dependencies.yaml` (`18-dependency-closure.md` §1) — the track and phase columns below are checked against it in CI

---

## 1. The three tracks

### 1.1 Definitions

| Track | Name | Question it answers | Ships when |
|---|---|---|---|
| **R1** | Core release | Does the loop work, end to end, for one motivated user? | The R1 exit sentence (§1.2) passes on web and Android, on staging data |
| **R2** | Stabilization | Would I let a stranger use this, and could I operate it while asleep? | The R2 gate checklist (§3.2) is fully green |
| **R3** | Later enhancements | What makes it better once people are actually using it? | Never as a batch — one item at a time, driven by usage |

R1 and R2 are **release trains with gates**. R3 is a backlog, deliberately undated.

The rule that decides the boundary: **R1 contains only what the exit sentence cannot be spoken without.** R2 contains what makes R1 trustworthy, operable, and pleasant. R3 contains what makes it competitive.

### 1.2 The R1 exit sentence

> A new user signs up with email or Google, verifies their address, uploads a PDF resume, reviews and corrects the extracted profile, sets their preferences, sees at least fifty jobs scored against that profile with a breakdown they can read, shortlists five, generates an application pack for one, edits and approves it, opens the original posting, confirms they applied, and receives a follow-up reminder seven days later — on web **and** on Android, against jobs ingested from at least three independent sources.

Every R1 acceptance criterion in this specification exists to make one clause of that sentence verifiable. If a proposed R1 item does not map to a clause, it is not R1.

### 1.3 What R1 deliberately is not

- Not multi-persona. P2 (passive explorer) needs the digest; P3 (career switcher) needs gap analysis. Both are R2/R3. R1 is built for P1.
- Not multi-source-complete. Three connectors, not nine.
- Not narrated. The match breakdown is deterministic and rendered from stored fields; the LLM rationale paragraph is built but off in production.
- Not operable unattended. Backups exist (`OPS-06`) but the restore drill, the load test, and the runbooks are R2.
- Not exportable. Deletion is R1 because it is a legal obligation with a 7-day clock; export is R2 because a support-ticket answer is an acceptable stopgap for a private beta and is not for a public one.
- Not iOS.

---

## 2. Track assignment for every requirement

Complete and exhaustive against BRD v1.0 §5. Every requirement appears exactly once. `R1 / R2` means the requirement is split — the split is stated in the reason column and detailed in the module file.

### 2.1 Authentication & Account

| ID | Requirement | BRD pri | Track | Reason |
|---|---|---|---|---|
| AUTH-01 | Email + password registration, breached-password check | M | **R1** | Front door |
| AUTH-02 | Google OIDC sign-in | M | **R1** | Most users will pick it; retrofitting account linking after real accounts exist is a migration |
| AUTH-03 | Email verification gate before resume upload | M | **R1** | Gate on the one expensive operation; also the anti-abuse floor for AI spend |
| AUTH-04 | Access + rotating refresh tokens, reuse detection | M | **R1** | Session design is not retrofittable |
| AUTH-05 | Password reset | M | **R1** | Without it, every locked-out user is a support ticket you answer by hand |
| AUTH-06 | Session list, sign out everywhere | S | R2 | No user has three devices in a private beta |
| AUTH-07 | Account deletion, 7-day hard delete incl. R2 objects | M | **R1** | Legal obligation with a clock (DPDP §7.3); the R2 object sweep is the hard part and must be built with the storage layer |
| AUTH-08 | Data export | S | R2 | Legal obligation without a fixed clock; answerable by hand for a beta of tens of users, not for a public launch |
| AUTH-09 | Auth rate limiting per IP and per account | M | **R1** | Costs nothing once Redis exists; absence is a credential-stuffing invitation |
| AUTH-10 | Authorization model: ownership-only, 404 not 403, generated cross-tenant sweep | *new* | **R1** | Not a BRD requirement, but the control everything else assumes. Added because "every query carries `user_id`" was prose in v1.0 §16 with nothing testing it |

### 2.2 Candidate Profile

| ID | Requirement | BRD pri | Track | Reason |
|---|---|---|---|---|
| PROF-01 | Structured profile schema | M | **R1** | The spine of everything downstream |
| PROF-02 | Preferences | M | **R1** | Without preferences there is no candidate set and therefore no feed |
| PROF-03 | Per-field `source`/`confidence`/`confirmed` provenance | M | **R1** | HR-7 depends on it; adding provenance to existing rows later means guessing |
| PROF-04 | Multiple resume versions | S | R3 | A second resume changes profile-skill union semantics and default selection. Real feature, not polish; do it when someone asks |
| PROF-05 | Completeness score with prompts | S | R2 | Onboarding nudge, not a capability |
| PROF-06 | Skill canonicalization + alias table | M | **R1** | Scoring compares canonical skills; without it "ReactJS" ≠ "React" and every score is wrong |
| PROF-07 | Field-level audit history | S | R2 | Useful for debugging extraction, needed by nobody in R1 |

### 2.3 Resume Analysis

| ID | Requirement | BRD pri | Track | Reason |
|---|---|---|---|---|
| RES-01 | PDF + DOCX ≤5 MB, clear rejection | M | **R1** | — |
| RES-02a | PDF/DOCX text extraction | M | **R1** | — |
| RES-02b | OCR fallback for image-only PDFs | S | R2 | Adds Tesseract to the image and a slow path; failure message ("this PDF has no text layer") is acceptable in R1 |
| RES-03 | Schema-constrained AI extraction with one repair retry | M | **R1** | — |
| RES-04 | Resume quality feedback | S | R2 | Advice, not extraction |
| RES-05 | Original in R2 storage, text + JSON in Mongo, **file bytes never to AI** | M | **R1** | HR-8 |
| RES-06 | Async pipeline with staged status via SSE/poll | M | **R1** | 30–60 s of silence during onboarding is where users leave |
| RES-07 | Re-analyze with diff view before applying | S | R2 | R1 has one resume and a review screen; re-upload is the workaround |

### 2.4 Job Search & Normalization

| ID | Requirement | BRD pri | Track | Reason |
|---|---|---|---|---|
| JOB-01 | Canonical `Job` schema | M | **R1** | — |
| JOB-02 | Scheduled per-connector ingestion + on-demand refresh | M | **R1** | Scheduled only in R1; per-saved-search refresh follows JOB-07 to R2 |
| JOB-03 | Dedup: exact, then fuzzy cross-source with merge | M | **R1** | Merge semantics (`source_refs[]`) shape the document. Retrofitting a merge onto duplicated rows means reconciling applications that point at the losing copy |
| JOB-04 | Normalization: title family, seniority, location, salary, type, dates | M | **R1** | Scoring reads only normalized fields |
| JOB-05 | Skill extraction — dictionary first, LLM enrichment for top-N | M | **R1** | Dictionary is the R1 default; enrichment ships behind the AI budget gate |
| JOB-06 | Full-text search + filters | M | **R1** | — |
| JOB-07 | Saved searches with notification opt-in | S | R2 | Ships with the digest (NOTIF-04); both serve P2 |
| JOB-08 | Staleness after 3 unseen ingestions; expired jobs stay in Tracker | M | **R1** | A tracker full of dead links is worse than no tracker |
| JOB-09 | Hide / not interested with reason | M | **R1** | The only feed control in R1, and it feeds MATCH-06 later |
| JOB-10 | Report listing as spam/scam | S | R2 | Ships with the operator queue (ADMIN-05) |

### 2.5 Connectors

| ID | Requirement | BRD pri | Track | Reason |
|---|---|---|---|---|
| CONN-01 | `BaseConnector` contract | M | **R1** | — |
| CONN-02 | Plugin isolation; core imports only the interface | M | **R1** | The brief's O6; enforced by import contract, not intention |
| CONN-03 | Enable/disable, rate limiter, retry, circuit breaker | M | **R1** | One flaky source must not stall ingestion for the others |
| CONN-04 | Per-connector compliance record | M | **R1** | HR-2's paper trail; written when the connector is written or never |
| CONN-05 | Raw payload retention, 30-day TTL | S | **R1** | Promoted. Debugging a normalizer without the raw payload is guesswork, and a TTL index is one line |
| CONN-06a | Connectors: `adzuna`, `remotive`, `greenhouse_board` | M | **R1** | One paid-key aggregator with India coverage, one keyless global remote source, one per-company board family. Three independent shapes, which is what proves the framework |
| CONN-06b | Connectors: `jooble`, `arbeitnow`, `himalayas`, `lever_postings`, `ashby_board`, `rss_generic` | M | R2 | Volume and coverage, not capability. Each is a file plus fixtures once R1's pipeline is proven |
| CONN-07 | Attribution + "view original" on every job | M | **R1** | Terms compliance, and it is a UI string |

### 2.6 Matching

| ID | Requirement | BRD pri | Track | Reason |
|---|---|---|---|---|
| MATCH-01 | 0–100 score with component breakdown | M | **R1** | — |
| MATCH-02a | Deterministic explain payload (matched/missing skills, verdicts, red flags) | M | **R1** | This is what "explainable" means to the user and what the UI renders |
| MATCH-02b | LLM rationale paragraph for top-N | M | **R1 code, R2 on** | Flagged decision, `README.md` §1 Call 1. Built and tested in R1 against the fake provider; `FLAG_LLM_RATIONALE_ENABLED=false` in production until AI budget accounting has two weeks of data |
| MATCH-03 | Deterministic, reproducible, versioned weights | M | **R1** | HR-3 and the ability to explain a score a week later |
| MATCH-04 | Embedding similarity component | M | **R1** | Required as the skills fallback when a listing lists no skills, which is common |
| MATCH-05 | Incremental rescore on new jobs and profile change | M | **R1** | Full rescore is affordable at beta scale but the debounce and candidate-set gate are the design; building them later means building them under load |
| MATCH-06 | User feedback on scores, bounded per-user weight offsets | S | R2 | Needs feedback data to be worth anything. R1 stores `user_job_actions` (JOB-09), which is the same signal in cheaper form |
| MATCH-07 | User-set minimum score threshold | M | **R1** | The only precision control in R1 |
| MATCH-08 | Gap analysis view | S | R3 | P3's headline feature. Deserves proper design, not a corner of R2 |

### 2.7 Application Assistance

| ID | Requirement | BRD pri | Track | Reason |
|---|---|---|---|---|
| APPLY-01 | Answer Bank with canonical question taxonomy | M | **R1** | Half the time saved in the loop |
| APPLY-02 | Pack generation: summary, cover letter, answers, resume suggestions | M | **R1** | — |
| APPLY-03 | Every item editable; `draft → approved`; only approved usable | M | **R1** | HR-1's mechanism |
| APPLY-04 | Anti-fabrication check | M | **R1** | HR-4. The single highest-consequence feature in the product — a fabricated claim in a cover letter is a fired user |
| APPLY-05 | Assisted apply: open posting, copy panel, confirm applied | M | **R1** | — |
| APPLY-06 | Browser extension, per-page approval, never submits | C | R3 | Separate artifact, separate store review, separate threat model |
| APPLY-07 | Immutable audit log of artifacts and approvals | M | **R1** | Append-only from day one or the record has a hole |
| APPLY-08 | Tailored ATS resume PDF export | S | R3 | A document-generation project wearing a feature's clothes |

### 2.8 Tracker

| ID | Requirement | BRD pri | Track | Reason |
|---|---|---|---|---|
| TRACK-01 | Application entity + full status state machine | M | **R1** | The transition table is cheap; a partial machine means a data migration when the rest arrives |
| TRACK-02a | Kanban + list views | M | **R1** | — |
| TRACK-02b | Calendar view of interviews and deadlines | M | R2 | A third rendering of data the list already shows |
| TRACK-03 | Notes, contacts, documents, interview rounds, salary log | M | **R1** | This is why someone returns daily |
| TRACK-04 | Event timeline | M | **R1** | Built from `status_history` and `audit_log`, both of which must be written from the start |
| TRACK-05 | Manual application entry | M | **R1** | Coverage from three connectors is thin; without manual entry the tracker is partial and therefore abandoned |
| TRACK-06 | Ghosted suggestion after 30 days of no change | S | R2 | Needs 30 days of data before it can fire |
| TRACK-07 | Stats: rate, conversion, time in stage | S | R2 | Same reason |

### 2.9 Notifications

| ID | Requirement | BRD pri | Track | Reason |
|---|---|---|---|---|
| NOTIF-01 | Follow-up, interview, deadline, custom reminders | M | **R1** | Final clause of the exit sentence |
| NOTIF-02a | In-app inbox + email | M | **R1** | Two channels are enough to prove delivery |
| NOTIF-02b | Mobile push via FCM | M | R2 | Firebase setup, per-flavor configs, token lifecycle, store permission copy. Email covers the reminder in R1; the in-app inbox covers it on the phone |
| NOTIF-02c | Web push (VAPID) | S | R3 | Lowest-value channel |
| NOTIF-03 | Quiet hours per timezone | S | R2 | Only matters once push exists |
| NOTIF-04 | Weekly digest of new matches | S | R2 | P2's feature; ships with saved searches |
| NOTIF-05 | Idempotent, logged delivery | M | **R1** | A worker restart must not send a reminder twice; that is a design property |

### 2.10 Operator Admin

| ID | Requirement | BRD pri | Track | Reason |
|---|---|---|---|---|
| ADMIN-01 | Connector dashboard: runs, counts, errors, circuit state, toggle | M | **R1** | You cannot operate three connectors from a Mongo shell |
| ADMIN-02 | AI usage dashboard: requests, tokens, cost by provider/model/feature | M | **R1** | The Google-AI-Pro isolation is only credible if you can see the bill forming (`README.md` §1 Call 2) |
| ADMIN-03 | Feature flags, env + DB override | M | **R1** | The mechanism the R1/R2 split relies on |
| ADMIN-04 | Skill alias management UI | S | R2 | R1 edits the seed file and redeploys |
| ADMIN-05 | Flagged listings queue | S | R2 | Ships with JOB-10 |
| ADMIN-06 | Operator role gating, separate prefix | M | **R1** | Access control is not a later feature |

### 2.11 Cross-cutting requirement families — **added in v2.1**

BRD v1.0 §5 numbered only the ten product families. The specification also defines eight cross-cutting families, which v2.0 left out of this table — so nothing could depend on them in a checkable way. They are listed here because `dependencies.yaml` requires every referenced requirement to have a track and a phase.

| Family | IDs | File | Track | Phase |
|---|---|---|---|---|
| `FOUND` | `FOUND-01` … `FOUND-14` | `01-foundations.md` | **R1** | P0 |
| `FOUND` | `FOUND-15` status registry, `FOUND-16` email transport | `01-foundations.md` §15–16 | **R1** | P0 |
| `DATA` | `DATA-01` … `DATA-07` | `17-data-model.md` | **R1** | P0 |
| `AI` | `AI-01` … `AI-07` | `05-ai-layer.md` | **R1** | P0 |
| `DEP` | `DEP-01` … `DEP-06` | `18-dependency-closure.md` | **R1** | P0 |
| `WEB` | `WEB-01` … `WEB-08` | `13-web-client.md` | **R1** (`WEB-07` R2) | P0–P7 |
| `MOB` | `MOB-01` … `MOB-08` | `14-mobile-client.md` | **R1** (`MOB-07` R2) | P0–P7 |
| `OPS` | `OPS-01` … `OPS-08` | `15-infra-and-ops.md` | **R1** (`OPS-07` R2) | P0, P7 |
| `SEC` | `SEC-01` … `SEC-06` | `16-security-and-compliance.md` | **R1** | P0–P5 |

`MATCH-09` (the feed sufficiency invariant, `08-matching.md` §8) is likewise new in v2.1, tracked **R1**, phase P4.

### 2.12 Cross-cutting items not in BRD §5

| Item | Track | Reason |
|---|---|---|
| Android release build, Play internal testing | **R1** | The exit sentence says "on Android" |
| iOS build and release | R3 | Needs a Mac and a $99/yr account (D8). Android first |
| Offline read-only cache (mobile) | R2 | Polish |
| Device calendar integration | R3 | Polish |
| WCAG 2.1 AA audit pass | R2 | R1 builds to the semantic conventions in `13-web-client.md` §7; the audit and remediation are R2 |
| Load test (k6, 200 concurrent) | R2 | Meaningless before the feed query is final |
| Backup restore drill | R2 | The backup itself is R1 |
| Runbooks | R2 | Written from incidents that have actually happened |
| Field-level encryption of phone + document metadata | R2 | — |
| ClamAV upload scanning | R2 | Uploads are user-owned and never served to other users in R1 |
| `schemathesis` API fuzzing | R2 | — |
| Product analytics (PostHog) | R3 | D9 |
| Learned ranker, weights `w2` | R3 | Needs outcome data |
| Billing / subscriptions | out | Non-goal; design does not preclude it |

---

## 3. Gates

A gate is a list of statements that must each be demonstrably true. No partial credit, no "mostly".

### 3.1 R1 gate

1. The R1 exit sentence (§1.2) passes as a scripted end-to-end run on staging: Playwright for web (`T-WEB-E2E.1`), `integration_test` on a physical Android device for mobile (`T-MOB-E2E.1`).
2. Every requirement marked **R1** in §2 has all of its acceptance criteria green in CI.
3. `import-linter` passes with the full contract set from `01-foundations.md` §4. Zero exemptions.
4. Hard rules HR-1 through HR-12 each have a passing enforcement test (`README.md` §2, right-hand column).
5. Staging holds ≥5,000 active, deduplicated jobs from ≥3 connectors, and the ratio of merged duplicates to total is recorded in `connector_runs`.
5a. **`INV-FEED-1` holds** (`08-matching.md` §8.2): the committed reference profile against that corpus yields ≥50 eligible jobs at the default threshold, 25 on the first page, 50 within two pages, each with a complete explain payload. **`INV-FEED-2`** scoring coverage is ≥99% for active users.
5b. **Closure is green** (`18-dependency-closure.md`): track closure has no violations, phase closure has no violations, the manifest is acyclic, and `BUILD-ORDER.md` matches the committed copy.
5c. **The field and enum registries are green** (`17-data-model.md` §7): every `collection.field` reference resolves and every enum member is registered.
6. Feed p95 <800 ms and non-AI CRUD p95 <500 ms, measured on staging with 5,000 jobs and 20 seeded users.
7. `AI_DAILY_COST_CAP_USD` is set, the cap has been deliberately tripped in staging, and every AI feature degraded rather than errored (`T-AI-03.4`).
8. A deletion request completes: soft-delete immediate, hard-delete after 7 days including every R2 object under the user prefix, verified by listing the prefix (`T-AUTH-07.4`).
9. Nightly `mongodump` to R2 has run for seven consecutive nights and the most recent dump restores into a scratch database (`T-OPS-06.1`).
10. ADR-001 … ADR-010 exist in `docs/adr/`, one paragraph minimum each.
11. **Implementation status matches the registry** (`01-foundations.md` §15). Every section declares one of `built` / `built-off` / `stub-501` / `absent`; the declaration is verified against the flag defaults, the OpenAPI surface, and the test suite; every R1 section is `built` except `MATCH-02b`, which is `built-off` and passes its criteria with the flag forced on; every `absent` section has no route, no flag, no module file and no skipped test; and no `TODO`, `FIXME`, `NotImplementedError`, skipped test or commented-out block exists on an R1 path.

### 3.2 R2 gate

1. Every requirement marked **R2** in §2 is green, or explicitly deferred to R3 in writing with a reason recorded in this file.
2. Security review against `16-security-and-compliance.md` §2 completed, every control either implemented or accepted in writing with a compensating control named.
3. Consent copy reviewed against the *current* terms of every AI provider and every connector; `docs/compliance/ai-providers.md` and each connector's `COMPLIANCE.md` reviewed within the last 30 days.
4. D5 settled: Gemini paid tier active before any public sign-up, or the free-tier data-use position explicitly disclosed in the consent screen and accepted by you in writing.
5. Load test at 200 concurrent users passes the §3.1(6) latency budget.
6. Restore drill executed from a backup you did not create by hand, timed, and the time written into a runbook.
7. Runbooks exist for: connector failing, AI cap exceeded, restore from backup, rotate JWT keys, verify a deletion, add a company board.
8. Alerting fires and reaches you: connector circuit open, AI cap hit, queue depth >1,000 for 10 min, error rate >2%.
9. WCAG 2.1 AA audit on web complete, blocking issues fixed.
10. Nine connectors live, each with a compliance record reviewed in the last 180 days.
11. Anything half-built is behind a flag that is off, or removed.

### 3.3 Track discipline rule

A feature may be pulled **forward** into R1 only by moving something else out, and only by editing §2 of this file with the reason. A feature may be pushed **back** freely. This is the only mechanism that protects the R1 date, and the failure mode it exists to prevent — a solo build that is 80% done in nine directions — is the top-listed risk in BRD v1.0 §24.

---

## 4. Phase order inside R1

Each phase ends deployable to staging. Estimates assume 15–20 focused hours/week and are for sequencing, not for promising.

| Phase | Name | Delivers | Exit gate | Est. |
|---|---|---|---|---|
| **P0** | Infrastructure proving | Monorepo, both entrypoints in one image, Compose stack, ARQ ping + heartbeat cron, R2 upload/presign, one Gemini call behind the protocol + fake provider, both clients hitting `/healthz`, four CI workflows, staging auto-deploy, Sentry + structlog + `/metrics`. **v2.1 additions:** `FOUND-16` email transport with the R1 template set (needed by P1, `18-dependency-closure.md` §5.1); the `DATA-06` embedding quantization codec in `shared/` (needed by P2, §5.2); `dependencies.yaml` + the closure checks; `FOUND-15` status registry | A commit on `develop` reaches staging unattended and both clients render live health from it; `lint-imports`, the closure checks and the traceability gate are green on an otherwise empty repo | 1 wk |
| **P1** | Identity & account | AUTH-01…05, 07, 09, 10; consent capture; web + mobile auth flows; account settings; operator role; verification and reset messages **through `FOUND-16`**, not a client of its own | Sign up → verify → login → refresh → logout on both clients; a deletion request runs to completion in an accelerated-clock test | 2 wk |
| **P2** | Candidate intelligence | RES-01, 02a, 03, 05, 06; PROF-01, 02, 03, 06; skill alias seed (~600 entries); onboarding wizard on web; upload + review + preferences on mobile | Exit-sentence clauses 1–5; extraction golden tests pass on 10 real resumes with ≥90% field-level precision on skills and employers | 3 wk |
| **P3** | Job engine | CONN-01…05, 06a, 07; JOB-01…06, 08, 09; ADMIN-01 | ≥5,000 deduplicated jobs from 3 sources in staging; a fixture-backed dummy connector goes from `touch` to visible in the dashboard in under one hour, timed | 3 wk |
| **P4** | Matching | MATCH-01, 02a, 02b (built-off), 03, 04, 05, 07, **09**; ADMIN-02, 03; feed + job detail on both clients, including the four `feed_state` renderings | `INV-FEED-1` holds on the reference fixtures (`08-matching.md` §8.2); `INV-FEED-2` scoring coverage ≥99%; scoring suite green; feed p95 <800 ms | 3 wk |
| **P5** | Application engine | APPLY-01…05, 07; `applications` collection with `saved/preparing/applied` only; answer bank UI; pack editor; apply panel and mobile sheet | Exit-sentence clauses "generates a pack, edits, approves, opens, confirms"; every pack claim either traceable or explicitly overridden | 3 wk |
| **P6** | Tracker & reminders | TRACK-01, 02a, 03, 04, 05; NOTIF-01, 02a, 05; **APPLY-09** (the follow-up draft, moved from P5 — it reads interview history, and it is the action a reminder prompts) | Final clause of the exit sentence; reminder idempotency verified across a worker kill during dispatch | 3 wk |
| **P7** | R1 closeout | Android release build, Play internal testing, R1 gate items 3–11, ADRs, `.env.example` parity | R1 gate (§3.1) fully green; `v1.0.0` tag | 2 wk |

**Why `applications` appears in P5 and not P6:** a pack has to hang off something. P5 creates the collection with three statuses and the audit log; P6 adds the rest of the state machine and the reminder scheduler. `10-tracker.md` marks which fields belong to which phase.

**Why matching precedes apply:** the pack prompt consumes the match explain payload (missing skills become the "address the gap" instruction). Building apply first means building it twice.

## 4.1 Phase order inside R2

Unlike R1, R2 phases are independent and can be reordered by whatever hurts most.

| Phase | Name | Delivers |
|---|---|---|
| **S1** | Hardening | `16-security-and-compliance.md` §2 review, rate-limit tuning, field-level encryption, ClamAV, `schemathesis`, load test, dependency sweep |
| **S2** | Connector expansion | CONN-06b (six connectors), JOB-07, JOB-10, ADMIN-04, ADMIN-05 |
| **S3** | Trust & control | AUTH-06, AUTH-08, PROF-05, PROF-07, RES-02b, RES-04, RES-07, MATCH-02b on, MATCH-06 |
| **S4** | Reach | NOTIF-02b, NOTIF-03, NOTIF-04, TRACK-02b, TRACK-06, TRACK-07, mobile offline cache |
| **S5** | Operability | Restore drill, runbooks, alerting, accessibility audit, D5 resolution |

---

## 5. Open decisions

Carried from BRD v1.0 §25, re-dated against the phase plan. Each has a default so no phase blocks on an unanswered question — the default takes effect if the decision is unmade when the phase starts.

| # | Decision | Needed by | Default if unanswered | Notes |
|---|---|---|---|---|
| **D1** | Product name + domain | P1 (email templates, consent copy) | Ship with `PRODUCT_NAME=JobPilot` in staging only; production deploy blocked until set | `README.md` §5 keeps the name out of code |
| **D2** | Atlas region | P0 | Mumbai `ap-south-1` | India-first (A3); moving a cluster region later is a migration |
| **D3** | Container host: PaaS vs VPS | P0 | Single small VPS (Hetzner/DO, ~₹400–600/mo) with Compose + Caddy behind Cloudflare | Compose file is the source of truth either way, so this is reversible |
| **D4** | Queue: Redis+ARQ vs alternative | P0 | Redis + ARQ | Settled by ADR-003; listed so it is not reopened |
| **D5** | Gemini free vs paid tier before public sign-up | **R2 gate**, item 4 | Paid tier, and disclose the provider in consent regardless | Free-tier prompt-data terms are the reason; see `05-ai-layer.md` §5.4 |
| **D6** | Confirm the R2 connector set | S2 | As listed in §2.5 CONN-06b, plus any company boards you personally target via `greenhouse_board`/`lever_postings` | — |
| **D7** | Email provider | P1 | Resend | Behind `EmailSender`; SES swap is one adapter |
| **D8** | iOS at launch | R3 | No | Needs a Mac; Codemagic or a macOS runner later |
| **D9** | Product analytics | R3 | None | Do not add a second data collector before the first has users |
| **D10** | Whether the R1 beta is invite-only | P7 | Invite-only, hard cap 50 accounts, enforced by a signup allowlist | *New.* The AI daily cap and Atlas M0's 512 MB are the real constraints; an open beta can exhaust either overnight |

---

## 6. Traceability

`README.md` §3 maps files to requirement families. §2 of this file maps every requirement to a track. Each module file maps every requirement to acceptance criteria and tests. The chain is:

```
requirement ID  →  track (this file §2)
                →  module file section (README §3)
                →  AC-<REQ>.<n>  (module file)
                →  T-<REQ>.<n>   (module file, names a real test path)
```

CI enforces the last link: `T-FOUND-06.1` parses every module file, extracts every `AC-` and `T-` identifier, and fails if an `AC-` has no matching `T-`, if a `T-` names a test path that does not exist, or if a requirement marked R1 in this file has no acceptance criteria anywhere. Specified in `01-foundations.md` §6.
