# 10 — Application Tracker

**Module:** `apps/api/app/modules/tracker`
**Track:** R1 except §3.1 (`TRACK-02b`, R2), §6 (`TRACK-06`, R2), §7 (`TRACK-07`, R2)
**Depends on:** `07-ingestion-and-jobs.md`, `09-apply.md`, `17-data-model.md` §2.10
**Requirements:** `TRACK-01` … `TRACK-07`
**Public API:** `TrackerService.create`, `.list`, `.get`, `.transition`, `.patch`, `.add_interview`, `.add_document`, `.timeline`, `.stats`
**Publishes:** `ApplicationStatusChanged`. **Consumes:** `AppliedConfirmed`, `PackApproved`, `JobExpired`.

The tracker is why someone opens the product on a Tuesday when they are not applying to anything. If it is not complete and trustworthy, they keep using a spreadsheet and the rest of the product loses its point.

**Phase note.** `00-scope-and-phases.md` §4: the `applications` collection is created in **P5** with `saved`, `preparing`, `applied` only, because a pack needs something to hang from. P6 adds the remaining statuses, the views, and everything below. Fields are marked `[P5]` or `[P6]` where it matters.

---

## 1. The application entity — `TRACK-01`, `TRACK-05`

**Objective.** One record per thing the user is pursuing, whether or not it came from our feed.

**Constraints.**
- Shape in `17-data-model.md` §2.10. **Exactly one of `job_id` and `manual_job`** is set, enforced at write time and by a collection validator (`AC-DATA-02.3`).
- Manual entry (`TRACK-05`) takes either a URL or free text. Given a URL, the product attempts a **light** enrichment: fetch the page title and, if the host matches a known board pattern, the company — with a 5-second timeout, an SSRF guard identical to `rss_generic` (`16-security-and-compliance.md` §2), no HTML parsing beyond `<title>`, and silent failure to plain free text. It does not scrape the posting (HR-2), and a failed enrichment is a non-event.
- Creating an application from a job is idempotent per `(user_id, job_id)` — the unique partial index means "save" twice yields one row.
- `source ∈ {match, search, manual}` is recorded at creation and never changed, so the question "did matching actually drive applications" is answerable later.
- `last_activity_at` updates on any user action or status change; `next_action_at` is set by the reminder scheduler (`11-notifications.md` §2) and is what the tracker sorts "needs attention" by.
- `listing_expired` is a **flag, not a status**: an expired listing does not move a card on the board. Set by the `JobExpired` handler.
- Deleting an application is a soft delete and is available to the user; it never deletes the underlying job or the audit rows.

**Inputs.** `POST /applications` with `job_id` or `manual_job`; `AppliedConfirmed`.

**Outputs.** `applications` document; `ApplicationStatusChanged` on creation (`null → saved`).

**Acceptance criteria.**
- `AC-TRACK-01.1` Creating with both `job_id` and `manual_job` is rejected `422`; with neither, rejected `422`.
- `AC-TRACK-01.2` Saving the same job twice returns the same application id and creates one row.
- `AC-TRACK-01.3` Manual entry from a URL populates title and company when the host is a known pattern, and falls back to free text on timeout, on a non-matching host, or on any parse failure — in every case creating the application.
- `AC-TRACK-01.4` A manual URL resolving to a private IP range is refused enrichment (no request made) and the application is still created from the URL as text.
- `AC-TRACK-01.5` `source` is set correctly for all three entry paths and is immutable thereafter.
- `AC-TRACK-01.6` `JobExpired` sets `listing_expired: true` without changing `status`.
- `AC-TRACK-01.7` A soft-deleted application disappears from all views and leaves its `audit_log` rows intact.
- `AC-TRACK-01.8` No HTML parser is used in the enrichment path (only a `<title>` regex over a capped byte range).

