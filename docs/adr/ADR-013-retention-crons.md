# ADR-013 — the four retention crons §5 requires are added to §10's inventory

- **Status:** accepted
- **Date:** 2026-09-08
- **Requirement:** `DATA-05`, amending `01-foundations.md` §10
- **Supersedes:** nothing

## The conflict

`17-data-model.md` §5's retention table names a **mechanism** for every row, and
its own first constraint makes that non-negotiable:

> A retention rule with no mechanism is a defect. Every row above names one.

Five rows name a "nightly cron". `01-foundations.md` §10's R1 task inventory
declares fourteen tasks and only one of them:

| §5 row | Mechanism §5 names | In §10's inventory? |
|---|---|---|
| `jobs`, expired | Nightly `jobs.purge_expired` cron | **no** |
| `connector_runs`, 180 days | Nightly cron | **no** |
| `notifications`, 180 days | Nightly cron | **no** |
| `reminders`, sent or cancelled, 180 days | Nightly cron | **no** |
| `failed_tasks`, resolved, 90 days | Nightly cron | **no** |
| Everything user-owned, after deletion | `account.purge_deleted` | yes |

`AC-DATA-05.2` then names `jobs.purge_expired` directly, so it is not merely
implied — a criterion asserts behaviour of a task the inventory does not have.

And `core/tasks.py` refuses at import any `@task` whose name is absent from
`DECLARED`, which is §10's table transcribed. That refusal is `AC-FOUND-10.4`
working exactly as intended: it is why the conflict surfaced as a failed import
rather than as a task nobody noticed was undeclared.

## Why the crons are right and the inventory is incomplete

§10's inventory is a list of the tasks the *features* need — it was written from
the feature sections. §5's table was written from the data model. Neither is
wrong about its own subject; the inventory simply predates §5's mechanisms
being enumerated, and a retention rule is a task like any other.

The alternative reading — that §5's "nightly cron" means one of the existing
fourteen — does not survive contact with the table. `account.purge_deleted`
deletes *one user's* data on request; sweeping 180-day-old `notifications`
across all users is a different query, a different failure mode and a different
lock. Folding them together would mean a bug in the notification sweep failing
account deletions, which is the one cron that must not fail.

## The two options considered

**Write the retention sweeps into `account.purge_deleted`.** Rejected. Coupling
five unrelated sweeps to the deletion cron means one shared lock, one shared
failure, and a `failed_tasks` row that says "account.purge_deleted" when what
broke was a `connector_runs` delete. It also makes the 7-day deletion promise
depend on housekeeping.

**Add the tasks to §10's inventory.** Accepted. They are tasks; the inventory is
the place tasks are declared; and `AC-FOUND-10.1`–`.6`'s guarantees — scalar
arguments, a stated idempotency key, a Redis lock, a `failed_tasks` row on
exhaustion — are exactly the guarantees a retention sweep needs.

## Decision

Four rows are added to §10's inventory. Not five: `reminders` and
`notifications` are both owned by the notifications module and are swept by one
task, because they are one lock, one schedule and one retention window.

| Task | Trigger | Natural key | Notes |
|---|---|---|---|
| `jobs.purge_expired()` | cron `0 4 * * *` | `expired_at` window + reference check | `DATA-05`; clears descriptions on referenced jobs rather than deleting them |
| `connector_runs.purge()` | cron `0 4 * * *` | `started_at` window | `DATA-05`; 180 days |
| `notifications.purge()` | cron `0 4 * * *` | `created_at` window | `DATA-05`; covers `notifications` and sent/cancelled `reminders` |
| `ops.purge_failed_tasks()` | cron `0 4 * * *` | `resolved_at` window | `DATA-05`; 90 days, resolved only |

All four at 04:00 UTC: after `ops.backup` (02:00) so a purge is always recoverable
from that night's backup, and after `account.purge_deleted` (03:00) so a
deleted user's rows are already gone and the retention sweeps have less to do.
HR-10: every schedule is UTC.

`ops.purge_failed_tasks` is under `ops` rather than `core` because §10's naming
uses `ops.` for tasks with no owning feature module, and `failed_tasks` is one
of §2's two infrastructure collections.

## Spec amendment

`01-foundations.md` §10's inventory gains the four rows above. The sentence
introducing it changes from "R1 task/cron inventory" to note the count, so a
fifteenth task added without a row is visible.

No acceptance criterion is added, removed or renumbered — the counts stay at 826
and 826. `AC-FOUND-10.3`'s "parametrized over the inventory" now covers eighteen
tasks instead of fourteen, which is the criterion doing more work rather than
different work.

## Consequences

- `core/tasks.py`'s `R1_TASKS` gains four rows and
  `tests/spec/test_task_signatures.py` — which parses §10's table and compares —
  keeps both in agreement.
- `AC-DATA-05.4`'s coverage test can now assert that every §5 mechanism names a
  task that exists, rather than only that every collection appears in the table.
- Each of the four is a cron, so each takes a Redis lock named for itself
  (`AC-FOUND-10.6`) and four sweeps at the same minute do not contend.
