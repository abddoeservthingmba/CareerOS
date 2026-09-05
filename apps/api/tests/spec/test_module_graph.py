"""T-DEP-02.1-.4 - the module graph (`18-dependency-closure.md` §2)."""

from __future__ import annotations

from specgate import graph

from . import spec_defects


def test_every_edge_projects_onto_the_module_graph(manifest):
    """AC-DEP-02.1 - a requirement-level edge between modules with no
    module-level edge fails.

    Currently ten edges do not project. See `spec_defects.MODULE_EDGE_VIOLATIONS`.
    """
    found = [(v.requirement, v.dependency) for v in graph.module_edge_violations(manifest)]
    assert found == spec_defects.MODULE_EDGE_VIOLATIONS, (
        "module-level edges changed; update dependencies.yaml or the ledger.\n"
        + "\n".join(str(v) for v in graph.module_edge_violations(manifest))
    )


def test_ai_and_connectors_are_leaves(manifest):
    """AC-DEP-02.2 - the leaf property, shared with the import contracts.

    Currently false for `CONN-07`. See `spec_defects.LEAF_VIOLATIONS`.
    """
    found = [(v.requirement, v.dependency) for v in graph.leaf_violations(manifest)]
    assert found == spec_defects.LEAF_VIOLATIONS, (
        "leaf violations changed; `ai` and `connectors` must import no module.\n"
        + "\n".join(str(v) for v in graph.leaf_violations(manifest))
    )


def test_no_module_reads_and_writes_another_modules_collections(manifest):
    """AC-DEP-02.3."""
    assert graph.read_write_conflicts(manifest) == []


def test_admin_can_be_removed(manifest):
    """AC-DEP-02.4 - the property that lets admin slip a phase.

    Currently false for three edges. See `spec_defects.ADMIN_DEPENDENTS`.
    """
    broken = graph.satisfied_without("admin", manifest)
    found = [tuple(line.split(" requires ")[0:1] + [line.split(" requires ")[1].split(" ")[0]])
             for line in broken]
    assert [tuple(pair) for pair in found] == spec_defects.ADMIN_DEPENDENTS, (
        "dependents of admin changed:\n" + "\n".join(broken)
    )


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
