# auth

## Purpose

Identity: who someone is, and how they prove it. `02-auth-and-account.md`.

Registration, sign-in, session lifetime, password reset, account deletion, and
the rate limiting that protects all of them. Everything a user does *before* the
product knows anything about their career.

The module's defining constraint is that it must not leak who has an account.
§1's registration is enumeration-safe, §3's login answers identically for a
wrong password and an unknown address, and §9 extends the rule to the rate
limiter itself — otherwise the limiter becomes the oracle the other two close.

## Status

| Requirement | State | Notes |
|---|---|---|
| `AUTH-01` registration and password policy | **built** | `POST /api/v1/auth/register` |
| `AUTH-09` rate limiting | **built** | the limiter itself is `core/ratelimit.py` |
| `AUTH-02` Google sign-in · `AUTH-03` login · `AUTH-04` reset · `AUTH-05` change · `AUTH-07` deletion · `AUTH-10` sessions | absent | P1, not yet started |
| `AUTH-06` session list · `AUTH-08` data export | absent | R2 |

The documents in `models.py` — `users`, `refresh_tokens`, `email_tokens` — are
all three built, because `DATA-02` created them in P0. A collection existing is
not a requirement being built.

## Public API

`__init__.py`'s `__all__` is the contract: `AuthService`, its request and
response DTOs, its two published events, and its two exceptions. Never a Beanie
document and never a repository (`AC-FOUND-04.2`).

## Events published

| Event | Consumed by | Handler action |
|---|---|---|
| `UserRegistered{user_id}` | — | none in R1 |
| `UserDeletionRequested{user_id, requested_at}` | — | none in R1; `AUTH-07`'s cron scans `users` |

Both were added to `01-foundations.md` §9's table by `AUTH-01`. The registry had
listed neither while §8 of `02-auth-and-account.md` named this module as their
publisher, and `EventBus.publish` rejects an unregistered name — so
registration could not be built until the two agreed.

`UserDeletionRequested`'s handler action is **none** on purpose. A deletion that
depended on an in-process handler would be lost on a restart between the request
and the sweep, so `AUTH-07`'s cron reads `users.status` and
`deletion_requested_at` instead. The event notifies; it is never the mechanism.

## Events consumed

None.

## What is worth knowing before changing `service.py`

**`register` is constant-time, and not by accident.** §1's objective is "without
revealing whether an email is registered". Three things hold that up, and each
looks removable:

1. The password is hashed on **both** branches, including the one that discards
   it. Argon2 at 64 MiB dominates the request, so hashing only for new accounts
   makes "already registered" measurably faster.
2. Every 202 is padded to `REGISTER_MIN_MILLIS`. Hashing on both paths is not
   sufficient — the fresh branch also writes the user *and* its verification
   token, two round trips a collision never pays. Measured against a managed
   database the fresh path was 59 ms **slower**, which is an oracle for "this
   address is *not* registered".
3. A mail failure is caught and logged, never raised. Otherwise the two paths
   diverge the moment one template's provider is unhealthy, and the observable
   is a 500 for exactly the addresses that already have accounts.

`tests/integration/test_registration_enumeration.py` measures the gap rather
than trusting the padding, because a floor set below the real cost fails
silently.

**The `registration_attempted` email carries no token.** Its `reset_url` points
at the reset *request* page. Minting a reset token there would hand anyone a
working credential for an address they do not own, by submitting a signup form.

**Consent is checked before anything else.** `AC-AUTH-01.7` requires a stale
version to create no user, and validating first means there is nothing to undo.
Both halves are checked — the version is current *and* the accepted keys cover
the current item set — because a right version with an empty item list would
record a consent to nothing.
