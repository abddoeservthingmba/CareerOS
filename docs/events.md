# Domain events — generated from `app/core/events.py`

Do not edit. Regenerate with `make events-doc`.

`01-foundations.md` §9. A handler does nothing but enqueue; it never does work
inline, and an exception in one never reaches the publisher.

| Event | Published by | Consumed by | Handler action |
|---|---|---|---|
| `ProfileUpdated{user_id, profile_version, changed_paths}` | profile | matching | enqueue `matching.rescore_user` (debounced 60 s) |
| `ProfileConfirmed{user_id}` | profile | — | (R2: completeness recompute) |
| `ResumeExtracted{user_id, resume_id}` | resume | profile | enqueue `profile.stage_extraction` |
| `JobsIngested{connector, job_ids}` | jobs | matching | enqueue `matching.score_new_jobs` |
| `JobExpired{job_id}` | jobs | tracker | enqueue `tracker.flag_expired_listing` |
| `ApplicationStatusChanged{application_id, user_id, from_status, to_status}` | tracker | notifications | enqueue `notifications.reconcile_reminders` |
| `PackApproved{user_id, application_id, pack_id, content_hash}` | apply | tracker | enqueue `tracker.append_timeline` |
| `AppliedConfirmed{user_id, application_id, applied_at}` | apply | tracker, notifications | transition to `applied`; schedule follow-up |
| `UserRegistered{user_id}` | auth | — | none in R1 |
| `UserDeletionRequested{user_id, requested_at}` | auth | — | none in R1; `AUTH-07`'s cron scans `users` |
