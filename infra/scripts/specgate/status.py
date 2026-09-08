"""The implementation-status registry - `FOUND-15`.

`01-foundations.md` §15. Four states and no fifth:

    built      implemented and on
    built-off  implemented, deliberately disabled in production
    stub-501   route reserved, no implementation behind it
    absent     does not exist

Two halves, with different lifetimes. The **declaration** half - that every
section names a state, and that the states follow the default-by-track rule -
is checkable against the specification alone and runs from the first commit.
The **reality** half (`AC-FOUND-15.3`/`.4`/`.5`/`.8`/`.9`) checks a declared
state against the flag defaults, the OpenAPI surface and the admin UI, none of
which exist before `FOUND-02`/`FOUND-13`; those criteria are asserted as the
phases that build them land.

Known gap, reported rather than worked around: `AC-FOUND-15.1` requires every
section to carry a literal `**Status:**` line, and no section in the shipped
specification has one. Until the specification is edited, `declared_status()`
reports the state *derived* from the section's `Track:` annotation - which is
what `docs/spec/spec_metadata.py` already does - and `undeclared_sections()`
lists every section still missing the line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import repo_root
from .parser import META_FILES, Section, Spec, parse_spec

STATES = ("built", "built-off", "stub-501", "absent")

STATUS_LINE = re.compile(r"^\s*\*\*Status:?\*\*\s*`?([a-z0-9-]+)`?", re.MULTILINE)

# `01-foundations.md` §15: "The only `built-off` in R1 is `MATCH-02b`".
EXPECTED_BUILT_OFF = ("MATCH-02b",)

# `AC-FOUND-15.7`: none of these may appear on an R1 path.
PLACEHOLDER_MARKERS = (
    "TODO",
    "FIXME",
    "XXX",
    "raise NotImplementedError",
    "@pytest.mark.skip",
)

# Directories that hold product code on an R1 path.
CODE_ROOTS = ("apps/api/app", "apps/web/src", "apps/mobile/lib", "infra/scripts")
CODE_SUFFIXES = (".py", ".ts", ".tsx", ".dart")


@dataclass(frozen=True)
class StatusEntry:
    file: str
    section: str
    heading: str
    requirements: tuple[str, ...]
    track: str
    status: str
    declared: bool


def declared_status(section: Section) -> str | None:
    """The state a section declares in its own body, if it declares one."""
    m = STATUS_LINE.search(section.body)
    if not m:
        return None
    value = m.group(1)
    return value if value in STATES else None


def entries(spec: Spec | None = None) -> list[StatusEntry]:
    spec = spec or parse_spec()
    out: list[StatusEntry] = []
    for section in spec.sections:
        if section.file in META_FILES:
            continue
        declared = declared_status(section)
        out.append(
            StatusEntry(
                file=section.file,
                section=section.number or section.title,
                heading=section.heading,
                requirements=section.requirements,
                track=section.track,
                status=declared or section.status,
                declared=declared is not None,
            )
        )
    return out


def undeclared_sections(spec: Spec | None = None) -> list[StatusEntry]:
    """`AC-FOUND-15.1`: sections with no `**Status:**` line of their own."""
    return [e for e in entries(spec) if not e.declared]


def default_by_track_violations(spec: Spec | None = None) -> list[str]:
    """`AC-FOUND-15.2`: R1 is `built` except `MATCH-02b`; R2/R3 are `absent`."""
    out: list[str] = []
    for entry in entries(spec):
        expected = {
            "R1": "built",
            "R1 code, R2 on": "built-off",
            "R2": "absent",
            "R3": "absent",
        }[entry.track]
        if entry.status != expected:
            out.append(
                f"{entry.file} §{entry.section}: track {entry.track} expects "
                f"{expected}, declared {entry.status}"
            )
        if entry.status == "built-off" and not any(
            r in EXPECTED_BUILT_OFF for r in entry.requirements
        ):
            out.append(
                f"{entry.file} §{entry.section}: built-off, but only "
                f"{', '.join(EXPECTED_BUILT_OFF)} may be built-off in R1"
            )
    return out


def _code_files(root: Path, roots: tuple[str, ...] = CODE_ROOTS) -> list[Path]:
    out: list[Path] = []
    for relative in roots:
        base = root / relative
        if not base.is_dir():
            continue
        out.extend(p for p in base.rglob("*") if p.suffix in CODE_SUFFIXES and p.is_file())
    return out


def placeholder_findings(root: Path | None = None) -> list[str]:
    """`AC-FOUND-15.7`: no placeholder marker anywhere on an R1 path.

    The gate itself is code on an R1 path, so `PLACEHOLDER_MARKERS` is compared
    against file content with the definition list in this module excluded.
    """
    root = root or repo_root()
    this_file = Path(__file__).resolve()
    out: list[str] = []
    for path in _code_files(root):
        if path.resolve() == this_file:
            continue
        for number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").split("\n"), start=1
        ):
            for marker in PLACEHOLDER_MARKERS:
                if marker in line:
                    out.append(f"{path.relative_to(root).as_posix()}:{number}: {marker}")
    return out


def absent_requirements(spec: Spec | None = None) -> set[str]:
    """Requirements whose every section is `absent`."""
    by_requirement: dict[str, set[str]] = {}
    for entry in entries(spec):
        for requirement in entry.requirements:
            by_requirement.setdefault(requirement, set()).add(entry.status)
    return {r for r, states in by_requirement.items() if states == {"absent"}}


def absent_findings(root: Path | None = None, spec: Spec | None = None) -> list[str]:
    """`AC-FOUND-15.6`: an `absent` section has no module file and no code path.

    Scoped to product code. The spec tooling under `infra/scripts/` names every
    requirement by design - it parses them - so scanning it would report the
    gate's own vocabulary as an implementation of the feature it is checking.
    """
    root = root or repo_root()
    out: list[str] = []
    absent = absent_requirements(spec)
    product = tuple(r for r in CODE_ROOTS if r != "infra/scripts")
    for path in _code_files(root, product):
        text = _executable_source(path)
        for requirement in sorted(absent):
            if re.search(rf"\b{re.escape(requirement)}\b", text):
                out.append(
                    f"{path.relative_to(root).as_posix()} mentions absent requirement {requirement}"
                )
    return out


def _executable_source(path: Path) -> str:
    """A file's code with comments and string literals removed.

    `AC-FOUND-15.6` forbids "a code path mentioning" an `absent` requirement. A
    docstring that explains *why* something is deliberately absent - "the R2/R3
    credentials `NOTIF-02b` needs are not here" - is the opposite of a code path
    for it, and citing the specification is how the rest of this codebase stays
    reviewable. So the scan looks at code only.
    """
    source = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix != ".py":
        # Line and block comments; the clients arrive in later phases and this
        # is refined then if it proves too coarse.
        source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
        return re.sub(r"//[^\n]*", " ", source)

    import io
    import tokenize

    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        return " ".join(
            token.string
            for token in tokens
            if token.type not in (tokenize.COMMENT, tokenize.STRING)
        )
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return source


STATUS_HEADER = """# Implementation status — generated from docs/spec/
#
# Do not edit. Regenerate with `make status`.
# Four states, no fifth: built | built-off | stub-501 | absent (01-foundations.md §15).
# `declared: false` means the section carries no **Status:** line and the state
# below is derived from its Track annotation (see AC-FOUND-15.1).

"""


def render(spec: Spec | None = None) -> str:
    lines = [STATUS_HEADER.rstrip("\n"), ""]
    current_file = ""
    for entry in entries(spec):
        if entry.file != current_file:
            current_file = entry.file
            lines.append(f"{entry.file}:")
        lines.append(f"  - section: {entry.section!r}")
        lines.append(f"    heading: {entry.heading!r}")
        lines.append(f"    requirements: [{', '.join(entry.requirements)}]")
        lines.append(f"    track: {entry.track!r}")
        lines.append(f"    status: {entry.status}")
        lines.append(f"    declared: {str(entry.declared).lower()}")
    return "\n".join(lines) + "\n"
