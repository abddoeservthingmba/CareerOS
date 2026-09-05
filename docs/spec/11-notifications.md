# 11 — Reminders & Notifications

**Module:** `apps/api/app/modules/notifications`
**Track:** R1 except §4.2 (`NOTIF-02b`, R2), §4.3 (`NOTIF-02c`, R3), §5 (`NOTIF-03`/`NOTIF-04`, R2)
**Depends on:** `10-tracker.md`, `01-foundations.md` §3 (time), §10 (tasks), `17-data-model.md` §2.11
**Requirements:** `NOTIF-01` … `NOTIF-05`
**Public API:** `NotificationService.send`, `ReminderService.schedule`, `.reconcile`, `.cancel`, `.list`
**Publishes:** none. **Consumes:** `AppliedConfirmed`, `ApplicationStatusChanged`.

The last clause of the R1 exit sentence lives here. Two properties matter: a reminder fires **once** even across a worker restart (`NOTIF-05`), and it fires at a time that makes sense **in the user's own day** (HR-10).

---

## 1. Reminder types — `NOTIF-01`

**Objective.** Four reminders that cover the actual reasons an application dies.

**Constraints.**

| Type | Trigger | Default timing | Cancelled when |
|---|---|---|---|
| `follow_up` | entry to `applied` | `applied_at` + 7 days, at 10:00 local | status moves beyond `applied`, or the application is withdrawn or deleted |
| `interview_24h` | interview added or `at` changed | 24 h before `interviews[].at` | interview removed, rescheduled (replaced), outcome recorded, or `at` in the past |
| `interview_1h` | same | 1 h before | same |
| `deadline_48h` | application saved for a job with `apply_deadline` | 48 h before the deadline | status reaches `applied`, or the job expires |
| `custom` | user | user-specified | user cancels, or the application is deleted |

- Follow-up delay is per-user configurable, 3–30 days, default 7.
- A reminder whose computed `due_at` is already in the past is **not** scheduled and not sent — a user who logs an interview an hour before it starts should not receive a 24-hour reminder. The skip is recorded so the absence is explicable.
- `payload` denormalizes the job title and company (`17-data-model.md` §2.11) so dispatch does not join for a batch of 200, and so a reminder about a purged job still renders.
- Only one live reminder per `(application, type, occurrence)` — enforced by `dedup_key` (§3).
- No reminder is created for an application in a terminal status.

**Inputs.** Tracker events; user settings; interview times.

**Outputs.** `reminders` rows.

**Acceptance criteria.**
- `AC-NOTIF-01.1` Each of the five types is scheduled by its trigger with the correct `due_at`, verified with a frozen clock.
- `AC-NOTIF-01.2` A follow-up delay changed to 14 days applies to newly scheduled reminders and reconciles existing scheduled ones.
- `AC-NOTIF-01.3` An interview added 30 minutes before it starts schedules neither reminder and records the skip.
- `AC-NOTIF-01.4` Each cancellation condition in the table cancels the right reminders and leaves others alone.
- `AC-NOTIF-01.5` No reminder is scheduled for an application in `rejected`, `withdrawn`, `accepted`, or `ghosted`.
- `AC-NOTIF-01.6` A reminder for a purged job renders from `payload` without a join.

**Tests.**
- `T-NOTIF-01.1` `tests/integration/test_reminder_scheduling.py`.
- `T-NOTIF-01.2` `tests/integration/test_followup_delay_setting.py`.
- `T-NOTIF-01.3` `tests/unit/test_past_due_skip.py`.
- `T-NOTIF-01.4` `tests/integration/test_reminder_cancellation.py`.
- `T-NOTIF-01.5` `tests/unit/test_terminal_no_reminders.py`.
- `T-NOTIF-01.6` `tests/integration/test_reminder_payload.py`.

---

## 2. Scheduling, reconciliation and local time — `NOTIF-01`, HR-10

