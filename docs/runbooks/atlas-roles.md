# Atlas database roles

`17-data-model.md` §2.12 and `AC-DATA-02.4`.

**This control cannot be verified by a test.** The suite runs under the same
database credential the application uses, so a test that successfully deleted an
`audit_log` row would prove the role is *wrong*, and a test that failed to delete
one could not be told apart from a network error. Whoever provisions a database
user applies the grants below, and `tests/integration/test_audit_append_only.py`
asserts only that this page exists and names the collection — not that Atlas is
configured correctly.

Read that literally: a green build says nothing about the privileges in force.

## The application user

One user, used by both entrypoints (`api` and `worker` — one image, ADR-002).

| Grant | Scope | Why |
|---|---|---|
| `readWrite` | every collection **except** `audit_log` | ordinary operation |
| `find`, `insert` | `audit_log` | append-only (`AC-DATA-02.4`) |
| **not** `update` | `audit_log` | an editable audit row is not evidence |
| **not** `remove` | `audit_log` | nor is a deletable one |
| **not** `dbAdmin` | anything | indexes are declared in code (`DATA-03`) and created by the deploy, never by the app |

### Why `audit_log` is singled out

Every other collection's value is that it says what is true now. `audit_log`'s
value is that it says what happened — and it is read precisely when that is
contested: a pack the user says they never approved, a consent they say they
never gave, a deletion request they say we ignored. A log the application can
rewrite answers only "here is what the application currently says", which is
what the rest of the database already says and worth nothing as evidence.

The repository-level control (`append` and `find` only) covers code written from
now on. It does not cover a migration script, an aggregation `$merge`, or a fix
applied by hand in Atlas's data browser at two in the morning. This grant does.

## Creating the role

Atlas has no built-in role with this shape, so it is a custom role. In Atlas:
**Database Access → Custom Roles → Add Custom Role**.

```
Role name: jobpilot_app

Action: find, insert, update, remove, createIndex
  Resource: database `jobpilot`, all collections   ← EXCEPT audit_log, see below

Action: find, insert
  Resource: collection `jobpilot.audit_log`
```

Atlas's role editor grants by resource, and a collection-level grant does not
subtract from a database-level one — they add. So the database-level grant must
**not** include `update` or `remove`; those are granted per collection instead,
to every collection except `audit_log`. Getting this backwards is the likely
mistake and it fails open: the role looks right in the UI and the audit log is
mutable.

## Verifying it, by hand

Against a **staging** database, never production, as the application user:

```js
use jobpilot
db.audit_log.insertOne({ _id: "verify", kind: "admin_action", at: new Date() })   // succeeds
db.audit_log.updateOne({ _id: "verify" }, { $set: { kind: "data_export" } })      // must fail: not authorized
db.audit_log.deleteOne({ _id: "verify" })                                        // must fail: not authorized
db.applications.updateOne({ _id: "nothing" }, { $set: { x: 1 } })                // succeeds (0 matched)
```

The fourth line matters as much as the second and third: a role that refused
everything would pass the two "must fail" checks and break the product.

The `verify` row stays in staging's `audit_log`. That is correct — it cannot be
removed by this user, which is the property being demonstrated.

## Rotation

Rotating the password does not change the grants. Rotating the *user* does:
a new user created with `readWriteAnyDatabase` because it was quicker undoes
this entire control, silently, and nothing will fail. Re-run the four commands
above after any change to database access.

| Field | Value |
|---|---|
| Owner accountable for this control | `UNFILLED` |
| Last verified against staging | `UNFILLED` |
| Verified by | `UNFILLED` |