**Tests.**
- `T-TRACK-01.1` `tests/integration/test_application_job_xor.py` (shared).
- `T-TRACK-01.2` `tests/integration/test_save_idempotence.py`.
- `T-TRACK-01.3` `tests/integration/test_manual_entry.py`.
- `T-TRACK-01.4` `tests/integration/test_manual_url_ssrf.py`.
- `T-TRACK-01.5` `tests/integration/test_application_source.py`.
- `T-TRACK-01.6` `tests/integration/test_expired_flag.py`.
- `T-TRACK-01.7` `tests/integration/test_application_soft_delete.py`.
- `T-TRACK-01.8` `tests/spec/test_no_scraping_deps.py` (shared).

**Manual entry, stated against its own requirement.**
- `AC-TRACK-05.1` An application can be created from a URL alone and from free text alone, and both are fully usable in every view and in the timeline (`AC-TRACK-01.3` shared).
- `AC-TRACK-05.2` A manually entered application supports packs only when enough is known to build a prompt (a title and a company); otherwise the pack action is unavailable with a stated reason rather than failing.
- `AC-TRACK-05.3` A manual application receives reminders identically to one created from a job.
- `T-TRACK-05.1`–`.3` `tests/integration/test_manual_entry.py` (shared), `tests/integration/test_manual_pack_gate.py`, `tests/integration/test_manual_reminders.py`.

---

## 2. The status state machine — `TRACK-01`

**Objective.** A status graph the user cannot corrupt and the code cannot bypass.

**Constraints.**

```
saved ──► preparing ──► applied ──► screening ──► interview ──► offer ──► accepted
   │          │            │            │             │            │
   └──────────┴────────────┴────────────┴─────────────┴────────────┴──► rejected | withdrawn
                            └────────────┴─────────────┴───────────────► ghosted
```

- The transition table lives in `tracker/state.py` as a pure data structure: `ALLOWED: dict[Status, set[Status]]`. Every transition in the product goes through `transition(app, to, by, reason)`; no code path assigns `status` directly, and a static check enforces that.
- **Forward moves are free.** Skipping stages is allowed — a user who goes straight from `saved` to `interview` because a recruiter called is describing reality, and a machine telling them that is impossible is the machine being wrong.
- **Backward moves are allowed but require a reason**, recorded in `status_history`. People fix mistakes.
- Terminal states are `accepted`, `rejected`, `withdrawn`, `ghosted`. They can be reopened to `screening` or `interview` with an explicit confirmation, because rejections get reversed and ghosts reply.
- An invalid transition raises `InvalidTransition` → `422` with the allowed set in `details`, so a client can render what is possible rather than guessing.
- Every transition appends to `status_history` with `{from, to, at, by ∈ {user, system}, reason}` and publishes `ApplicationStatusChanged`, which the notifications module consumes to reconcile reminders (`01-foundations.md` §9).
- Transitions the **system** may make, exhaustively — and no others: `preparing → applied` on `AppliedConfirmed`; `saved → preparing` on first pack generation. The system never moves an application to `ghosted`, `rejected`, or any terminal state. `TRACK-06` only *suggests* (§6).
- `applied_at` is set once, on the first entry to `applied`, and never overwritten by a later re-entry.

**Inputs.** `POST /applications/{id}/status`.

**Outputs.** `status`, `status_history`; `ApplicationStatusChanged`.

**Acceptance criteria.**
- `AC-TRACK-01.9` The full transition matrix is tested: every (from, to) pair is asserted allowed or rejected against the table, including all reopenings.
- `AC-TRACK-01.10` A forward skip (`saved → interview`) succeeds; a backward move without a reason is rejected `422`; with a reason it succeeds and records it.
- `AC-TRACK-01.11` `InvalidTransition` returns 422 with the allowed set in `details`.
- `AC-TRACK-01.12` No code outside `state.py` assigns `status` (static check).
- `AC-TRACK-01.13` The system performs only the two permitted transitions; a test asserts no system-initiated transition to a terminal state exists anywhere in the codebase.
- `AC-TRACK-01.14` `applied_at` is unchanged by a second entry into `applied`.
- `AC-TRACK-01.15` Every transition publishes exactly one event and appends exactly one history entry.

