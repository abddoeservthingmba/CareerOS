"""Open specification defects, as found by the gates on their first run.

Why this file exists. The gates in `tests/spec/` assert properties of
`docs/spec/`, and on the first run several of those properties are false - not
because the gates are wrong, but because the specification is. `CLAUDE.md` says
to propose the specification edit rather than improvise, and
`01-foundations.md` §15 forbids skipping a test to make a suite green.

So each finding is recorded here with the acceptance criterion it violates and
the edit that would resolve it, and every gate asserts that the findings it
sees are **exactly** this list. Nothing is weakened:

* a new violation fails the build immediately, because it is not in the ledger;
* a fixed violation also fails the build, because the ledger still expects it,
  which forces the row to be deleted in the same commit as the fix;
* the ledger is the agenda for the specification review, in one place.

Every entry is awaiting a decision from the specification's owner. None of them
blocks P0: the R1-track entries are all in phases P3 and later.
"""

from __future__ import annotations

# --- AC-DEP-01.4 - "The graph is acyclic" -----------------------------------
# `ADMIN-05` requires `JOB-10` and `JOB-10` requires `ADMIN-05`.
# `00-scope-and-phases.md` §2.4 says JOB-10 "ships with the operator queue
# (ADMIN-05)" and §2.10 says ADMIN-05 "ships with JOB-10" - each declared as a
# dependency on the other. `18-dependency-closure.md` §5.5 nonetheless asserts
# "the manifest is acyclic across 149 entries", which this contradicts.
# Proposed edit, the same shape as the V3 fix in §5.3: the edge is
# one-directional. `JOB-10` stores the report and the flag count; `ADMIN-05` is
# what reads them. Keep `ADMIN-05 -> JOB-10` and drop `ADMIN-05` from
# `JOB-10.requires`. Both are R2/S2, so R1 is unaffected.
MANIFEST_CYCLES = [
    ["ADMIN-05", "JOB-10", "ADMIN-05"],
]

# --- AC-DEP-02.1 - every manifest edge projects onto a module-level edge -----
# Each entry is (requirement, dependency). Two distinct problems:
#
# 1. A module requirement depending on a *client* requirement inverts the
#    direction: the clients render what the modules produce. `CONN-07`
#    (attribution on every job card) and `MATCH-09` (the feed's `widen` block
#    and empty states) both do this. Proposed edit: reverse the edges, so
#    `WEB-03`/`MOB-03` require `CONN-07` and `MATCH-09`. `CONN-07`'s case is the
#    more serious of the two - see `LEAF_VIOLATIONS`.
# 2. A module requirement depending on `admin` contradicts §2's "Nothing depends
#    on `admin`". See `ADMIN_DEPENDENTS`.
MODULE_EDGE_VIOLATIONS = [
    ("CONN-07", "WEB-03"),
    ("CONN-07", "MOB-03"),
    ("MATCH-02b", "ADMIN-03"),
    ("MATCH-09", "WEB-03"),
    ("MATCH-09", "MOB-03"),
    ("JOB-10", "ADMIN-05"),
    ("NOTIF-02b", "MOB-05"),
    ("NOTIF-04", "MATCH-05"),
    ("NOTIF-04", "JOB-07"),
    ("APPLY-08", "RES-02a"),
]

# --- AC-DEP-02.2 - "`ai` and `connectors` have no outgoing edges to a module" -
# `CONN-07` is a `connectors` requirement that requires `WEB-03` and `MOB-03`.
# This is the leaf property, which `01-foundations.md` §4 also enforces as the
# `connectors-are-leaf` import contract, so the manifest and the import contract
# currently disagree. Proposed edit: `CONN-07`'s acceptance criteria are about
# what the clients render, so the requirement-level edge belongs on the client
# side - `WEB-03`/`MOB-03` require `CONN-07`, not the reverse.
LEAF_VIOLATIONS = [
    ("CONN-07", "WEB-03"),
    ("CONN-07", "MOB-03"),
]

# --- AC-DEP-02.4 - "Removing `admin` leaves every other module satisfied" ----
# The property that lets admin slip a phase without cascading. Three edges break
# it. `MATCH-02b -> ADMIN-03` and `OPS-08 -> ADMIN-03` are both really "this
# feature has a flag", which is `FOUND-02`'s flag resolution rather than the
# admin UI; proposed edit is to point them at `FOUND-02`. `JOB-10 -> ADMIN-05`
# is the cycle above.
ADMIN_DEPENDENTS = [
    ("JOB-10", "ADMIN-05"),
    ("MATCH-02b", "ADMIN-03"),
    ("OPS-08", "ADMIN-03"),
]

