"""T-FOUND-15.1/.2 - the implementation-status registry (`01-foundations.md` §15)."""

from __future__ import annotations

from specgate import status

from . import spec_defects


def test_every_section_declares_a_status(spec):
    """AC-FOUND-15.1 - one of exactly four states, on every section.

    Currently no section in any of the twenty files carries a `**Status:**`
    line. See `spec_defects.SECTIONS_WITHOUT_A_STATUS_LINE`. Asserted as a count
    so the lines can be added file by file, each commit moving one number.
    """
    undeclared = status.undeclared_sections(spec)
    assert len(undeclared) == spec_defects.SECTIONS_WITHOUT_A_STATUS_LINE, (
        f"{len(undeclared)} sections carry no Status line, ledger expects "
        f"{spec_defects.SECTIONS_WITHOUT_A_STATUS_LINE}"
    )
    for entry in status.entries(spec):
        assert entry.status in status.STATES, (
            f"{entry.file} §{entry.section}: {entry.status!r} is not one of {status.STATES}"
        )


def test_status_follows_default_by_track(spec):
    """AC-FOUND-15.2 - R1 is `built` except `MATCH-02b`; R2/R3 are `absent`."""
    violations = status.default_by_track_violations(spec)
    assert violations == [], "\n".join(violations)


def test_match_02b_is_the_only_built_off_section(spec):
    """§15 - "The only `built-off` in R1 is `MATCH-02b`"."""
    built_off = [
        f"{e.file} §{e.section}" for e in status.entries(spec) if e.status == "built-off"
    ]
    assert len(built_off) == 1, f"expected one built-off section, found {built_off}"
    entry = next(e for e in status.entries(spec) if e.status == "built-off")
    assert "MATCH-02b" in entry.requirements
    assert entry.file == "08-matching.md"


def test_there_is_no_fifth_state():
    assert status.STATES == ("built", "built-off", "stub-501", "absent")


def test_the_registry_renders(spec):
    """`docs/spec/status.yaml` - the state of the whole product in one file."""
    rendered = status.render(spec)
    assert rendered.startswith("# Implementation status")
    assert "status: built-off" in rendered
    assert "status: absent" in rendered
    assert "status: built" in rendered
