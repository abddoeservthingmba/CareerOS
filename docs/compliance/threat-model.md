# Threat model

`16-security-and-compliance.md` §1 (`SEC-01`).

**Objective.** Name what is actually being defended against, so controls can be
judged against something.

That phrasing is the point of the document. A control list with no threat model
is a list nobody can argue with: every item looks prudent, none can be shown to
be unnecessary, and none can be shown to be missing. This page is what makes the
control table in §2 answerable — each control exists because of a named
adversary with a named goal, and a control that answers no adversary here is a
control to question.

| Field | Value |
|---|---|
| Last reviewed | 2026-09-08 |
| Next review due | 2027-03-07 |
| Review interval | 180 days (`AC-SEC-01.1`) |
| Owner accountable for this document | `UNFILLED` |
| Reviewed by | `UNFILLED` |

---

## 1. Assets, in order of consequence

Ordered deliberately. When two controls compete for effort, the one protecting a
higher asset wins, and "in order of consequence" means consequence *to the
user*, not to us.

### 1. A user's résumé and profile

A complete employment history, contact details, and often a current-employer
name.

Leakage is a privacy harm and, for someone job-hunting quietly, a professional
one — the disclosure that matters is not the résumé's contents but the fact of
its existence on a job-search product, visible to a current employer. That is
the asset whose loss the user cannot undo, cannot mitigate, and did not choose
to risk beyond uploading a file.

It is first for that reason and not because it is the largest data set.

### 2. The application record

That someone applied to a competitor is more sensitive than the applications
themselves.

The distinction is worth stating because it inverts an intuition. A cover letter
is a document the user wrote to be read by a stranger; the *list* of who they
sent it to is a document they wrote for nobody. A breach of the second is worse
than a breach of the first even though the first contains more text.

### 3. Credentials and sessions

Account takeover exposes 1 and 2 and allows text to be sent as the user.

Third rather than first because it is a means to the other two rather than an
end — but the "sent as the user" clause is its own harm: a product that can
generate an application in someone's name is a product whose compromise can
generate one they did not write.

### 4. The AI budget

Abusable for cost, and it is a shared resource across users.

The second clause is what makes it an asset rather than an expense. A single
abusive account consuming the daily cap degrades the product for every other
user — the degradation matrix in `05-ai-layer.md` §3 is what turns that from an
outage into a reduced service, and the per-user caps are what stop one account
reaching the global one.

### 5. The job corpus

Low sensitivity, but its integrity matters: a poisoned corpus produces bad
scores and, via prompt injection, bad letters.

Nothing in it is private — every listing was public when it was fetched. What
can be lost is trust in the output: a candidate who applies to a role that does
not exist, or sends a letter shaped by text an attacker put in a job
description, has been harmed by our data quality rather than by a disclosure.

---

## 2. Adversaries, and the control that answers each

| Adversary | Goal | Primary control | Verified by |
|---|---|---|---|
| Credential stuffer | Account takeover at scale | Argon2id, breach check, two-dimension rate limits, enumeration-safe responses | `AC-AUTH-01.2`, `AC-AUTH-01.6`, `AC-AUTH-09.1`–`.6` |
| Another user of the product | Read someone else's profile or applications | Ownership-only authorization, **404 not 403**, generated cross-tenant sweep | `AC-AUTH-10.1`–`.5` |
| A malicious job listing | Manipulate extraction, scoring, or a cover letter; or attack the browser | Untrusted-content delimiting and the injection corpus, HTML allowlist sanitization, no model-driven control flow | `AC-AI-06.1`–`.6` |
| An abusive signup | Consume the AI budget | Email verification before spend, per-user daily caps, invite-only R1 (D10) | `AC-AI-03.1`–`.4` |
| A stolen device | Read tokens | In-memory access tokens, Keystore refresh, `allowBackup=false`, family revocation | `AC-MOB-03.1`–`.4`, `AC-AUTH-04.5` |
| A compromised dependency | Anything | Lockfiles, `pip-audit`/`npm audit`, Dependabot, no HTML parser or headless browser in the API image | `AC-CONN-02.4`, `AC-OPS-03.4` |
| Us, by accident | Leak PII into logs, prompts, or an AI provider | The log-privacy assertion, the file-boundary assertion, the contacts assertion | `AC-FOUND-14.1`, `AC-RES-05.2`, `AC-TRACK-03.3` |

