# 18 — Dependency Closure and Build Order

**Module:** `docs/spec/dependencies.yaml`, `apps/api/tests/spec/`
**Track:** R1
**Depends on:** `00-scope-and-phases.md` §2 and §4, `01-foundations.md` §4
**Requirements:** `DEP-01` … `DEP-05`
**Added in:** v2.1

The v2.0 specification said an agent could be handed one module file and build it. That was true of the *prose* and false of the *graph*: modules consume each other's public APIs and events, and nothing declared which. This file makes the graph explicit, machine-readable, and checked, so that "what must exist before I can build this" is a query rather than a reading exercise.

Two closure properties matter, and they are different. **Track closure** asks whether R1 can ship without R2 or R3 code existing. **Phase closure** asks whether each phase can be built with only what earlier phases produced. v2.0 satisfied the first and violated the second in two places (§5), which is exactly what this check exists to catch.

---

## 1. The manifest — `DEP-01`

**Objective.** One machine-readable file declaring, for every requirement, what it needs before it can be built, so build order is derived rather than assumed.

**Constraints.**
- `docs/spec/dependencies.yaml` is the authority. It is committed, reviewed like code, and read by the traceability gate (`01-foundations.md` §6) and by the metadata generator.
- Schema, one entry per requirement ID in `00-scope-and-phases.md` §2:

```yaml
MATCH-05:
  track: R1                 # must equal the track table in 00 §2
  phase: P4                 # the phase that builds it; null for R2/R3 items not yet phased
  module: matching          # owning module, matching 01-foundations §4
  requires:                 # hard edges: this cannot be built without them
    - PROF-02               # preferences define the candidate set
    - JOB-04                # scoring reads normalized fields only
    - MATCH-01
    - AI-02                 # embedding provider selection
  consumes_events: [JobsIngested, ProfileUpdated]
  publishes_events: []
  reads_collections: [profiles, jobs, match_scores]
  writes_collections: [match_scores]
```

- `requires` means **hard**: the dependency's acceptance criteria must be green before this requirement's can be. A soft or aspirational relationship is not an edge and does not belong here.
- A cross-module edge must correspond to a permitted import (`01-foundations.md` §4) or to a domain event. An edge that would require importing another module's models is a specification defect, not a dependency.
- `reads_collections` / `writes_collections` must be consistent with the ownership table in `17-data-model.md` §2: a requirement may write only to its own module's collections.
- Every requirement in `00 §2` appears exactly once; no entry exists for an ID absent from that table.

**Inputs.** `00-scope-and-phases.md` §2 (tracks), §4 (phases); `01-foundations.md` §4 (import contracts); `17-data-model.md` §2 (ownership).

**Outputs.** `dependencies.yaml`; a `requires` field on every requirement in `SPEC-METADATA.json`; a rendered graph in `docs/spec/TRACEABILITY.md`.

**Acceptance criteria.**
- `AC-DEP-01.1` Every requirement ID in `00 §2` has exactly one manifest entry, and every manifest entry names an ID that exists there.
- `AC-DEP-01.2` Each entry's `track` equals the track table's value, and each `module` is a real module directory or `core`/`ai`/`connectors`.
- `AC-DEP-01.3` Every `requires` target exists as an entry; there is no dangling edge.
- `AC-DEP-01.4` The graph is acyclic; a cycle fails with the cycle printed.
- `AC-DEP-01.5` Every cross-module edge corresponds to a permitted import or to a declared event in `01-foundations.md` §9; an edge implying a forbidden import fails.
- `AC-DEP-01.6` No requirement declares a write to a collection its module does not own.

**Tests.**
- `T-DEP-01.1`–`.6` `tests/spec/test_dependency_manifest.py`.

---

## 2. The module graph — `DEP-02`

**Objective.** Fix the coarse shape once, so that a per-requirement edge that contradicts it is visible immediately.

**Constraints.** Modules and their permitted consumption. An arrow means "may call the public API of" or "may consume events from".

