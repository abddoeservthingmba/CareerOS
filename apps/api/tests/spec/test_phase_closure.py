"""T-DEP-04.1-.5 - phase closure and the build order.

Also carries T-DEP-05.1/.3/.5/.6 (shared), which assert that the four
phase-closure violations v2.0 contained are fixed in v2.1.
"""

from __future__ import annotations

from specgate import graph


def test_dependencies_sit_in_an_earlier_or_equal_phase(manifest):
    """AC-DEP-04.1 - prints requirement, phase, dependency and dependency phase."""
    violations = graph.phase_closure_violations(manifest)
    assert violations == [], "\n".join(str(v) for v in violations)


def test_the_order_is_deterministic(manifest):
    """AC-DEP-04.2 - stable across runs."""
    assert graph.build_order(manifest) == graph.build_order(manifest)
    order = graph.build_order(manifest)
    assert len(order) == len(set(order)) == len(manifest.ids)


def test_phase_assignment_matches_the_phase_table(manifest):
    """AC-DEP-04.3 - against `00-scope-and-phases.md` §4's deliverables column."""
    # The deliverables column names these explicitly; they are the ones a
    # mis-phased manifest would most likely get wrong.
    expected = {
        "FOUND-16": "P0",  # §4 P0: "FOUND-16 email transport"
        "DATA-06": "P0",  # §4 P0: "the DATA-06 embedding quantization codec"
        "FOUND-15": "P0",  # §4 P0: "FOUND-15 status registry"
        "MATCH-09": "P4",  # §2.11: "MATCH-09 ... phase P4"
        "APPLY-09": "P6",  # §4 P6: "APPLY-09 ... moved from P5"
        "TRACK-03": "P6",
        "AUTH-01": "P1",
        "RES-03": "P2",
        "JOB-03": "P3",
    }
    actual = {rid: manifest[rid].phase for rid in expected}
    assert actual == expected


def test_build_order_matches_the_committed_copy(repo, manifest):
    """AC-DEP-04.4 - byte-identical, or CI fails."""
    committed = (repo / "docs" / "spec" / "BUILD-ORDER.md").read_text(encoding="utf-8")
    assert graph.render_build_order(manifest) == committed, (
        "BUILD-ORDER.md is stale; regenerate with `make build-order`"
    )


def test_the_first_ten_entries_are_early_phases(manifest):
    """AC-DEP-04.5 - a sanity check that catches an inverted graph."""
    first_ten = graph.build_order(manifest)[:10]
    phases = {manifest[rid].phase for rid in first_ten}
    assert phases <= {"P0", "P1"}, f"first ten are {first_ten} in phases {sorted(phases)}"


# --- DEP-05: the four v2.0 violations, asserted fixed ------------------------


def test_email_transport_is_foundations_not_notifications(manifest):
    """AC-DEP-05.1 (V1) - auth depends on FOUND-16, never on a NOTIF requirement."""
    assert manifest["FOUND-16"].phase == "P0"
    for requirement in ("AUTH-01", "AUTH-03", "AUTH-05"):
        assert "FOUND-16" in manifest[requirement].requires
    notif_edges = sorted(
        f"{e.id} -> {t}"
        for e in manifest
        if e.module == "auth"
        for t in e.requires
        if t.startswith("NOTIF-")
    )
    assert notif_edges == []


def test_the_embedding_codec_is_phase_p0(manifest):
    """AC-DEP-05.3 (V2) - PROF-01 and JOB-05 depend on DATA-06, which is P0."""
    assert manifest["DATA-06"].phase == "P0"
    assert "DATA-06" in manifest["PROF-01"].requires
    assert "DATA-06" in manifest["JOB-05"].requires


def test_the_digest_depends_on_saved_searches(manifest):
    """AC-DEP-05.5 (V3) - NOTIF-04 -> JOB-07, and not the reverse."""
    assert "JOB-07" in manifest["NOTIF-04"].requires
    assert not [t for t in manifest["JOB-07"].requires if t.startswith("NOTIF-")]
    assert manifest["JOB-07"].phase == "S2"


def test_the_followup_draft_moved_to_p6(manifest):
    """AC-DEP-05.6 (V4) - APPLY-09 is P6, with TRACK-03 available."""
    assert manifest["APPLY-09"].phase == "P6"
    assert "TRACK-03" in manifest["APPLY-09"].requires
    assert manifest["TRACK-03"].phase == "P6"
