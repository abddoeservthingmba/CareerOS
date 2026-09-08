"""T-FOUND-15.7 - no placeholders on an R1 path (`01-foundations.md` §15).

"The whole codebase contains no `TODO`, `FIXME`, `XXX`, `raise
NotImplementedError`, `@pytest.mark.skip`, or commented-out code block on an R1
path."

This is the criterion that keeps `absent` honest and stops a half-built feature
hiding behind a note to self, so it runs from the first commit rather than at
the R1 gate.
"""

from __future__ import annotations

from specgate import status


def test_no_placeholder_markers(repo):
    """AC-FOUND-15.7."""
    findings = status.placeholder_findings(repo)
    assert findings == [], "\n".join(findings)


def test_no_skipped_tests(repo):
    """A skipped test is the commonest way an acceptance criterion goes missing."""
    offenders = []
    for path in (repo / "apps" / "api" / "tests").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for marker in ("@pytest.mark.skip", "pytest.skip(", "@pytest.mark.xfail"):
            if marker in text and path.name != "test_no_placeholders.py":
                offenders.append(f"{path.relative_to(repo).as_posix()}: {marker}")
    assert offenders == [], "\n".join(offenders)


def test_the_marker_list_is_the_one_the_spec_names():
    assert status.PLACEHOLDER_MARKERS == (
        "TODO",
        "FIXME",
        "XXX",
        "raise NotImplementedError",
        "@pytest.mark.skip",
    )