**Tests.**
- `T-TRACK-01.9`/`.10`/`.11` `tests/unit/test_state_machine.py`, `tests/integration/test_transitions.py`.
- `T-TRACK-01.12` `tests/spec/test_no_direct_status_assignment.py`.
- `T-TRACK-01.13` `tests/spec/test_system_transitions.py`.
- `T-TRACK-01.14` `tests/integration/test_applied_at_stability.py`.
- `T-TRACK-01.15` `tests/integration/test_event_wiring.py` (shared).

---

## 3. Views — `TRACK-02`

**Objective.** Two renderings of the same list, both fast, both honest about what needs attention.

**Constraints.**
- **Kanban** (`GET /applications?group_by=status`): one column per status in graph order, each column cursor-paginated independently with its own count, capped at 50 loaded per column with "load more". A board that loads 400 cards is slow on a phone and useless on a desktop.
- **List** (`GET /applications`): filterable by status, `source`, company, date range, `listing_expired`, and `needs_attention` (a derived flag: `next_action_at` in the past, or an unresolved `needs_user` on the current pack, or `listing_expired` with a non-terminal status). Sortable by `last_activity_at`, `next_action_at`, `applied_at`, company.
- Both read from the `(user_id, status, last_activity_at desc)` index (`17-data-model.md` §3).
- Card payload is a projection: title, company, status, score band if the job is scored, `next_action_at`, `listing_expired`, interview count, and the attribution string. Never the description, never the pack.
- Optimistic status changes on both clients: the card moves immediately and reverts with a message on failure. A drag that waits 400 ms for a round trip feels broken.
- Empty states are specified, not left to the implementer: a new user with no applications sees a prompt pointing at the matches feed; a filtered view with no results says which filter to clear.

### 3.1 Calendar view — `TRACK-02b` — **Track: R2**

Month and week views of `interviews[].at` and `apply_deadline`, with a list fallback. Reads the same data; no new fields.

**Inputs.** Query parameters.

**Outputs.** `Page[ApplicationCard]` per column, or one page for the list.

**Acceptance criteria.**
- `AC-TRACK-02.1` The Kanban returns each column independently paginated with its own total, and one column's cursor does not affect another's.
- `AC-TRACK-02.2` `needs_attention` is true for each of its three conditions and false otherwise, tested per condition.
- `AC-TRACK-02.3` Every filter and every sort works and combines; a fixture matrix covers each.
- `AC-TRACK-02.4` The card projection contains no description and no pack content.
- `AC-TRACK-02.5` An optimistic move that fails server-side reverts the card and surfaces the reason (component tests, both clients).
- `AC-TRACK-02.6` Board load p95 < 500 ms for a user with 300 applications.
- `AC-TRACK-02.7` Both specified empty states render.

**Tests.**
- `T-TRACK-02.1` `tests/integration/test_kanban_pagination.py`.
- `T-TRACK-02.2` `tests/unit/test_needs_attention.py`.
- `T-TRACK-02.3` `tests/integration/test_application_filters.py`.
- `T-TRACK-02.4` `tests/contract/test_card_projection.py`.
- `T-TRACK-02.5` `apps/web/.../kanban.test.tsx`, `apps/mobile/test/tracker_card_test.dart`.
- `T-TRACK-02.6` `tests/integration/test_tracker_latency.py` (nightly).
- `T-TRACK-02.7` `apps/web/.../empty-states.test.tsx`.

---

## 4. Application detail: notes, contacts, documents, interviews, salary — `TRACK-03`

**Objective.** Everything about one pursuit in one place, including the things a spreadsheet cannot hold.

