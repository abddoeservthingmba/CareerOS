"""Parse `docs/spec/*.md` into a queryable model.

The specification's own conventions, implemented once here:

* `README.md` §0 - the six-part section contract, and the ID conventions
  `AC-<REQ>.<n>` / `T-<REQ>.<n>`.
* `README.md` §0 "Range and list notation" - a **Tests** line may cover several
  criteria at once: ``T-AUTH-05.1``-``.5`` is the five tests `.1` through `.5`,
  and ``T-FOUND-05.3``/``.5`` is exactly those two. `(shared)` means the test is
  defined in another file's **Tests** list and is resolved across the whole
  specification rather than per file.
* `01-foundations.md` §15 - the four implementation states.

Deviation from the shipped `docs/spec/spec_metadata.py`, deliberate and
recorded: that script splits a file on `## ` headings only, so a section's body
swallows its own `### ` subsections. A subsection annotated `**Track: R2**`
therefore drags its R1 parent to R2 - which is why the committed
`SPEC-METADATA.json` reports `AUTH-04` (sessions, R1, phase P1) as track R2 /
status `absent`, and likewise `RES-02`, `JOB-06`/`JOB-09`, `TRACK-02`,
`NOTIF-02` and `MOB-05`. This parser splits on `##` *and* `###`, so a heading's
body stops at the next heading of any level and each annotated subsection is its
own status-bearing unit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import spec_dir

# `README.md` and `00-scope-and-phases.md` describe the contract rather than
# carrying requirements of their own.
META_FILES = frozenset({"README.md", "00-scope-and-phases.md"})

# Committed alongside the specification but not part of it: generated artifacts
# and the kickoff prompt. Excluding these yields the 20 files that
# `SPEC-METADATA.json` counts.
COMPANION_FILES = frozenset(
    {
        "BUILD-ORDER.md",
        "CONSISTENCY-REPORT-v2.1.md",
        "PROMPT-claude-code.md",
        "TRACEABILITY.md",
    }
)

AC_ID = re.compile(r"AC-[A-Z]+-\d+\.\d+")
T_ID = re.compile(r"T-[A-Z]+-\d+\.\d+")
T_ID_PARTS = re.compile(r"T-([A-Z]+)-(\d+)\.(\d+)")
# A bare `.4` continuation inside a range or list, in its own code span.
BARE_SUFFIX = re.compile(r"^\.(\d+)$")
REQ_ID = re.compile(r"\b([A-Z]{2,6}-\d+[ab]?)\b")
HEADING = re.compile(r"^(#{2,3})\s+(.*?)\s*$")
CODE_SPAN = re.compile(r"`([^`\n]+)`")
SECTION_NUMBER = re.compile(r"^(\d+(?:\.\d+)?)[.\s]")

# An identifier is *defined* where the section contract puts it: on an
# "**Acceptance criteria**" / "**Tests**" line, or in the bullet list under one.
# Everywhere else - "(`AC-DEP-05.2` shared)", a control table in
# `16-security-and-compliance.md` §2 - it is a *reference* to a definition that
# lives elsewhere, and must not be mistaken for a second definition.
AC_MARKER = re.compile(r"^\s*\*\*Acceptance criteria")
TESTS_MARKER = re.compile(r"^\s*\*\*Tests\.?\*\*")
AC_BULLET = re.compile(r"^\s*-\s+\*{0,2}`AC-")
T_BULLET = re.compile(r"^\s*-\s+\*{0,2}`T-")


def defines_criteria(line: str) -> bool:
    return bool(AC_MARKER.match(line) or AC_BULLET.match(line))


def defines_tests(line: str) -> bool:
    return bool(TESTS_MARKER.match(line) or T_BULLET.match(line))


def defined_criteria_ids(line: str) -> list[str]:
    """The `AC-` identifiers a line *defines*, as opposed to mentions."""
    if not defines_criteria(line):
        return []
    return _definition_criteria_ids(line)


def defined_test_ids(line: str) -> list[str]:
    """The `T-` identifiers a line *defines*, with ranges and lists expanded."""
    if not defines_tests(line):
        return []
    return _expand_test_ids(line)


# A code span that looks like a path to a file the repository could hold.
# `apps/web/.../job-card.test.tsx` is written with an elided middle in the spec
# and is treated as a glob.
PATH_SPAN = re.compile(
    r"^[A-Za-z0-9_.][A-Za-z0-9_./*-]*\.(?:py|ts|tsx|dart|yml|yaml|mjs|sh|json|md)$"
)

TRACK_R2 = "**Track: R2**"
TRACK_R3 = "**Track: R3**"
TRACK_STRADDLE_MARKER = "code R1, enabled R2"
TRACK_STRADDLE = "R1 code, R2 on"

# `01-foundations.md` §15: default by track. An R1 section is `built`; an R2 or
# R3 section is `absent`; the single straddle is `built-off`.
STATUS_BY_TRACK = {
    "meta": "n/a",
    "R1": "built",
    TRACK_STRADDLE: "built-off",
    "R2": "absent",
    "R3": "absent",
}


@dataclass(frozen=True)
class Criterion:
    """An `AC-<REQ>.<n>` identifier and the sentence that defines it."""

    id: str
    text: str
    file: str
    line: int
    section: str


@dataclass(frozen=True)
class TestDef:
    """A `T-<REQ>.<n>` identifier as defined on a **Tests** line.

    `paths` are the file locations named on that line, repo- or `apps/api`-
    relative exactly as the specification writes them. `shared_with` carries the
    other `T-` identifiers the line points at, which is how a line such as
    "`T-AUTH-02.6` shared with `T-AI-05.5`" locates its test.
    """

    id: str
    paths: tuple[str, ...]
    shared_with: tuple[str, ...]
    file: str
    line: int
    section: str
    text: str


@dataclass(frozen=True)
class Section:
    """A `##` or `###` heading and everything up to the next heading."""

    file: str
    level: int
    heading: str
    number: str
    title: str
    requirements: tuple[str, ...]
    track: str
    status: str
    line: int
    body: str

    @property
    def ref(self) -> str:
        return f"{self.file}#{self.number or self.title}"


@dataclass
class SpecFile:
    name: str
    path: Path
    text: str
    lines: list[str]
    sections: list[Section] = field(default_factory=list)
    criteria: dict[str, Criterion] = field(default_factory=dict)
    tests: dict[str, TestDef] = field(default_factory=dict)


@dataclass
class Spec:
    """The whole specification, parsed once."""

    root: Path
    files: dict[str, SpecFile]

    @property
    def sections(self) -> list[Section]:
        return [s for f in self.files.values() for s in f.sections]

    @property
    def criteria(self) -> dict[str, Criterion]:
        out: dict[str, Criterion] = {}
        for f in self.files.values():
            out.update(f.criteria)
        return out

    @property
    def tests(self) -> dict[str, TestDef]:
        out: dict[str, TestDef] = {}
        for f in self.files.values():
            out.update(f.tests)
        return out

    def criteria_in(self, file: str) -> dict[str, Criterion]:
        return self.files[file].criteria

    def tests_in(self, file: str) -> dict[str, TestDef]:
        return self.files[file].tests


def _split_code_spans(line: str) -> list[tuple[str, str]]:
    """Return (span_text, separator_before) pairs for every code span on a line."""
    out: list[tuple[str, str]] = []
    last_end = 0
    for m in CODE_SPAN.finditer(line):
        out.append((m.group(1), line[last_end : m.start()]))
        last_end = m.end()
    return out


# An identifier is being *defined* when it opens the sentence or list item that
# describes it. One appearing mid-sentence - "(shared with `T-CONN-02.3`)",
# "...without the model fails `AC-DATA-07.1`." - points at a definition that
# lives elsewhere, even when it belongs to the same requirement.
DEFINITION_BOUNDARY = (".", ":", ";", "-", "*", "/", "|")


def _starts_definition(separator: str) -> bool:
    stripped = separator.rstrip()
    return stripped == "" or stripped.endswith(DEFINITION_BOUNDARY)


def _expand_test_ids(line: str) -> list[str]:
    """Expand the range and list notation of `README.md` §0 into explicit ids.

    ``T-AUTH-05.1``-``.5``  -> .1 .2 .3 .4 .5
    ``T-FOUND-05.3``/``.5`` -> .3 .5
    """
    ids: list[str] = []
    base: tuple[str, str] | None = None
    previous_index: int | None = None
    for span, separator in _split_code_spans(line):
        full = T_ID_PARTS.fullmatch(span)
        if full:
            if not _starts_definition(separator):
                continue
            family, requirement, index = full.groups()
            base = (family, requirement)
            previous_index = int(index)
            ids.append(span)
            continue
        bare = BARE_SUFFIX.fullmatch(span)
        if bare and base is not None:
            index = int(bare.group(1))
            is_range = "–" in separator or "—" in separator or separator.strip() == "-"
            if is_range and previous_index is not None and index > previous_index:
                for n in range(previous_index + 1, index + 1):
                    ids.append(f"T-{base[0]}-{base[1]}.{n}")
            else:
                ids.append(f"T-{base[0]}-{base[1]}.{index}")
            previous_index = index
    return ids


def _definition_criteria_ids(line: str) -> list[str]:
    ids: list[str] = []
    for span, separator in _split_code_spans(line):
        if AC_ID.fullmatch(span) and _starts_definition(separator):
            ids.append(span)
    return ids


def _paths_on(line: str) -> tuple[str, ...]:
    seen: list[str] = []
    for span, _ in _split_code_spans(line):
        if PATH_SPAN.fullmatch(span) and span not in seen:
            seen.append(span)
    return tuple(seen)


def _track_of(body: str, heading: str, file_name: str, requirements: tuple[str, ...]) -> str:
    """The section's track.

    `dependencies.yaml` is the authority - `AC-DEP-01.2` requires its `track` to
    equal the table in `00-scope-and-phases.md` §2 - so a heading that names a
    requirement takes that requirement's track. The prose annotation is the
    fallback for sections that name none, and the tiebreak where a heading
    covers requirements on different tracks.
    """
    if file_name in META_FILES:
        return "meta"

    from .manifest import ManifestError
    from .manifest import manifest as _manifest

    try:
        entries = _manifest()
    except (OSError, ManifestError):
        # The manifest is itself under test, or not yet written. Fall back to
        # the prose annotation rather than failing the parse.
        entries = None
    if entries is not None:
        tracks = {entries[r].effective_track for r in requirements if r in entries}
        if len(tracks) == 1:
            return tracks.pop()

    scope = heading + "\n" + body
    if TRACK_R3 in scope:
        return "R3"
    if TRACK_R2 in scope:
        return "R2"
    if TRACK_STRADDLE_MARKER in scope:
        return TRACK_STRADDLE
    return "R1"


def _parse_file(path: Path) -> SpecFile:
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    sf = SpecFile(name=path.name, path=path, text=text, lines=lines)

    heading_positions: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        m = HEADING.match(line)
        if m:
            heading_positions.append((i, len(m.group(1)), m.group(2)))

    for n, (start, level, heading) in enumerate(heading_positions):
        end = heading_positions[n + 1][0] if n + 1 < len(heading_positions) else len(lines)
        body = "\n".join(lines[start + 1 : end])
        num_match = SECTION_NUMBER.match(heading)
        number = num_match.group(1) if num_match else ""
        title = SECTION_NUMBER.sub("", heading, count=1) if num_match else heading
        title = re.sub(r"\s*—.*$", "", title).strip()
        requirements = tuple(dict.fromkeys(REQ_ID.findall(heading)))
        track = _track_of(body, heading, path.name, requirements)
        sf.sections.append(
            Section(
                file=path.name,
                level=level,
                heading=heading,
                number=number,
                title=title,
                requirements=requirements,
                track=track,
                status=STATUS_BY_TRACK[track],
                line=start + 1,
                body=body,
            )
        )

    def section_at(index: int) -> str:
        current = ""
        for start, _level, heading in heading_positions:
            if start <= index:
                current = heading
            else:
                break
        return current

    for i, line in enumerate(lines):
        for ac in defined_criteria_ids(line):
            if ac not in sf.criteria:
                sf.criteria[ac] = Criterion(
                    id=ac,
                    text=_normalise(line),
                    file=path.name,
                    line=i + 1,
                    section=section_at(i),
                )
        mentions = defined_test_ids(line)
        if not mentions:
            continue
        paths = _paths_on(line)
        shared_with = tuple(t for t in T_ID.findall(line) if t not in mentions)
        for tid in mentions:
            if tid in sf.tests and sf.tests[tid].paths:
                continue
            sf.tests[tid] = TestDef(
                id=tid,
                paths=paths,
                shared_with=shared_with,
                file=path.name,
                line=i + 1,
                section=section_at(i),
                text=_normalise(line),
            )
    return sf


def _normalise(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip())


@lru_cache(maxsize=1)
def parse_spec(root: str | None = None) -> Spec:
    directory = Path(root) if root else spec_dir()
    files: dict[str, SpecFile] = {}
    for path in sorted(directory.glob("*.md")):
        if path.name in COMPANION_FILES:
            continue
        files[path.name] = _parse_file(path)
    return Spec(root=directory, files=files)