**Objective.** Get the timing right in the user's timezone, and keep the schedule consistent when the underlying application changes.

**Constraints.**
- All `due_at` values are stored **UTC** (HR-10). The user's `tz` is applied at scheduling to pick a sensible local moment — "10:00 local" is computed against `tz` at the time the reminder is scheduled, then stored as UTC.
- **DST is handled by recomputation, not by arithmetic.** A reminder scheduled 7 days out across a DST boundary is computed by localizing to `tz`, adding days in local calendar terms, then converting to UTC — never by adding 604,800 seconds. India has no DST, but users will not all be in India, and this is the kind of bug that is invisible until it is embarrassing.
- Changing `user.tz` **reconciles** all scheduled reminders: each is recomputed in the new zone. A user who moves and then gets a 3 a.m. reminder loses trust in the whole system.
- **Reconciliation, not deletion and recreation.** `notifications.reconcile_reminders(application_id)` is the single entry point invoked on every relevant change: it computes the desired set of reminders for the application's current state, compares it with the scheduled set, cancels what should not exist, schedules what is missing, and leaves matching ones untouched (so their `dedup_key` and identity survive). Idempotent — running it twice changes nothing the second time.
- Reconciliation is enqueued by the `ApplicationStatusChanged` and `AppliedConfirmed` handlers (`01-foundations.md` §9), never performed inline.
- Quiet hours (`NOTIF-03`, R2) shift a due time forward to the next allowed hour; they never drop a reminder.

**Inputs.** Application state; `user.tz`; settings.

**Outputs.** The reconciled reminder set.

**Acceptance criteria.**
- `AC-NOTIF-01.7` Every stored `due_at` is UTC-aware; a naive value raises.
- `AC-NOTIF-01.8` A 7-day follow-up crossing a DST transition in `America/New_York` fires at 10:00 local, not 09:00 or 11:00.
- `AC-NOTIF-01.9` Changing `tz` from `Asia/Kolkata` to `Europe/London` recomputes every scheduled reminder to the correct new UTC instant.
- `AC-NOTIF-01.10` Reconciliation run twice on unchanged state performs zero writes and preserves every `dedup_key`.
- `AC-NOTIF-01.11` Reconciliation after a status change cancels exactly the reminders the table says and schedules exactly the new ones.
- `AC-NOTIF-01.12` Reconciliation is always enqueued, never executed in the request or the event handler (`AC-FOUND-09.1` shared).

**Tests.**
- `T-NOTIF-01.7` `tests/unit/test_time_utc.py` (shared).
- `T-NOTIF-01.8` `tests/unit/test_dst_scheduling.py`.
- `T-NOTIF-01.9` `tests/integration/test_tz_change_reconcile.py`.
- `T-NOTIF-01.10`/`.11` `tests/integration/test_reconciliation.py`.
- `T-NOTIF-01.12` `tests/spec/test_handlers_only_enqueue.py` (shared).

---

## 3. Dispatch and idempotency — `NOTIF-05`

**Objective.** Exactly one delivery per reminder occurrence, no matter what the worker does.

**Constraints.**
- `reminders.dispatch()` runs every minute (cron, lock-guarded). It selects `status: scheduled AND due_at <= now`, ordered by `due_at`, in batches of 200, on the `(status, due_at)` index.
- **The idempotency mechanism is the unique `dedup_key`**, not the task's care. `dedup_key` embeds the occurrence: `follow_up:{application_id}:{applied_at_epoch}`, `interview_24h:{application_id}:{interview_id}:{at_epoch}`. Rescheduling an interview produces a genuinely different key, so the new reminder is a new occurrence rather than a silent collision with the old one.
- Dispatch is a **claim-then-send** sequence: an atomic `findOneAndUpdate` moves the row from `scheduled` to `sending` with a claim timestamp; only the claimant sends. A row stuck in `sending` for more than 10 minutes is reclaimed (the worker died), and because the send itself is idempotent per channel where the provider supports it, a reclaim is safe. Where the provider offers no idempotency, a reclaim may duplicate — that is a documented, bounded risk (at most one duplicate per worker death) and is preferable to a silent drop.
- Every attempt increments `attempts` and is logged. After 3 failed attempts the reminder goes to `failed` and the failure is surfaced in the in-app inbox — the user learns we could not email them, rather than silently missing a follow-up.
- Channel selection is per user, per type. The **in-app inbox always receives** the notification regardless of other channels, so nothing is ever entirely lost.
- Dispatch never blocks on a slow provider: each send has a 10-second timeout and a failure is a retry, not a stalled batch.