```
                    ┌──────────────┐
                    │  foundations │  core · shared · infra interfaces
                    └──────┬───────┘
        ┌──────────┬───────┴────┬─────────────┬──────────────┐
        ▼          ▼            ▼             ▼              ▼
   ┌────────┐ ┌────────┐  ┌──────────┐  ┌───────────┐  ┌──────────┐
   │  auth  │ │   ai   │  │connectors│  │  profile  │  │  admin   │
   └───┬────┘ └───┬────┘  └────┬─────┘  └─────┬─────┘  └────▲─────┘
       │          │            │              │             │ reads every
       │          ├────────────┴──────┐       │             │ public API
       │          ▼                   ▼       ▼             │
       │     ┌─────────┐          ┌──────────────┐          │
       │     │ resume  │─────────▶│     jobs     │          │
       │     └─────────┘  (none)  └──────┬───────┘          │
       │          │ ResumeExtracted      │ JobsIngested     │
       │          ▼                      ▼                  │
       │     ┌─────────┐          ┌──────────────┐          │
       │     │ profile │─────────▶│   matching   │          │
       │     └─────────┘ Profile  └──────┬───────┘          │
       │                 Updated         │ explain payload  │
       │                                 ▼                  │
       │                          ┌──────────────┐          │
       │                          │    apply     │          │
       │                          └──────┬───────┘          │
       │                                 │ PackApproved     │
       │                                 │ AppliedConfirmed │
       │                                 ▼                  │
       │                          ┌──────────────┐          │
       └─────────────────────────▶│   tracker    │──────────┘
         user tz + settings       └──────┬───────┘
                                         │ ApplicationStatusChanged
                                         ▼
                                  ┌──────────────┐
                                  │notifications │
                                  └──────────────┘
```

Rules the picture encodes:
- `ai` and `connectors` are **leaves**. They import nothing from `modules/*` and depend only on foundations (HR-5, `01-foundations.md` §4).
- `resume` does **not** write the profile. It publishes `ResumeExtracted`; `profile` stages it (`04-resume-pipeline.md` §4, `AC-RES-03.8`).
- `matching` reads `profile` and `jobs` and writes only `match_scores`. It is downstream of both and upstream of `apply`.
- `admin` reads every module's public API and writes only `feature_flags` and audit rows. Nothing depends on `admin`, which is why it can be built late in any phase without blocking.
- `notifications` is the terminal consumer. Nothing in the product depends on it except the user, which is why its failure degrades rather than blocks.
- The one upward edge is `auth → tracker/notifications` for the user's timezone and notification settings, taken through `AuthService`, never by reading `users` directly.

**Acceptance criteria.**
- `AC-DEP-02.1` Every edge in `dependencies.yaml` projects onto an edge in this module graph; a requirement-level edge between modules with no module-level edge fails.
- `AC-DEP-02.2` `ai` and `connectors` have no outgoing edges to any module (leaf property, shared with the import contracts).
- `AC-DEP-02.3` No module both reads and writes another module's collections.
- `AC-DEP-02.4` Removing `admin` from the graph leaves every other module's dependencies satisfied — the property that lets admin slip a phase without cascading.

**Tests.** `T-DEP-02.1`–`.4` `tests/spec/test_module_graph.py`.

---

## 3. Track closure — `DEP-03`

**Objective.** Prove R1 can be built, shipped and operated with no R2 or R3 code in the repository.

**Constraints.**
- **The closure rule:** for every requirement with `track: R1`, the transitive closure of `requires` contains only `track: R1` entries. An R1 item that needs an R2 item is a scope error, and the fix is to move the dependency into R1 or to cut the dependent item — never to build "just a bit" of the R2 item.
- The reverse direction is unrestricted: R2 and R3 requirements may and usually do depend on R1 ones.
- The rule applies to the **manifest**, not to prose. A section that mentions an R2 feature as future context is fine; an acceptance criterion that cannot pass without R2 code is not.
- `MATCH-02b` is the one deliberate straddle and is modelled explicitly: `track: "R1 code, R2 on"`, `phase: P4`, with an `enabled_in: R2` field. Its *code* is closed under R1; only its production flag is R2. The closure check treats it as R1 (`00 §2.6`).

**Acceptance criteria.**
- `AC-DEP-03.1` The transitive closure of every R1 requirement contains no R2 or R3 requirement. The check prints the offending path if it fails.
- `AC-DEP-03.2` `MATCH-02b`'s closure is R1-only, and its `enabled_in: R2` is the only mechanism deferring it.
- `AC-DEP-03.3` Deleting every R2 and R3 section from the specification leaves every R1 acceptance criterion still resolvable (no R1 criterion references an R2/R3 section as a precondition).
- `AC-DEP-03.4` No R1 acceptance criterion names a test that lives only in an R2/R3 module's test file.

**Tests.** `T-DEP-03.1`–`.4` `tests/spec/test_track_closure.py`.

---

## 4. Phase closure, and the build order — `DEP-04`

**Objective.** Prove each phase can be built from what earlier phases produced, and derive the build order rather than asserting it.

