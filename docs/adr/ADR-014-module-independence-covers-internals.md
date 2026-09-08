# ADR-014 — `module-independence` forbids internals, not the public surface

- **Status:** accepted
- **Date:** 2026-09-08
- **Requirement:** `FOUND-04`, correcting the generated contract and amending
  `AC-FOUND-04.1`'s contract count
- **Supersedes:** nothing

## The conflict

`01-foundations.md` §5 is explicit about how modules read each other:

> Cross-module side effects go through in-process domain events (§9), never a
> direct call into another module's service, **with one exception: a read
> through another module's public service method is allowed and preferred over
> duplicating a query.**

`17-data-model.md` §2 says the same thing from the data side: "Another module
reads it through the owner's public service, never directly."

The generated `module-independence` contract forbids that read. It is an
import-linter `independence` contract over the nine module packages, and
`independence` forbids **every** import between the listed modules in either
direction, at any depth. So `from app.modules.tracker import TrackerService` -
the one thing §5 calls "allowed and preferred" - fails `lint-imports`.

The contract's own generated comment says "Only another module's `__init__.py`
public surface may be imported", which is what §5 means and what the contract
does not do. `independence` has no such mode.

This surfaced building `DATA-05`. `AC-DATA-05.2` requires `jobs.purge_expired`
to keep an expired job that "is referenced by an `applications` document", and
`applications` is owned by `tracker`. That reference check is precisely §5's
sanctioned read, and there is no way to write it.

## Why the specification is right and the contract is wrong

The alternative - route the reference check through an event - does not work and
would be worse if it did. An event tells you something happened; this needs to
ask a question *now*, at purge time, about a job the purge is holding. Modelling
it as an event means `tracker` publishing "these job ids are referenced" on a
schedule and `jobs` caching it, which is a denormalised copy of another module's
data, kept in sync by nothing, consulted when deciding whether to delete
something permanently. §5 anticipates exactly this: the read is "preferred over
duplicating a query".

What §5 forbids is reaching *past* the public surface - into `models`,
`repository`, or the internals of a service. That is the rule worth enforcing,
because that is the coupling that makes a module impossible to extract later:
another module holding a Beanie document class, or building a Mongo filter
against a collection it does not own.

## The two options considered

**Add `ignore_imports` entries.** Rejected outright. `AC-FOUND-04.1` requires
"**zero** `ignore_imports` entries. An exemption requires a new ADR." An
exemption per cross-module read would be a growing list of holes in the one
contract that keeps the monolith modular - and each hole would be shaped like a
legitimate read, so nobody would object to the next one.

**Forbid the internals instead.** Accepted. Nine `forbidden` contracts, one per
module, each forbidding the other eight modules' internal submodules -
`models`, `repository`, `service`, `router`, `tasks`, `events`, and the
pure-logic files §5 permits. A module's package root stays importable, so
`from app.modules.tracker import TrackerService` works and
`from app.modules.tracker.repository import ApplicationRepository` does not.

That is stricter than `independence` in the way that matters and looser in the
way §5 asks for. It also forbids something `independence` allowed by accident:
`independence` had nothing to say about `app.modules.auth.service` importing
`app.modules.auth.models` (correct, and permitted) versus
`app.modules.jobs.service` importing `app.modules.jobs.repository` from a
*different* module's file - the per-module `forbidden` form catches the second.

## Decision

`gen_importlinter.py` emits one `forbidden` contract per module in place of the
single `independence` contract, named `module-independence-<name>`.

`AC-FOUND-04.1`'s "all eight contracts active" becomes "all seven cross-cutting
contracts plus one per module". Seven, because `module-independence` leaves the
numbered set and the per-module contracts are counted separately - the numbered
contracts are the ones that do not scale with the module list, and conflating
the two is what made "eight" ambiguous as soon as the ninth module landed.

`ignore_imports` stays at zero, and the test that asserts it stays as it is.

## Spec amendment

`AC-FOUND-04.1` changes from:

> `lint-imports` exits 0 with all eight contracts active and **zero**
> `ignore_imports` entries.

to:

> `lint-imports` exits 0 with all seven cross-cutting contracts active, one
> `module-independence-<name>` contract per module, and **zero**
> `ignore_imports` entries. A module's package root is importable by another
> module - §5's sanctioned read - and its internals are not (ADR-014).

No criterion is added, removed or renumbered. The counts stay at 826 and 826.

## Consequences

- `jobs.purge_expired` can ask `tracker` whether a job is referenced, through
  `TrackerService`, which is what `AC-DATA-05.2` requires.
- `tests/spec/test_collection_ownership.py` is unaffected and is now the
  narrower control it was written to be: it forbids importing another module's
  *documents* specifically, which the new contracts also forbid - two
  mechanisms for the property most worth protecting.
- Every module's `__init__.py` becomes load-bearing. `AC-FOUND-04.2` already
  requires `__all__` to be non-empty and to export nothing from `models.py` or
  `repository.py`, so the public surface is already the reviewed thing.
- `tests/spec/test_import_linter_catches_violation.py` gains a fixture for the
  new shape: `alpha` importing `beta`'s package root must pass, and `alpha`
  importing `beta.repository` must fail. Both directions, because a contract
  that forbade everything would satisfy the second and break the product.