**Inputs.** Due reminders.

**Outputs.** `notifications` rows; emails; `reminders.status: sent`; metrics by type and channel.

**Acceptance criteria.**
- `AC-NOTIF-05.1` Two dispatch workers running concurrently over the same due set deliver each reminder exactly once.
- `AC-NOTIF-05.2` Killing the worker mid-send and restarting delivers each reminder at most twice and never zero times, with the duplicate bounded to the reclaim window (asserted and documented).
- `AC-NOTIF-05.3` A duplicate `dedup_key` insert is rejected by the index.
- `AC-NOTIF-05.4` Rescheduling an interview produces a different `dedup_key`, and both the cancellation of the old and the scheduling of the new are recorded.
- `AC-NOTIF-05.5` Three send failures move the reminder to `failed` and write an in-app notification explaining it.
- `AC-NOTIF-05.6` A provider that hangs for 30 s does not delay the rest of the batch beyond the timeout.
- `AC-NOTIF-05.7` The in-app notification is written even when email is disabled for that user and type.
- `AC-NOTIF-05.8` 1,000 due reminders are dispatched in batches without exceeding the queue's per-task time budget.

**Tests.**
- `T-NOTIF-05.1` `tests/integration/test_dispatch_concurrency.py`.
- `T-NOTIF-05.2` `tests/integration/test_worker_restart.py` (shared).
- `T-NOTIF-05.3` `tests/integration/test_dedup_key_uniqueness.py`.
- `T-NOTIF-05.4` `tests/integration/test_interview_reschedule.py`.
- `T-NOTIF-05.5` `tests/integration/test_send_failure.py`.
- `T-NOTIF-05.6` `tests/integration/test_provider_timeout.py`.
- `T-NOTIF-05.7` `tests/integration/test_inapp_always.py`.
- `T-NOTIF-05.8` `tests/integration/test_dispatch_batching.py`.

---

## 4. Channels — `NOTIF-02`

### 4.1 In-app inbox and email — **R1**

**Objective.** Two channels, one of which cannot fail to record.

**Constraints.**
- **In-app**: a `notifications` row plus an SSE push to any connected client (`01-foundations.md` §11). Unread count from the partial index. Deep links use a scheme both clients resolve (`app://applications/{id}`), mapped to a web route and a mobile route from one shared table so a link cannot work in one client and not the other.
- **Email**: behind `EmailSender.send(to, template_id, data)` so the provider is swappable (D7 default Resend, SES alternative). Templates authored in MJML, compiled to HTML at build time, **with a plain-text alternative always included** — text-only clients and spam scoring both need it.
- Email content rules: no PII beyond the recipient's own data; the job title and company are the only external strings; every email carries a working unsubscribe/preferences link; the sending domain has SPF, DKIM, and DMARC configured (`15-infra-and-ops.md` §3) or transactional mail lands in spam and the whole reminder feature silently fails.
- A bounce or complaint webhook marks the address `email_undeliverable`, stops email sends, and surfaces it in-app. Continuing to send to a bouncing address damages the sending domain's reputation for every other user.
- Emails are never a channel for anything sensitive: no tokens beyond single-use links, no pack content, no resume text.

