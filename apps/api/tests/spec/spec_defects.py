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

# Resolved in v2.1.1, in the same commit that deleted their rows here:
#
#   AC-DEP-01.4  the ADMIN-05 <-> JOB-10 cycle - JOB-10 no longer requires
#                ADMIN-05, since JOB-10 stores the report and ADMIN-05 reads it.
#   AC-DEP-02.2  CONN-07 required WEB-03/MOB-03, breaking the connectors leaf
#                property and contradicting the `connectors-are-leaf` import
#                contract. Attribution rendering is a client criterion; the edge
#                is gone.
#   AC-DEP-02.4  MATCH-02b and OPS-08 required ADMIN-03 for what is really
#                FOUND-02's flag resolution, and JOB-10 required ADMIN-05.
#                Nothing depends on admin now.
#   AC-FOUND-06.1  eleven T- identifiers named a mechanism rather than a file,
#                and two named a runbook. All thirteen now name a test path.
#   AC-DEP-06.2  the five-file bundle limit, amended to seven with the reason
#                recorded in 18-dependency-closure.md §6. Three files are in
#                every bundle before a requirement names anything, so five
#                allowed one cross-module dependency.
#   README §3    09-apply.md §6.1 now names APPLY-09 in its heading.

# --- A second R1 straddle, undeclared --------------------------------------
# `00-scope-and-phases.md` §2.11 tracks `WEB-07` (accessibility) as R2, while
# `13-web-client.md` §7 is headed "build to it in R1, audit in R2" and its
# criteria `AC-WEB-07.1`-`.5` describe R1 work with only `.6` marked R2. That is
# the same shape as `MATCH-02b`, which `01-foundations.md` §15 says is the only
# one in R1 ("The only `built-off` in R1 is `MATCH-02b`"). The registry follows
# the manifest, so `WEB-07` reads `absent`, which understates it.
#
# Left open deliberately: the fix is a product decision, not a mechanical edit.
# Either split `WEB-07` into `WEB-07a` (build to the conventions, R1) and
# `WEB-07b` (the audit, R2) as `RES-02a`/`RES-02b` already are, or declare a
# second straddle and amend §15's "only `MATCH-02b`" sentence. It costs nothing
# before P4, when the web client's accessibility work starts.
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