**"Us, by accident" is the last row and the most likely one.** Every other
adversary has to do something; this one only has to be busy. It is the row with
the most controls behind it in `01-foundations.md` §14 and `05-ai-layer.md` §5,
and it is the only adversary that has already caused a real finding in this
repository: the Gemini API key was reachable through `vars(self)` and
`core/redaction.py` would not have scrubbed it, so a Sentry frame would have
uploaded the credential verbatim. Found by a test, fixed with a closure — and it
is the shape every future instance of this row will take.

---

## 3. Explicitly not defended against in R1

Recorded so the choice is deliberate. `AC-SEC-01.3` requires each accepted risk
to name a compensating control or an explicit "none", because an accepted risk
with no compensating control and no acknowledgement is indistinguishable from
one nobody thought about.

### A compromised host

No HSM, no envelope encryption of the whole database.

**Compensating control:** none.

An attacker with the application's memory has the database credential and the
decryption key for anything the application can read, so application-level
encryption of everything buys nothing against this adversary — it protects
against a *stolen backup*, which is a different threat and is covered by R2's
field encryption for `contact.phone`. Claiming otherwise is the usual mistake
here. Accepted because the alternative is a key-management system this product
cannot justify at R1, and pretending to have one is worse than not having one.

### A malicious operator

There is one operator, and admin reads are audited rather than prevented.

**Compensating control:** `audit_log` is append-only in code *and* by database
privilege (`AC-DATA-02.4`), and every individual-user read from `/admin` is
audited (`AC-ADMIN-06.1`–`.7`). So an operator can read anything and cannot
erase the record of having read it.

That is genuinely weaker than prevention and it is the right trade at one
operator: separation of duties needs two people, and a control that requires a
second person who does not exist is a control that gets bypassed on the first
incident.

### A targeted state-level adversary

**Compensating control:** none.

Out of scope in the sense that no control in this document would change the
outcome. Stating it prevents the reverse error — treating a control as
sufficient because it would stop a credential stuffer.

### Access-token revocation before its 15-minute expiry

`AC-AUTH-04.7`.

**Compensating control:** the 15-minute lifetime itself, plus refresh-family
revocation, which stops the *next* access token being issued. A logout, a
password change or a detected token reuse revokes the family immediately; the
access token already in the client's memory keeps working until it expires.

A denylist checked on every request would close the window and would put a Redis
read on the hot path of every authenticated request — including during a Redis
outage, when `AC-AUTH-09.6` requires auth to fail closed. Fifteen minutes of
residual access after a logout is the accepted cost.

### No malware scanning in R1

`AC-SEC-02.3` marks ClamAV as R2.

**Compensating control:** magic-byte type detection (`AC-DATA-04.4`), a 5 MB
cap, and — the load-bearing one — nothing uploaded is ever executed, rendered,
or parsed by anything other than a text extractor. A malicious PDF is a threat
to whoever opens it, and the only party who ever opens it is the user who
uploaded it.

### No field-level encryption in R1

`AC-SEC-02.4` marks it R2.

**Compensating control:** none for a stolen backup; backups are retained 14 days
and that window is disclosed in the consent text (`SEC-04`). Accepted because
the asset it protects — `contact.phone` — ranks below the résumé text it would
not protect, so encrypting it first would be security theatre with a real
performance cost.

---

## 4. What this document is for, and what it is not

It is the thing §2's control table is judged against. Two questions it should be
able to answer at any time:

- **Is this control necessary?** If no adversary in §2 has a goal it obstructs,
  the honest answer is "we do not know", and that is worth finding out before
  the control accrues maintenance.
- **Is something missing?** If an adversary's goal is answered only by a control
  marked R2, or by nothing, that is a gap rather than a plan.

It is **not** a compliance artifact to be filed. `AC-SEC-01.1` puts a 180-day
review on it for that reason: a threat model that is not revisited describes the
product as it was, and the gap between that and the product as it is grows
silently, in the direction of fewer controls covering more surface.

**Review means re-reading §2's table against §2 of this document**, not
re-reading this document. The assets do not change often. What changes is the
number of ways in, and each new requirement adds some.