### 4.2 Mobile push (FCM) — `NOTIF-02b` — **Track: R2**

Tokens in `devices`, registered after the first application rather than at launch (`14-mobile-client.md` §6 — asking for notification permission on a cold launch is how permission gets denied forever). Behind `PushSender`. An `UNREGISTERED` or `INVALID_ARGUMENT` response invalidates the token immediately. Payload carries the deep link and no content beyond the title and company.

### 4.3 Web push (VAPID) — `NOTIF-02c` — **Track: R3**

Same interface, lowest value, last.

**Inputs.** A user, a template, data.

**Outputs.** Delivered messages; delivery metrics; bounce state.

**Acceptance criteria.**
- `AC-NOTIF-02.1` Every email template renders in HTML and plain text, and a golden-file test catches unintended changes.
- `AC-NOTIF-02.2` Every email contains a working preferences link and no PII beyond the recipient's own.
- `AC-NOTIF-02.3` A bounce webhook marks the address undeliverable, stops further email, and writes an in-app notification.
- `AC-NOTIF-02.4` Deep links resolve to the equivalent screen in both clients, from one shared mapping table.
- `AC-NOTIF-02.5` The unread count matches the number of `read_at: null` rows and updates over SSE without a refetch.
- `AC-NOTIF-02.6` SPF, DKIM, and DMARC records are verified for the sending domain (a check script, run at the R1 gate).
- `AC-NOTIF-02.7` (R2) An invalid FCM token is invalidated on the first failed send and not retried.

**Tests.**
- `T-NOTIF-02.1` `tests/unit/test_email_templates.py`.
- `T-NOTIF-02.2` `tests/integration/test_email_content_rules.py`.
- `T-NOTIF-02.3` `tests/integration/test_bounce_handling.py`.
- `T-NOTIF-02.4` `tests/spec/test_deep_link_parity.py`.
- `T-NOTIF-02.5` `tests/integration/test_inbox_sse.py`.
- `T-NOTIF-02.6` `infra/scripts/check_email_dns.sh` + `tests/spec/test_dns_check_exists.py`.
- `T-NOTIF-02.7` `tests/integration/test_fcm_token_lifecycle.py` (R2).

---

## 5. Quiet hours and the digest — `NOTIF-03`, `NOTIF-04` — **Track: R2**

**Objective.** Do not wake anyone up, and give the passive user (P2) a reason to come back weekly.

**Constraints.**
- **Quiet hours**: a per-user local-time window (default none). A reminder due inside it is **shifted forward** to the window's end, never dropped and never sent early. Interview reminders are exempt — a 1-hour interview reminder at 07:00 for an 08:00 interview must fire.
- **Digest**: weekly, Monday 08:00 local, containing the top 10 new matches at or above the user's threshold from the last 7 days, plus a "looks ghosted" section (`TRACK-06`) and a count of applications needing attention. Opt-in, off by default. Skipped entirely when there is nothing to say — an empty digest trains people to ignore the next one.
- The digest reads stored `match_scores` only. It never triggers scoring or an AI call, so a weekly send cannot spike the AI budget.
- One digest per user per week, idempotent on `digest:{user_id}:{iso_week}`.

**Acceptance criteria.** `AC-NOTIF-03.1` A reminder due inside quiet hours is shifted to the window's end and not sent early. `AC-NOTIF-03.2` Interview reminders ignore quiet hours. `AC-NOTIF-04.1` The digest contains only stored scores above the threshold from the last 7 days, at most 10. `AC-NOTIF-04.2` A user with nothing new receives no digest. `AC-NOTIF-04.3` The digest run makes zero AI calls. `AC-NOTIF-04.4` Re-running the digest job in the same ISO week sends nothing further.
**Tests.** `T-NOTIF-03.1`/`.2` `tests/integration/test_quiet_hours.py`. `T-NOTIF-04.1`–`.4` `tests/integration/test_weekly_digest.py`.