**Constraints.**
- **Notes** are markdown, capped at 32 KB, rendered with a **scheme allowlist** — an unrecognised URL scheme degrades to plain text, so `javascript:` and `data:` hrefs cannot become live links. This is the user's own content, but the renderer is shared and must be safe regardless.
- **Contacts**: name, role, email, phone, notes. Capped at 20. Email and phone are validated in shape only, never verified. Contacts are personal data about **third parties** — they are included in export, purged with the account, and never sent to an AI provider (the follow-up draft receives only names and roles, never contact details).
- **Documents**: uploaded to `u/{user_id}/applications/{application_id}/{document_id}.{ext}` (`17-data-model.md` §4). Same validation as resumes (magic bytes, 5 MB, allowlisted types plus PNG/JPEG for offer-letter screenshots). Capped at 10 per application. `kind ∈ {resume, cover, offer, screenshot, other}`. Presigned download, 5-minute TTL, ownership-checked.
- **Interviews**: `{id, round, type, at, duration_min, location, notes, outcome}`. `type ∈ {screening, technical, system_design, behavioural, hr, take_home, panel, final, other}`; `outcome ∈ {pending, passed, failed, cancelled, no_show}`. Adding or changing `at` reconciles reminders (`11-notifications.md` §2). Rounds need not be contiguous — a user who logs round 3 without round 2 is not corrected.
- **Salary log**: append-only entries `{at, kind, money, note}` with `kind ∈ {expectation_given, offer_received, counter_made, revised_offer, accepted}`. Append-only because a negotiation history that can be edited is not a history. Uses `Money` (`01-foundations.md` §3) — minor units, never floats.
- All of these update `last_activity_at`.

**Inputs.** `PATCH /applications/{id}`, and the sub-resource endpoints.

**Outputs.** The updated document; timeline entries.

**Acceptance criteria.**
- `AC-TRACK-03.1` A note containing a `javascript:` link, a `data:` image, and raw HTML renders with none of them live, in both clients.
- `AC-TRACK-03.2` Every cap is enforced with a `422` naming the limit.
- `AC-TRACK-03.3` Contact email and phone never appear in any AI request (outbound capture over the follow-up draft path).
- `AC-TRACK-03.4` Document upload rejects a mismatched magic-byte file and an oversized file; a presigned URL is never issued cross-user.
- `AC-TRACK-03.5` Adding an interview schedules the 24-hour and 1-hour reminders; changing `at` cancels the old ones and schedules new ones with different dedup keys.
- `AC-TRACK-03.6` A non-contiguous round number is accepted.
- `AC-TRACK-03.7` A salary-log entry cannot be edited or deleted through any endpoint.
- `AC-TRACK-03.8` Money round-trips through the API with no floating-point drift across 1,000 hypothesis-generated values.
- `AC-TRACK-03.9` Every sub-resource mutation updates `last_activity_at`.

**Tests.**
- `T-TRACK-03.1` `tests/unit/test_markdown_renderer.py`, `apps/web/.../notes.test.tsx`, `apps/mobile/test/notes_test.dart`.
- `T-TRACK-03.2` `tests/integration/test_detail_caps.py`.
- `T-TRACK-03.3` `tests/integration/test_no_contacts_to_provider.py`.
- `T-TRACK-03.4` `tests/integration/test_application_documents.py`.
- `T-TRACK-03.5` `tests/integration/test_interview_reminders.py`.
- `T-TRACK-03.6` `tests/unit/test_interview_rounds.py`.
- `T-TRACK-03.7` `tests/integration/test_salary_log_append_only.py`.
- `T-TRACK-03.8` `tests/unit/test_money.py` (shared).
- `T-TRACK-03.9` `tests/integration/test_last_activity.py`.

---

## 5. Timeline — `TRACK-04`

**Objective.** One chronological answer to "what has happened with this application".