**Constraints.**
- **The phase rule:** for every requirement, every entry in its `requires` has a phase **earlier than or equal to** its own. An equal phase is allowed (two requirements built together in one phase); a later phase is a violation.
- The build order is the topological sort of the graph, tie-broken by phase then by requirement ID. It is generated, not written; the phase table in `00 §4` is checked against it, and a disagreement fails CI rather than being reconciled by hand.
- A requirement may be split across phases only by splitting the requirement (as `RES-02a`/`RES-02b` already are). "Half of X in P2" is not expressible and must not be.
- The generated order is published as `docs/spec/BUILD-ORDER.md` on every push to `develop`, so the next thing to build is always a file rather than a judgement.

**Inputs.** The manifest; the phase table.

**Outputs.** `BUILD-ORDER.md`; the CI check.

**Acceptance criteria.**
- `AC-DEP-04.1` Every requirement's dependencies sit in an earlier or equal phase; a violation prints requirement, phase, dependency, and dependency phase.
- `AC-DEP-04.2` The topological order is stable across runs (deterministic tie-breaking).
- `AC-DEP-04.3` The phase assignment in the manifest matches `00 §4`'s deliverables column for every requirement named there.
- `AC-DEP-04.4` `BUILD-ORDER.md` regenerates on every push to `develop` and is byte-identical to the committed copy, or CI fails.
- `AC-DEP-04.5` The first ten entries of the build order are all `phase: P0` or `P1` — a sanity check that catches an inverted graph.

**Tests.** `T-DEP-04.1`–`.5` `tests/spec/test_phase_closure.py`.

---

## 5. The four phase-closure violations found in v2.0, and their fixes — `DEP-05`

**Objective.** Record what the first run of this check found, so the fixes are traceable and the check's value is demonstrable rather than theoretical. Two were visible on a careful read; two were not, and are the reason the manifest exists rather than a convention.

### 5.1 Violation 1 — email transport was owned by a phase that runs last

**Found:** `AUTH-01`, `AUTH-03` and `AUTH-05` (phase **P1**) all send email — verification, the "someone tried to register" notice, password reset. Email was specified only as part of `NOTIF-02a` (phase **P6**). P1 therefore could not be built as specified, and the likely improvisation is an inline SMTP call in `modules/auth` that `notifications` later duplicates.

**Fix, in v2.1:** the **transport** is extracted from `NOTIF-02a` into foundations as `FOUND-16` (`01-foundations.md` §16), owned by `infra/email`, available from P1. `NOTIF-02a` keeps what is genuinely its own: reminder templates, channel preferences, the in-app inbox, and delivery accounting. The manifest models this as `AUTH-01 → FOUND-16` and `NOTIF-02a → FOUND-16`, both phase-legal.

**Why this is the right cut, not a workaround:** sending a templated message to one address is infrastructure, like storage or the queue. Deciding *which* messages a user receives, when, and through which channel is a product concern. v2.0 had them in one box because both were "email".

### 5.2 Violation 2 — the embedding codec was needed two phases before it was scheduled

**Found:** `PROF-01` stores `profiles.embedding` in phase **P2**, and every stored embedding is quantized by the codec specified in `DATA-06` (`17-data-model.md` §6), which the phase table did not assign to any phase — it read as a capacity concern for later. Storing float32 embeddings in P2 and quantizing in P4 is a data migration over every profile and job, for no reason.

**Fix, in v2.1:** `DATA-06`'s codec (`shared/embedding.py`) is assigned to **P0**, alongside the other `shared/` primitives it belongs with, and is listed in P0's deliverables in `00 §4`. The capacity *measurement* half of `DATA-06` stays where it was, as an ongoing nightly job. The manifest records `PROF-01 → DATA-06` and `JOB-05 → DATA-06`.

### 5.3 Violation 3 — saved searches depended on the digest, in the wrong direction

**Found by the check, not by reading.** `JOB-07` (saved searches, phase **S2**) was written as "ships with the digest", and `NOTIF-04` (weekly digest) sits in **S4**. Modelled honestly that is S2 depending on S4 — a violation.

**Fix, in v2.1:** the edge is reversed, because the dependency was stated backwards. A saved search is a stored filter set and is useful on its own; it stores a `notify` flag that nothing yet reads. `NOTIF-04` is what reads it, so `NOTIF-04 → JOB-07` (S4 depending on S2), which is phase-legal and matches how the two features actually relate. `00 §4.1` keeps `JOB-07` in S2.

### 5.4 Violation 4 — the follow-up draft needed interview history that did not exist yet

