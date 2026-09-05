"""T-DEP-03.1-.4 - track closure (`18-dependency-closure.md` §3).

Prove R1 can be built, shipped and operated with no R2 or R3 code in the
repository. All four pass as shipped: the specification's claim in §5.5 that
"track closure passed on the first run with no violations" is confirmed.
"""

from __future__ import annotations


def test_r1_closure_contains_only_r1(manifest):
    """AC-DEP-03.1 - prints the offending path if it fails."""
    from specgate import graph

    violations = graph.track_closure_violations(manifest)
    assert violations == [], "\n".join(str(v) for v in violations)


def test_match_02b_is_the_only_straddle(manifest):
    """AC-DEP-03.2 - its closure is R1-only and `enabled_in: R2` is the only
    mechanism deferring it."""
    straddles = [e.id for e in manifest if e.enabled_in]
    assert straddles == ["MATCH-02b"]

    entry = manifest["MATCH-02b"]
    assert entry.track == "R1"
    assert entry.enabled_in == "R2"
    assert entry.phase == "P4"
    off_track = sorted(d for d in manifest.closure("MATCH-02b") if manifest[d].track != "R1")
    assert off_track == [], f"MATCH-02b depends on non-R1 work: {off_track}"


def test_deleting_r2_and_r3_leaves_r1_resolvable(manifest):
    """AC-DEP-03.3 - no R1 criterion references an R2/R3 section as a precondition."""
    r1 = {e.id for e in manifest if e.track == "R1"}
    dangling = sorted(
        f"{entry.id} -> {target}"
        for entry in manifest
        if entry.track == "R1"
        for target in entry.requires
        if target not in r1
    )
    assert dangling == [], f"R1 requirements needing non-R1 work: {dangling}"


def test_no_r1_criterion_names_a_test_in_an_r2_only_file(manifest, spec):
    """AC-DEP-03.4 - an R1 criterion may not name a test that lives only in an
    R2/R3 module's test file.

    R2/R3 requirements are `absent` (`01-foundations.md` §15), so no file exists
    for them; a shared R1 test must therefore be defined by an R1 requirement.
    """
    r2_r3 = {e.id for e in manifest if e.track != "R1"}
    offenders: list[str] = []
    for tid, definition in spec.tests.items():
        requirement = tid[2:].rsplit(".", 1)[0]
        if requirement in r2_r3:
            continue
        for other in definition.shared_with:
            other_requirement = other[2:].rsplit(".", 1)[0]
            if other_requirement in r2_r3:
                offenders.append(f"{tid} resolves via {other} ({other_requirement}, R2/R3)")
    assert offenders == [], "\n".join(offenders)