**Constraints.**
- Composed at read time from four sources: `status_history`, `audit_log` rows for this application (`09-apply.md` §6), `reminders` that were sent, and `interviews` (added, rescheduled, outcome recorded). Nothing is duplicated into a fifth store — a timeline collection would be a second copy that drifts.
- Each entry: `{at, kind, actor ∈ {user, system}, title, detail, ref}`. Sorted by `at`, ties broken by kind precedence so a status change and its triggered reminder read in causal order.
- Every entry is derived from a durable record. The timeline never says something happened unless a stored row says so.
- Cursor-paginated, newest first, 50 per page.
- An entry whose referenced object is gone (a purged reminder, a deleted document) still renders with its recorded title and a note that the detail is no longer available, rather than vanishing — a timeline with holes is worse than one with tombstones.

**Inputs.** The four sources.

**Outputs.** `Page[TimelineEntry]`.

**Acceptance criteria.**
- `AC-TRACK-04.1` A seeded journey (save → pack → approve → apply → reminder sent → screening → interview added → interview outcome → offer) produces exactly the expected entries in the expected order.
- `AC-TRACK-04.2` No timeline entry exists without a backing stored row (asserted by removing a row and re-reading).
- `AC-TRACK-04.3` A status change and the reminder it caused, sharing a timestamp, render in causal order.
- `AC-TRACK-04.4` An entry referencing a purged object renders with a tombstone rather than disappearing.
- `AC-TRACK-04.5` There is no `timeline` collection (composition is at read time).

**Tests.**
- `T-TRACK-04.1` `tests/integration/test_timeline_journey.py`.
- `T-TRACK-04.2` `tests/integration/test_timeline_backing.py`.
- `T-TRACK-04.3` `tests/unit/test_timeline_ordering.py`.
- `T-TRACK-04.4` `tests/integration/test_timeline_tombstones.py`.
- `T-TRACK-04.5` `tests/spec/test_collection_ownership.py` (shared).

---

## 6. Ghosted suggestion — `TRACK-06` — **Track: R2**

**Objective.** Clear the board of dead applications without ever deciding for the user.

**Constraints.** A nightly job flags applications with no status change and no activity for 30 days in `applied` or `screening`, surfacing a dismissible suggestion in the tracker and in the weekly digest: "these 6 look ghosted — mark them?" with a bulk action. **The system never sets `ghosted`** (`AC-TRACK-01.13`). Dismissing a suggestion suppresses it for 30 more days. The threshold is per-user configurable, 14–90 days.

**Acceptance criteria.** `AC-TRACK-06.1` No automatic transition occurs, ever. `AC-TRACK-06.2` The suggestion appears at the threshold and not before. `AC-TRACK-06.3` Dismissal suppresses for 30 days. `AC-TRACK-06.4` The bulk action transitions only the selected applications, each with `by: user`.
**Tests.** `T-TRACK-06.1`–`.4` `tests/integration/test_ghosted_suggestion.py`.

---

## 7. Statistics — `TRACK-07` — **Track: R2**

**Objective.** Show the user their own funnel, without flattering it.

**Constraints.** Computed on read from `status_history` (no aggregates stored, at this scale): applications per week, response rate (reached `screening` or beyond ÷ `applied`), interview conversion, offer rate, median time in each stage, and a breakdown by `source` — which is the number that tells you whether the matching engine is earning its keep. Every figure states its denominator and is **suppressed below 10 data points** with "not enough applications yet" rather than shown as a meaningless percentage. Time-in-stage uses only completed transitions; applications still in a stage are excluded and the count of excluded ones is shown.

**Acceptance criteria.** `AC-TRACK-07.1` Every metric matches a hand-computed expectation on a seeded history. `AC-TRACK-07.2` Fewer than 10 data points suppresses the figure. `AC-TRACK-07.3` Denominators are stated. `AC-TRACK-07.4` The `source` breakdown separates `match`, `search`, and `manual`. `AC-TRACK-07.5` In-progress applications are excluded from time-in-stage and counted separately.
**Tests.** `T-TRACK-07.1`–`.5` `tests/unit/test_stats.py`, `tests/integration/test_stats_endpoint.py`.
