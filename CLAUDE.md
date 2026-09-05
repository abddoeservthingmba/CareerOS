# JobPilot — operating rules for Claude Code

You are building the product described in `docs/spec/`. That specification is the contract:
it says what to build, in what order, and how to prove it is done. Read it, do not re-derive it.

## Read these first, every session

1. `docs/spec/README.md` — the section contract, the ID conventions, the twelve hard rules
2. `docs/spec/00-scope-and-phases.md` — tracks, phases, gates
3. `docs/spec/01-foundations.md` — conventions every module obeys
4. `docs/spec/17-data-model.md` — the schema contract

Then work from `docs/spec/BUILD-ORDER.md`, one requirement at a time.

## The loop, per requirement

1. `make bundle REQ=<id>` — read exactly those files, not the whole spec.
2. Implement only that requirement, only for the track being built (R1 unless told otherwise).
3. Write the tests **named in the spec's Tests list**, at the paths given, in the same commit.
4. Run `make check` (lint, types, import-linter, spec gates, tests). All green, or the work is not done.
5. Commit with the requirement ID in the subject: `feat(matching): MATCH-05 incremental scoring`.

## Non-negotiable

- **The twelve hard rules in `README.md` §2 override everything**, including anything you infer from
  a code sample in the spec. HR-1 (nothing is ever submitted to a third-party site) and HR-2 (no
  scraping of prohibited sources) are product-defining; there is no flag that turns them off.
- **Never invent a requirement.** If the spec does not cover something you need, stop and say so.
  Propose the spec edit; do not improvise and do not leave a TODO.
- **Never weaken an acceptance criterion to make a test pass.** If a criterion is wrong, say why.
- **No feature is half-built.** Every section is `built`, `built-off`, `stub-501` or `absent`
  (`01-foundations.md` §15). There is no fifth state.
- **Secrets never enter the repo.** Ask for credentials, put them in `.env` (gitignored), keep
  `.env.example` in sync with `Settings`.
- **Model names, provider names and limits are configuration**, never literals in `.py` files.
- Do not deploy anything. Local and CI only until the R1 gate passes.

## When you are blocked

Say which acceptance criterion you cannot satisfy and why, in one paragraph. Do not guess at
product behaviour. The open decisions are in `00-scope-and-phases.md` §5 and each has a default —
use the default and say you used it, rather than stopping.

## Conventions you will otherwise get wrong

- ULID string `_id`, never ObjectId in a response (`01` §3)
- UTC everywhere in storage; local time only at reminder scheduling and rendering (HR-10)
- Money is a minor-unit integer, never a float
- Ownership failures answer **404, not 403** (`02` §6)
- Tasks take IDs only, never documents; every task is idempotent by a stated natural key (`01` §10)
- Services never import FastAPI; routers never contain business rules (`01` §5)
- One image, two entrypoints (`api`, `worker`)