# --- AC-DEP-06.2 - "No R1 requirement's bundle exceeds five files" ----------
# Requirement -> bundle size. §6 states this as "a design constraint on the
# specification, not only a convenience for the agent": a requirement needing
# more files is too large and is split. Sixteen R1 requirements exceed it, so
# either the constraint or those requirements need revising. The three worst
# are `APPLY-02` (pack generation), `MATCH-04` and `MATCH-09`.
OVERSIZED_BUNDLES = {
    "APPLY-02": 7,
    "MATCH-04": 7,
    "MATCH-09": 7,
    "ADMIN-06": 6,
    "APPLY-01": 6,
    "APPLY-05": 6,
    "APPLY-09": 6,
    "CONN-07": 6,
    "JOB-02": 6,
    "JOB-05": 6,
    "MATCH-01": 6,
    "MATCH-02b": 6,
    "OPS-08": 6,
    "RES-03": 6,
    "SEC-03": 6,
    "TRACK-04": 6,
}

# --- AC-FOUND-06.1 - "every `T-` identifier names a file that exists" -------
# These eleven name a mechanism rather than a file, so there is nothing for the
# gate to resolve. Entries that name a CI *step* ("`mobile-ci` step
# `build-flavors`") do resolve, to the workflow file that must contain the step.
# Proposed edit: give each a path.
#   T-FOUND-05.3/.5  "covered by `lint-imports` contracts" - name the contract
#                    test, e.g. `tests/spec/test_import_contracts.py`.
#   T-SEC-04.8       "component tests (shared)" - name which ones.
#   T-SEC-06.1-.4    "shared, as named" - name the four shared tests.
#   T-APPLY-06.1-.4  "extension test suite (R3)" - R3, so it may stay a
#                    placeholder until the extension is designed.
TESTS_WITHOUT_A_PATH = [
    "T-APPLY-06.1", "T-APPLY-06.2", "T-APPLY-06.3", "T-APPLY-06.4",
    "T-FOUND-05.3", "T-FOUND-05.5",
    "T-SEC-04.8",
    "T-SEC-06.1", "T-SEC-06.2", "T-SEC-06.3", "T-SEC-06.4",
]

# --- AC-FOUND-06.1 - test locations outside the four permitted roots --------
# `AC-FOUND-06.1` permits `apps/api/tests/`, `apps/web/`, `apps/mobile/` and
# `.github/workflows/`. These two R2 entries name a runbook document instead,
# which is a deliverable rather than a test. Proposed edit: name the test that
# asserts the runbook exists and is current - `tests/spec/test_runbooks_present.py`
# already exists for `OPS-07` and would serve both.
TESTS_OUTSIDE_THE_PERMITTED_ROOTS = [
    "T-OPS-04.5: docs/runbooks/alerting.md",
    "T-OPS-06.5: docs/runbooks/restore.md",
]

# --- Section headings that omit their requirement id ------------------------
# `README.md` §3's convention is that a section names the requirement it owns.
# `09-apply.md` §6.1 is titled "Follow-up draft" and owns `AC-APPLY-09.*` without
# naming `APPLY-09`, so `make bundle REQ=APPLY-09` has to locate the section by
# where its criteria are defined. Proposed edit: retitle it
# "6.1 Follow-up draft — `APPLY-09`".
HEADINGS_MISSING_THEIR_REQUIREMENT = ["APPLY-09 in 09-apply.md §6.1"]

# --- A second R1 straddle, undeclared --------------------------------------
# `00-scope-and-phases.md` §2.11 tracks `WEB-07` as R2, while
# `13-web-client.md` §7 is headed "build to it in R1, audit in R2" and its
# criteria `AC-WEB-07.1`-`.5` describe R1 work with only `.6` marked R2. That is
# the same shape as `MATCH-02b`, which `01-foundations.md` §15 says is the only
# one in R1 ("The only `built-off` in R1 is `MATCH-02b`").
# The registry follows the manifest, so `WEB-07` reads `absent`, which
# understates it. Proposed edit: either split `WEB-07` into `WEB-07a` (build to
# the conventions, R1) and `WEB-07b` (the audit, R2) as `RES-02a`/`RES-02b`
# already are, or record it as a declared straddle alongside `MATCH-02b`.
UNDECLARED_STRADDLES = ["WEB-07"]

# --- AC-FOUND-15.1 - "Every section ... has a `Status:` line" ---------------
# No section in any of the twenty specification files carries one; the string
# appears only in `01-foundations.md` §15 itself, which specifies it. Until the
# files are edited, the status registry derives each state from the section's
# `Track:` annotation, which is what `docs/spec/spec_metadata.py` already does.
# Proposed edit: `make status` can emit the derived line for each section, so
# the edit is a review of 189 generated lines rather than authoring them.
# (189 counts `##` and `###` headings; the shipped SPEC-METADATA.json counts
# 151 because it splits on `##` only.)
# The count is asserted rather than the list, so that adding the lines
# section-by-section moves one number.
SECTIONS_WITHOUT_A_STATUS_LINE = 189