**Found by the check.** `APPLY-09` (the follow-up email draft) was placed in **P5** with the rest of the apply engine, but its prompt reads the application's interview rounds and contacts — `TRACK-03`, phase **P6**.

**Fix, in v2.1:** `APPLY-09` moves to **P6**. It belongs there on product grounds too: the follow-up draft is the action a follow-up reminder prompts, and reminders are P6. P5 ends at "confirms they applied", which is exactly where the exit sentence's apply clause ends.

### 5.5 What the check did not find

For completeness, because a check that only ever reports problems is as suspect as one that never does: **track closure passed on the first run with no violations** — no R1 requirement transitively depends on an R2 or R3 requirement — and every requirement-level edge projects onto a permitted module-level edge. All four findings are phase-order, which is the dimension v2.0 had no way to express. The first ten entries of the generated build order are all P0, and the manifest is acyclic across 149 entries.

**Acceptance criteria.**
- `AC-DEP-05.1` `AUTH-01`, `AUTH-03` and `AUTH-05` depend on `FOUND-16`, which is phase P0, and no auth requirement depends on any `NOTIF-*` requirement.
- `AC-DEP-05.2` `modules/auth` contains no email client; it calls the `EmailSender` interface from `infra/email` (import check).
- `AC-DEP-05.3` `PROF-01` and `JOB-05` depend on `DATA-06`, which is phase P0.
- `AC-DEP-05.4` No embedding is ever stored unquantized; a float32 vector reaching the persistence layer raises.
- `AC-DEP-05.5` `NOTIF-04` depends on `JOB-07` and not the reverse; `JOB-07`'s manifest entry has no `NOTIF-*` dependency.
- `AC-DEP-05.6` `APPLY-09` is phase P6 and `00 §4` lists it under P6's deliverables.
- `AC-DEP-05.7` All four violations appear in `docs/spec/CONSISTENCY-REPORT-v2.1.md` with their resolutions, and the report is referenced from this section.

**Tests.**
- `T-DEP-05.1`/`.3` `tests/spec/test_phase_closure.py` (shared).
- `T-DEP-05.2` `tests/spec/test_email_ownership.py`.
- `T-DEP-05.4` `tests/unit/test_embedding_quantization.py` (shared with `T-DATA-06.1`).
- `T-DEP-05.5`/`.6` `tests/spec/test_phase_closure.py` (shared).
- `T-DEP-05.7` `tests/spec/test_consistency_report.py`.

---

## 6. The agent handoff bundle — `DEP-06`

**Objective.** Replace "give the agent one module file" with a computed answer to "which files does this agent need".

**Constraints.**
- For a requirement `R`, the bundle is: `README.md`, `01-foundations.md`, `17-data-model.md`, the file owning `R`, and the file owning every requirement in `R`'s **direct** `requires` set — plus `18-dependency-closure.md` itself when the agent is expected to add a manifest entry.
- The transitive closure is deliberately **not** included: a direct dependency is a contract the agent must satisfy; a transitive one is that dependency's problem. Handing over ten files reproduces the reading exercise this file exists to remove.
- `make bundle REQ=MATCH-05` prints the file list and the exact section anchors within them, so the handoff is copy-pasteable.
- The bundle for every R1 requirement must be **seven files or fewer**. A requirement needing more is too large and is split — this is a design constraint on the specification, not only a convenience for the agent.
  - **Amended in v2.1.1.** The limit was five, which sixteen R1 requirements exceeded on the first run of `AC-DEP-06.2`. Three files (`README.md`, `01-foundations.md`, `17-data-model.md`) are in every bundle before a requirement names anything, so five allowed a requirement one cross-module dependency. Pack generation (`APPLY-02`) legitimately reads the profile, the match explain payload and the AI layer, and splitting it to satisfy an arithmetic limit would have made the specification worse. Seven is the observed maximum and still catches a requirement that balloons.

**Inputs.** The manifest; the requirement ID.

**Outputs.** `make bundle REQ=<id>`; a `bundle` field per requirement in `SPEC-METADATA.json`.

**Acceptance criteria.**
- `AC-DEP-06.1` `make bundle REQ=<id>` prints an existing file list plus section anchors for every requirement in the manifest.
- `AC-DEP-06.2` No R1 requirement's bundle exceeds seven files.
- `AC-DEP-06.3` Every file named in a bundle exists and every anchor resolves to a heading.
- `AC-DEP-06.4` `SPEC-METADATA.json` carries the computed bundle for every requirement.

**Tests.** `T-DEP-06.1`–`.4` `tests/spec/test_handoff_bundle.py`.
