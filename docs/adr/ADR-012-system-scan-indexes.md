# ADR-012 — the compound-index rule admits enumerated system-scan indexes

- **Status:** accepted
- **Date:** 2026-09-08
- **Requirement:** `DATA-03`, amending `17-data-model.md` §1 and §3
- **Supersedes:** nothing

## The conflict

`17-data-model.md` §1 and §3 both state the rule without qualification:

> Every user-owned document has `user_id` as its **first** field in every
> compound index. (§1)

> Every compound index on a user-owned collection starts with `user_id`. (§3)

§3's own index table then declares two compound indexes on user-owned
collections that do not:

| Collection | Index | Serves |
|---|---|---|
| `reminders` | `status, due_at` | dispatch scan |
| `application_packs` | `application_id, status` | current pack |

The specification therefore contradicts itself, and it is not a typo in the
table: both indexes serve queries that are correct only because they cross
users.

## Why each one is right as written

**`reminders (status, due_at)`** is the dispatch scan. Every minute, a cron asks
"what is due now, for everybody" — that is the entire job. Leading with `user_id`
would require iterating users to find the ones with due reminders, which is a
full scan of `users` per minute plus one indexed lookup per user. At any real
number of users that is the wrong shape, and it gets worse in exactly the way
that matters: linearly with signups, on a cron, forever.

**`application_packs (application_id, status)`** finds the current pack for one
application. `application_id` is already narrower than `user_id`: an application
belongs to exactly one user, so a lookup by it cannot reach another user's data.
Prefixing `user_id` would make the index larger, no more selective, and no
safer.

## The two options considered

**Rewrite the two indexes to lead with `user_id`.** Rejected. It makes the
dispatch scan O(users) per minute — a real, permanent, growing cost — to satisfy
a rule whose purpose (stopping an accidental cross-user read) is not served
here, because the dispatch scan is *deliberately* cross-user and there is no
`user_id` to supply.

**Weaken the rule to "should".** Rejected, and this is the important rejection.
The rule's value is that it has no judgement in it: an index that does not lead
with `user_id` is wrong, full stop, so a forgotten `user_id` and a deliberate
cross-user index look different. "Should" restores the judgement, and the next
index that omits `user_id` will be omitting it by accident with a plausible
reason attached.

## Decision

The rule keeps its absolute form, and gains an **enumerated exception list**.
`app/core/documents.py` holds `SYSTEM_SCAN_INDEXES`: an explicit set of
`(collection, key pattern)` pairs that may omit the leading `user_id`, each with
its reason. `compound_index_starts_with_user_id` consults it.

Adding an entry is a visible act in a reviewed file, next to five other entries
that each say why. That is the same mechanism `AC-FOUND-04.1` uses for
`ignore_imports` — "an exemption requires a new ADR" — and for the same reason:
the goal is not to prevent exceptions but to make each one a decision somebody
made rather than a line somebody wrote.

A **system-scan index** is one that serves a scheduled job or a per-entity
lookup narrower than the user. Nothing on a request path may use one, which
`AC-DATA-01.4`'s `@admin_scope` check already enforces from the other side.

## Spec amendment

§1's sentence and §3's constraint each gain the same clause:

> …in every compound index, except for the system-scan indexes enumerated in
> `core/documents.py`, each of which serves a scheduled job or an entity
> narrower than a user and carries a stated reason.

No acceptance criterion is added, removed or renumbered. The counts stay at 826
criteria and 826 tests. `AC-DATA-03.1`'s "every index above is declared in code"
now has an internally consistent set to declare.

## Consequences

- The two indexes are declared as §3's table gives them.
- `compound_index_starts_with_user_id` gains a lookup, and a test asserts the
  exception list is *narrow*: an entry for a collection with no system scan
  fails, and so does an entry that duplicates a rule-abiding index.
- The dispatch scan stays O(due reminders) rather than O(users).
- `tests/integration/test_index_declarations.py` asserts the exception list and
  §3's table agree, so the list cannot grow without the table growing too.
