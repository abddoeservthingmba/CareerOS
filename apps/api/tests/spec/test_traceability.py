"""T-FOUND-06.1-.4 - the specification traceability gate (`01-foundations.md` §6).

One test case per check, as the Tests list requires.
"""

from __future__ import annotations

from specgate import traceability
from specgate.parser import defined_criteria_ids, defined_test_ids


def test_every_criterion_has_a_test_that_names_a_file(spec, manifest, repo):
    """AC-FOUND-06.1.

    Two halves. Every `AC-` has a matching `T-` in the same file, and every
    `T-` names a location. Thirteen identifiers named a mechanism or a document
    rather than a test file until v2.1.1 gave each one a path.

    Whether the named file *exists* is asserted separately, by
    `test_named_test_files_exist`, because it becomes true only as the build
    lands the tests.
    """
    report = traceability.run(spec, manifest, repo, check_existence=False)

    assert [str(f) for f in report.unmatched_criteria] == []

    assert [str(f) for f in report.unlocatable_tests] == []

    # The four roots `AC-FOUND-06.1` names, plus `infra/` for the shell checks
    # the specification places there.
    roots = (
        "tests/",
        "apps/api/tests/",
        "apps/web/",
        "apps/mobile/",
        "apps/extension/",
        ".github/workflows/",
        "infra/",
    )
    stray = sorted(
        f"{tid}: {path}"
        for tid, paths in report.resolved_paths.items()
        for path in paths
        if not path.startswith(roots)
    )
    assert stray == [], f"test paths outside the permitted roots: {stray}"


def test_every_r1_requirement_has_a_criterion(spec, manifest, repo):
    """AC-FOUND-06.2."""
    report = traceability.run(spec, manifest, repo, check_existence=False)
    assert [str(f) for f in report.requirements_without_criteria] == []


def test_no_identifier_is_defined_twice_with_different_text(spec, manifest, repo):
    """AC-FOUND-06.3."""
    report = traceability.run(spec, manifest, repo, check_existence=False)
    assert [str(f) for f in report.duplicate_definitions] == []


def test_traceability_artifact_is_generated(spec, manifest, repo):
    """AC-FOUND-06.4 - `TRACEABILITY.md` is regenerated and published."""
    rendered = traceability.render(spec, manifest, repo)
    assert rendered.startswith("# Traceability")
    for requirement in ("FOUND-06", "MATCH-05", "AUTH-01"):
        assert f"`{requirement}`" in rendered
    committed = repo / "docs" / "spec" / "TRACEABILITY.md"
    assert committed.is_file(), "run `make spec-trace` to publish TRACEABILITY.md"
    assert committed.read_text(encoding="utf-8") == rendered, (
        "TRACEABILITY.md is stale; regenerate with `make spec-trace`"
    )


def test_named_test_files_exist(spec, manifest, repo):
    """The other half of AC-FOUND-06.1, and the R1 gate's item 2 evidence.

    Every test named in the specification must exist by the R1 gate. It is
    asserted here as a monotonic count rather than a boolean, so the number can
    only fall: a commit that names a test without writing it fails.
    """
    report = traceability.run(spec, manifest, repo, check_existence=True)
    outstanding = {f.subject for f in report.missing_paths}
    assert len(outstanding) <= EXPECTED_OUTSTANDING_TESTS, (
        f"{len(outstanding)} tests are named but not written, up from "
        f"{EXPECTED_OUTSTANDING_TESTS}. Write the test, or correct the path."
    )


# Lowered by each commit that lands a test file; reaches 0 at the R1 gate.
# Update this number downward in the same commit that writes the tests.
EXPECTED_OUTSTANDING_TESTS = 613


def test_the_range_and_list_notation_expands(spec):
    """`README.md` §0 - the notation the gate must understand.

    Asserted directly, because every other check in this file depends on the
    expansion being right.
    """
    assert defined_test_ids("- `T-AUTH-05.1`–`.5` `tests/integration/test_password_reset.py`.") == [
        "T-AUTH-05.1",
        "T-AUTH-05.2",
        "T-AUTH-05.3",
        "T-AUTH-05.4",
        "T-AUTH-05.5",
    ]
    assert defined_test_ids("- `T-AUTH-01.2`/`.3` `tests/integration/test_breach_check.py`.") == [
        "T-AUTH-01.2",
        "T-AUTH-01.3",
    ]
    # A trailing "shared with" is a reference, not a second definition, even
    # when it names the same requirement.
    assert defined_test_ids(
        "- `T-CONN-02.8` `tests/spec/test_connector_addition_drill.py` (shared with `T-CONN-02.3`)."
    ) == ["T-CONN-02.8"]
    assert defined_criteria_ids("- `AC-DATA-07.6` Adding a field ... fails `AC-DATA-07.1`.") == [
        "AC-DATA-07.6"
    ]
    # A control table in `16-security-and-compliance.md` §2 references criteria.
    table_row = "| 1 | Passwords | Argon2id | R1 | `AC-AUTH-01.2`, `AC-AUTH-01.6` |"
    assert defined_criteria_ids(table_row) == []


def test_totals_match_the_committed_metadata(spec):
    """The parse is corroborated by the shipped `SPEC-METADATA.json` totals."""
    assert len(spec.files) == 20
    assert len(spec.criteria) == 826
    assert len(spec.tests) == 826
