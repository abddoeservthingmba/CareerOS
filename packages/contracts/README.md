# `packages/contracts`

The API contract, and the two clients generated from it.

**This directory is written by CI and by nobody else.** `01-foundations.md` §1:
"No generated code is hand-edited. `packages/contracts` is written only by the
`contracts` CI workflow." `AC-FOUND-01.5` asserts it as a git-history check —
a commit here whose author is not the CI bot fails the build.

The rule is not tidiness. `openapi.json` is the evidence an API diff is taken
against (`AC-FOUND-13.4`): if it can be hand-edited, a breaking change can be
declared additive by editing the evidence rather than the API. And `ts/` and
`dart/` are build outputs — a hand-committed one becomes the version everyone
actually uses, and drifts from the server silently.

## What is here

| Path | Written by | Committed |
|---|---|---|
| `openapi.json` | `infra/scripts/export_openapi.py`, run by `contracts.yml` | yes — it is the diff baseline |
| `ts/` | `openapi-typescript` + `openapi-fetch`, in CI | no (gitignored) |
| `dart/` | `openapi-generator` dart-dio, in CI | no (gitignored) |

`openapi.json` is committed because a document that existed only at build time
could not be compared with the previous one, and "a removed field fails CI" has
nothing to subtract from. The clients are not, because they are reproducible
from it and a stale copy is worse than none.

## Regenerating locally

```sh
py infra/scripts/export_openapi.py --write     # the document
py infra/scripts/export_openapi.py --check     # what CI asserts
```

The document contains only routes under `/api/v1` (`AC-FOUND-13.5`).
`/healthz`, `/readyz`, `/metrics` and the provider webhooks are deliberately
absent: a load balancer is not an API consumer, and anything in the generated
client is something a client developer can call — and therefore something that
cannot be changed freely.

## Changing the API

Additive changes — a new endpoint, a new optional field — are free within `v1`.
A breaking change is never made in place; it creates `/api/v2` (§13). If one
genuinely has to land on `v1`, the PR body needs:

```
BREAKING-API-APPROVED: <why a shipped mobile app is allowed to break>
```

with an actual reason. A bare token is the ritual without the thinking, and the
check requires the sentence.
