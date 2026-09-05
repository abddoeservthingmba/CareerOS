"""The specification traceability gate - `FOUND-06`.

`01-foundations.md` §6. The chain the gate enforces:

    requirement ID  ->  track (00 §2)
                    ->  module file section (README §3)
                    ->  AC-<REQ>.<n>
                    ->  T-<REQ>.<n>  (names a real test path)

Path resolution. A **Tests** line writes a location the way the owning module
would: `tests/...` is relative to `apps/api`, while `apps/web/...`,
`apps/mobile/...`, `infra/...` and `.github/workflows/...` are repo-relative.
`apps/web/.../job-card.test.tsx` is written with an elided middle and is matched
as a glob.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import repo_root
from .manifest import Manifest, manifest
from .parser import Spec, defined_criteria_ids, defined_test_ids, parse_spec

# Roots a `T-` path may be written against, in resolution order.
PATH_ROOTS = ("", "apps/api/")

# `15-infra-and-ops.md` §3 names the workflows. A **Tests** entry may point at a
# step inside one rather than at a test file - "`T-MOB-01.4` `mobile-ci` step
# `build-flavors`" - which locates the workflow that must contain that step.
CI_WORKFLOWS = {
    "api-ci": ".github/workflows/api-ci.yml",
    "web-ci": ".github/workflows/web-ci.yml",
    "mobile-ci": ".github/workflows/mobile-ci.yml",
    "contracts": ".github/workflows/contracts.yml",
    "deploy-staging": ".github/workflows/deploy-staging.yml",
    "deploy-prod": ".github/workflows/deploy-prod.yml",
    "mobile-release": ".github/workflows/mobile-release.yml",
    "nightly": ".github/workflows/nightly.yml",
}


@dataclass(frozen=True)
class Finding:
    """One failure, phrased so the message alone locates the problem."""

    kind: str
    subject: str
    detail: str
    file: str = ""
    line: int = 0

    def __str__(self) -> str:
        where = f"{self.file}:{self.line}" if self.file else ""
        return f"[{self.kind}] {self.subject} - {self.detail}" + (
            f"  ({where})" if where else ""
        )


@dataclass
class TraceReport:
    criteria: int = 0
    tests: int = 0
    unmatched_criteria: list[Finding] = field(default_factory=list)
    missing_paths: list[Finding] = field(default_factory=list)
    unlocatable_tests: list[Finding] = field(default_factory=list)
    requirements_without_criteria: list[Finding] = field(default_factory=list)
    duplicate_definitions: list[Finding] = field(default_factory=list)
    resolved_paths: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def structural(self) -> list[Finding]:
        """Findings that do not depend on any code having been written yet."""
        return (
            self.unmatched_criteria
            + self.unlocatable_tests
            + self.requirements_without_criteria
            + self.duplicate_definitions
        )


def _existing(path: str, root: Path) -> bool:
    for prefix in PATH_ROOTS:
        candidate = prefix + path
        if "*" in candidate or "..." in candidate:
            pattern = candidate.replace("...", "**")
            if any(root.glob(pattern)):
                return True
        elif (root / candidate).exists():
            return True
    return False


# Roots a test may live under. `AC-FOUND-06.1` names the first four; `infra/` is
# added because the specification places a few shell checks there, and
# `apps/extension/` because `APPLY-06` (R3) is a separate artifact. `docs/` is
# deliberately absent: a **Tests** line may cite a runbook as the thing being
# asserted, and that citation is a reference, not a test location.
TEST_ROOTS = (
    "tests/",
    "apps/api/tests/",
    "apps/web/",
    "apps/mobile/",
    "apps/extension/",  # the R3 browser extension, a separate artifact
    ".github/workflows/",
    "infra/",
)


def _normalise_path(candidate: str) -> str | None:
    """A test location, or `None` if the span is an incidental reference.

    A **Tests** line may name artifacts alongside the test - "generated from
    `openapi.json`", "parametrized from `ai-budget.yaml`". Those carry no
    directory and are not workflows, so they are references rather than
    locations. A bare workflow name is expanded: "`.github/workflows/
    deploy-staging.yml`, `deploy-prod.yml`" names two workflows.
    """
    if candidate.startswith(TEST_ROOTS):
        return candidate
    if "/" not in candidate:
        stem = candidate.rsplit(".", 1)[0]
        if stem in CI_WORKFLOWS:
            return CI_WORKFLOWS[stem]
        return None
    return None


def _ci_workflow_paths(text: str) -> tuple[str, ...]:
    out = [path for name, path in CI_WORKFLOWS.items() if f"`{name}`" in text]
    return tuple(dict.fromkeys(out))


def resolve_paths(spec: Spec) -> dict[str, tuple[str, ...]]:
    """Attach every `T-` id to its location.

    Four resolution steps, in order, each following a convention the
    specification uses rather than relaxing `AC-FOUND-06.1`:

    1. A path named on the entry's own line.
    2. A CI step, which locates the workflow file that must contain it.
    3. `(shared)` / "shared with `T-...`", resolved across the whole
       specification per `README.md` §0.
    4. "same test." - the entry immediately above it, for the same requirement.
    """
    tests = spec.tests
    resolved: dict[str, tuple[str, ...]] = {}
    for tid, definition in tests.items():
        located = tuple(
            dict.fromkeys(
                p for p in (_normalise_path(raw) for raw in definition.paths) if p
            )
        )
        if located:
            resolved[tid] = located

    for tid, definition in tests.items():
        if tid in resolved:
            continue
        workflows = _ci_workflow_paths(definition.text)
        if workflows:
            resolved[tid] = workflows

    for tid, definition in tests.items():
        if tid in resolved:
            continue
        inherited: list[str] = []
        for other in definition.shared_with:
            inherited.extend(resolved.get(other, ()))
        if inherited:
            resolved[tid] = tuple(dict.fromkeys(inherited))

    for tid, definition in tests.items():
        if tid in resolved or "same test" not in definition.text:
            continue
        requirement, index = tid.rsplit(".", 1)
        sibling = f"{requirement}.{int(index) - 1}"
        if sibling in resolved:
            resolved[tid] = resolved[sibling]
    return resolved


def run(
    spec: Spec | None = None,
    m: Manifest | None = None,
    root: Path | None = None,
    check_existence: bool = True,
) -> TraceReport:
    spec = spec or parse_spec()
    m = m or manifest()
    root = root or repo_root()
    report = TraceReport()

    resolved = resolve_paths(spec)
    report.resolved_paths = resolved
    report.criteria = len(spec.criteria)
    report.tests = len(spec.tests)

    # AC-FOUND-06.1a - every AC has a matching T in the same file.
    for name, sf in spec.files.items():
        for ac in sorted(sf.criteria):
            expected = ac.replace("AC-", "T-", 1)
            if expected not in sf.tests:
                report.unmatched_criteria.append(
                    Finding(
                        "ac-without-test",
                        ac,
                        f"no {expected} defined in {name}",
                        name,
                        sf.criteria[ac].line,
                    )
                )

    # AC-FOUND-06.1b - every T names a locatable file, and that file exists.
    for tid in sorted(spec.tests):
        definition = spec.tests[tid]
        paths = resolved.get(tid, ())
        if not paths:
            report.unlocatable_tests.append(
                Finding(
                    "test-without-path",
                    tid,
                    f"names no test file: {definition.text[:90]}",
                    definition.file,
                    definition.line,
                )
            )
            continue
        if not check_existence:
            continue
        for path in paths:
            if not _existing(path, root):
                report.missing_paths.append(
                    Finding(
                        "test-file-missing",
                        tid,
                        f"{path} does not exist",
                        definition.file,
                        definition.line,
                    )
                )

    # AC-FOUND-06.2 - every R1 requirement has at least one acceptance criterion.
    for entry in m:
        if entry.track != "R1":
            continue
        base = entry.id[:-1] if entry.id[-1] in "ab" else entry.id
        prefix = f"AC-{base}."
        if not any(ac.startswith(prefix) for ac in spec.criteria):
            report.requirements_without_criteria.append(
                Finding(
                    "r1-without-criteria",
                    entry.id,
                    "no AC- identifier anywhere in the spec",
                )
            )

    # AC-FOUND-06.3 - no identifier defined twice with different text.
    seen: dict[str, tuple[str, str, int]] = {}
    for name, sf in spec.files.items():
        for number, line in enumerate(sf.lines, start=1):
            for identifier in defined_criteria_ids(line) + defined_test_ids(line):
                text = " ".join(line.split())
                previous = seen.get(identifier)
                if previous is None:
                    seen[identifier] = (text, name, number)
                elif previous[0] != text:
                    report.duplicate_definitions.append(
                        Finding(
                            "duplicate-definition",
                            identifier,
                            f"defined at {previous[1]}:{previous[2]} and {name}:{number} "
                            "with different text",
                            name,
                            number,
                        )
                    )
    return report


TRACEABILITY_HEADER = """# Traceability — generated from docs/spec/

Do not edit. Regenerate with `make spec-trace`.

Requirement → track → acceptance criterion → test → status.

"""


def render(
    spec: Spec | None = None, m: Manifest | None = None, root: Path | None = None
) -> str:
    """`AC-FOUND-06.4` - the published `TRACEABILITY.md` artifact."""
    spec = spec or parse_spec()
    m = m or manifest()
    root = root or repo_root()
    resolved = resolve_paths(spec)
    criteria = spec.criteria

    lines = [TRACEABILITY_HEADER.rstrip("\n"), ""]
    lines.append("| Requirement | Track | Phase | AC | Test | Path | Status |")
    lines.append("|---|---|---|---|---|---|---|")
    for entry in sorted(m, key=lambda e: (e.phase_index, e.id)):
        base = entry.id[:-1] if entry.id[-1] in "ab" else entry.id
        owned = sorted(
            (ac for ac in criteria if ac.startswith(f"AC-{base}.")),
            key=lambda a: int(a.rsplit(".", 1)[1]),
        )
        if not owned:
            lines.append(
                f"| `{entry.id}` | {entry.track} | {entry.phase or '—'} | — | — | — | no criteria |"
            )
            continue
        for ac in owned:
            tid = ac.replace("AC-", "T-", 1)
            paths = resolved.get(tid, ())
            if not paths:
                status = "no test path"
            elif all(_existing(p, root) for p in paths):
                status = "test present"
            else:
                status = "test not written"
            shown = ", ".join(f"`{p}`" for p in paths) if paths else "—"
            lines.append(
                f"| `{entry.id}` | {entry.track} | {entry.phase or '—'} | `{ac}` | "
                f"`{tid}` | {shown} | {status} |"
            )
    return "\n".join(lines) + "\n"
