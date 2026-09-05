"""T-FOUND-15.6 - `absent` means absent (`01-foundations.md` §15).

"no dead code, no commented-out block, no unreachable branch, no unused flag,
no orphan migration, no test skipped with a 'later' marker, and no model field
that nothing reads."

The route, flag and OpenAPI halves of `AC-FOUND-15.6` are asserted as the
phases that build them land - there is no `Settings` and no `openapi.json`
before `FOUND-02` and `FOUND-13`. What is checkable from the first commit is
that no code path mentions an `absent` requirement at all, which is the half
that would otherwise rot silently.
"""

from __future__ import annotations

from specgate import status


def test_no_code_mentions_an_absent_requirement(repo, spec):
    """AC-FOUND-15.6 - no module file and no code path for an `absent` section."""
    findings = status.absent_findings(repo, spec)
    assert findings == [], "\n".join(findings)


def test_the_absent_set_is_the_r2_and_r3_work(spec, manifest):
    """A sanity check on the derivation: `absent` must be exactly non-R1."""
    absent = status.absent_requirements(spec)
    for requirement in sorted(absent):
        if requirement not in manifest:
            continue
        assert manifest[requirement].track in ("R2", "R3"), (
            f"{requirement} is derived `absent` but tracked "
            f"{manifest[requirement].track}"
        )


def test_r2_and_r3_requirements_are_absent(spec, manifest):
    """Every R2/R3 requirement must be `absent` unless it declares otherwise."""
    entries = status.entries(spec)
    declared: dict[str, set[str]] = {}
    for entry in entries:
        for requirement in entry.requirements:
            declared.setdefault(requirement, set()).add(entry.status)
    wrong = []
    for entry in manifest:
        if entry.track not in ("R2", "R3") or entry.enabled_in:
            continue
        states = declared.get(entry.id)
        if states and states != {"absent"}:
            wrong.append(f"{entry.id} ({entry.track}) is {sorted(states)}")
    assert wrong == [], "\n".join(wrong)
