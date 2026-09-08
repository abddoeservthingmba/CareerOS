"""T-DEP-02.1-.4 - the module graph (`18-dependency-closure.md` §2)."""

from __future__ import annotations

from specgate import graph


def test_every_edge_projects_onto_the_module_graph(manifest):
    """AC-DEP-02.1 - a requirement-level edge between modules with no
    module-level edge fails."""
    violations = graph.module_edge_violations(manifest)
    assert violations == [], "\n".join(str(v) for v in violations)


def test_ai_and_connectors_are_leaves(manifest):
    """AC-DEP-02.2 - the leaf property, shared with the import contracts."""
    violations = graph.leaf_violations(manifest)
    assert violations == [], "\n".join(str(v) for v in violations)


def test_no_module_reads_and_writes_another_modules_collections(manifest):
    """AC-DEP-02.3."""
    assert graph.read_write_conflicts(manifest) == []


def test_admin_can_be_removed(manifest):
    """AC-DEP-02.4 - the property that lets admin slip a phase."""
    broken = graph.satisfied_without("admin", manifest)
    assert broken == [], "\n".join(broken)


def test_the_leaf_modules_are_the_ones_the_spec_names():
    """§2's rules are transcribed, so the transcription itself is asserted."""
    assert graph.LEAF_MODULES == ("ai", "connectors")
    assert graph.MODULE_EDGES["ai"] == frozenset()
    assert graph.MODULE_EDGES["connectors"] == frozenset()
    # "`matching` reads `profile` and `jobs` ... and is upstream of `apply`."
    assert {"profile", "jobs"} <= graph.MODULE_EDGES["matching"]
    assert "matching" in graph.MODULE_EDGES["apply"]
    # "`resume` does not write the profile."
    assert "profile" in graph.MODULE_EDGES["resume"]
