"""T-DEP-01.1-.6 - the dependency manifest (`18-dependency-closure.md` §1)."""

from __future__ import annotations

import pytest

from specgate import graph
from specgate.manifest import MODULES, TRACKS, ManifestError, load

from . import spec_defects


def test_every_requirement_has_exactly_one_entry(manifest, spec):
    """AC-DEP-01.1 - and every entry names an id that exists in `00` §2."""
    ids = manifest.ids
    assert len(ids) == 149, f"expected 149 entries, found {len(ids)}"

    # `00-scope-and-phases.md` §2 is the track table. Every requirement it names
    # must appear here, and vice versa. The table is prose, so the check is that
    # every manifest id has acceptance criteria somewhere in the spec, which is
    # the same population by `README.md` §3.
    def has_criteria(requirement: str) -> bool:
        base = requirement.rstrip("abc") if requirement[-1] in "abc" else requirement
        return any(ac.startswith(f"AC-{base}.") for ac in spec.criteria)

    unknown = sorted(entry.id for entry in manifest if not has_criteria(entry.id))
    assert unknown == [], f"manifest entries with no acceptance criteria: {unknown}"


def test_track_and_module_are_valid(manifest):
    """AC-DEP-01.2 - track matches the table; module is a real module."""
    bad_track = [e.id for e in manifest if e.track not in TRACKS]
    assert bad_track == [], f"entries with an unknown track: {bad_track}"

    bad_module = sorted({e.module for e in manifest} - MODULES)
    assert bad_module == [], f"entries with an unknown module: {bad_module}"


def test_no_dangling_requires(manifest):
    """AC-DEP-01.3 - every `requires` target exists as an entry."""
    dangling = sorted(
        f"{entry.id} -> {target}"
        for entry in manifest
        for target in entry.requires
        if target not in manifest
    )
    assert dangling == [], f"dangling edges: {dangling}"


def test_graph_is_acyclic(manifest):
    """AC-DEP-01.4 - a cycle fails with the cycle printed.

    Currently false. See `spec_defects.MANIFEST_CYCLES`.
    """
    found = [list(cycle) for cycle in manifest.cycles()]
    assert found == spec_defects.MANIFEST_CYCLES, (
        "manifest cycles changed; update docs/spec/dependencies.yaml or the ledger.\n"
        f"found: {found}\nledger: {spec_defects.MANIFEST_CYCLES}"
    )


def test_cross_module_edges_are_permitted(manifest):
    """AC-DEP-01.5 - a cross-module edge matches a permitted import or event.

    Shares its subject with `AC-DEP-02.1`; asserted there against the module
    graph, and here against the ledger so a new edge fails in both places.
    """
    found = [(v.requirement, v.dependency) for v in graph.module_edge_violations(manifest)]
    assert found == spec_defects.MODULE_EDGE_VIOLATIONS


def test_no_write_outside_the_owning_module(manifest):
    """AC-DEP-01.6 - no requirement declares a write to another module's collection."""
    assert graph.read_write_conflicts(manifest) == []


def test_a_malformed_manifest_is_rejected(tmp_path):
    """The strict reader is what makes AC-DEP-01.1-.3 meaningful."""
    bad = tmp_path / "dependencies.yaml"
    bad.write_text("FOO-01:\n  track: R1\n  phase: P0\n  moduel: core\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="unknown key 'moduel'"):
        load(bad)

    incomplete = tmp_path / "incomplete.yaml"
    incomplete.write_text("FOO-01:\n  track: R1\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="missing required key"):
        load(incomplete)
