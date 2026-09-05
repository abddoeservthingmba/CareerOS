"""T-DEP-06.1-.4 - the agent handoff bundle (`18-dependency-closure.md` §6)."""

from __future__ import annotations

import json

import pytest

from specgate import bundle as bundle_mod


def test_every_requirement_has_a_bundle(manifest, spec, repo):
    """AC-DEP-06.1 - an existing file list plus section anchors, for every id."""
    for entry in manifest:
        b = bundle_mod.bundle_for(entry.id, manifest, spec)
        assert b.files, f"{entry.id} produced an empty bundle"
        assert set(bundle_mod.ALWAYS) <= set(b.files), (
            f"{entry.id} omits one of {bundle_mod.ALWAYS}"
        )
        for name in b.files:
            assert (repo / "docs" / "spec" / name).is_file(), (
                f"{entry.id} names a missing file {name}"
            )


def test_the_transitive_closure_is_not_included(manifest, spec):
    """§6 - a direct dependency is a contract; a transitive one is not."""
    # MATCH-05 requires MATCH-01, MATCH-04, FOUND-09, FOUND-10, DATA-03.
    # MATCH-01 in turn requires PROF-02 - whose file must not be pulled in.
    b = bundle_mod.bundle_for("MATCH-05", manifest, spec)
    assert "03-profile.md" not in b.files
    assert "08-matching.md" in b.files


def test_no_r1_bundle_exceeds_five_files(manifest, spec):
    """AC-DEP-06.2 - a design constraint on the specification.

    The limit is seven, amended from five in v2.1.1 with the reason recorded in
    `18-dependency-closure.md` §6.
    """
    found = bundle_mod.oversized(manifest, spec)
    assert found == {}, f"bundles over {bundle_mod.MAX_FILES} files: {found}"


def test_every_anchor_resolves_to_a_heading(manifest, spec):
    """AC-DEP-06.3 - every file exists and every anchor is a real heading."""
    headings = {
        name: {section.heading for section in sf.sections}
        for name, sf in spec.files.items()
    }
    for entry in manifest:
        b = bundle_mod.bundle_for(entry.id, manifest, spec)
        for name, anchors in b.anchors.items():
            for anchor in anchors:
                assert anchor in headings.get(name, set()), (
                    f"{entry.id}: anchor {anchor!r} is not a heading in {name}"
                )


def test_every_r1_requirement_has_an_anchor_in_its_owning_file(manifest, spec):
    """A bundle whose owning file has no anchor sends the agent to a whole file."""
    missing = []
    for entry in manifest:
        if entry.track != "R1":
            continue
        owner = bundle_mod.owning_file(entry.id, spec)
        if not bundle_mod.anchors_for(entry.id, owner, spec):
            missing.append(f"{entry.id} in {owner}")
    assert missing == [], "R1 requirements with no section anchor: " + ", ".join(missing)


def test_spec_metadata_carries_the_bundle(repo):
    """AC-DEP-06.4 - `SPEC-METADATA.json` carries the computed bundle."""
    data = json.loads((repo / "docs" / "spec" / "SPEC-METADATA.json").read_text(encoding="utf-8"))
    dependencies = data["dependencies"]
    assert dependencies, "SPEC-METADATA.json has no dependencies block"
    for requirement, row in dependencies.items():
        assert "bundle" in row, f"{requirement} has no bundle in SPEC-METADATA.json"
        assert "requires" in row, f"{requirement} has no requires in SPEC-METADATA.json"


def test_an_unknown_requirement_is_refused(manifest, spec):
    with pytest.raises(KeyError):
        bundle_mod.bundle_for("NOPE-99", manifest, spec)
