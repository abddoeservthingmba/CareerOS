"""`make bundle REQ=<id>` - the agent handoff bundle (`DEP-06`).

`18-dependency-closure.md` §6: for a requirement `R` the bundle is `README.md`,
`01-foundations.md`, `17-data-model.md`, the file owning `R`, and the file
owning every requirement in `R`'s **direct** `requires` set - plus
`18-dependency-closure.md` when the agent is expected to add a manifest entry.
The transitive closure is deliberately not included.
"""

from __future__ import annotations

from dataclasses import dataclass

from .manifest import Manifest, manifest
from .parser import Spec, parse_spec

ALWAYS = ("README.md", "01-foundations.md", "17-data-model.md")
MANIFEST_FILE = "18-dependency-closure.md"
MAX_FILES = 7

# `README.md` §3 - the file index. Used only where a requirement declares no
# acceptance criteria of its own, so the owning file cannot be derived.
FAMILY_FILE = {
    "FOUND": "01-foundations.md",
    "AUTH": "02-auth-and-account.md",
    "PROF": "03-profile.md",
    "RES": "04-resume-pipeline.md",
    "AI": "05-ai-layer.md",
    "CONN": "06-connectors.md",
    "JOB": "07-ingestion-and-jobs.md",
    "MATCH": "08-matching.md",
    "APPLY": "09-apply.md",
    "TRACK": "10-tracker.md",
    "NOTIF": "11-notifications.md",
    "ADMIN": "12-admin.md",
    "WEB": "13-web-client.md",
    "MOB": "14-mobile-client.md",
    "OPS": "15-infra-and-ops.md",
    "SEC": "16-security-and-compliance.md",
    "DATA": "17-data-model.md",
    "DEP": "18-dependency-closure.md",
}


@dataclass(frozen=True)
class Bundle:
    requirement: str
    files: tuple[str, ...]
    anchors: dict[str, tuple[str, ...]]

    @property
    def size(self) -> int:
        return len(self.files)


def owning_file(requirement: str, spec: Spec | None = None) -> str:
    """The specification file that defines a requirement's acceptance criteria."""
    spec = spec or parse_spec()
    base = requirement.rstrip("abc") if requirement[-1] in "abc" else requirement
    prefix = f"AC-{base}."
    for name, sf in spec.files.items():
        if any(ac.startswith(prefix) for ac in sf.criteria):
            return name
    family = requirement.split("-")[0]
    return FAMILY_FILE[family]


def anchors_for(requirement: str, file: str, spec: Spec | None = None) -> tuple[str, ...]:
    """Section headings inside `file` that name `requirement`."""
    spec = spec or parse_spec()
    sf = spec.files.get(file)
    if sf is None:
        return ()
    base = requirement.rstrip("abc") if requirement[-1] in "abc" else requirement
    out = [
        s.heading
        for s in sf.sections
        if requirement in s.requirements or base in s.requirements
    ]
    if out:
        return tuple(dict.fromkeys(out))

    # Fallback for a heading that omits its requirement id - `09-apply.md` §6.1
    # is titled "Follow-up draft" but owns `AC-APPLY-09.*`. Locate the section
    # by where the criteria are defined instead, so the bundle still points at a
    # section rather than a whole file.
    prefix = f"AC-{base}."
    lines = {c.line for c in sf.criteria.values() if c.id.startswith(prefix)}
    if not lines:
        return ()
    headings = sorted({s.line: s.heading for s in sf.sections}.items())
    found: list[str] = []
    for line in sorted(lines):
        current = ""
        for start, heading in headings:
            if start <= line:
                current = heading
            else:
                break
        if current:
            found.append(current)
    return tuple(dict.fromkeys(found))


def bundle_for(
    requirement: str,
    m: Manifest | None = None,
    spec: Spec | None = None,
    include_manifest: bool = False,
) -> Bundle:
    m = m or manifest()
    spec = spec or parse_spec()
    if requirement not in m:
        raise KeyError(f"{requirement} is not in the dependency manifest")

    files: list[str] = list(ALWAYS)
    owner = owning_file(requirement, spec)
    if owner not in files:
        files.append(owner)
    for dependency in m[requirement].requires:
        dependency_file = owning_file(dependency, spec)
        if dependency_file not in files:
            files.append(dependency_file)
    if include_manifest and MANIFEST_FILE not in files:
        files.append(MANIFEST_FILE)

    anchors = {owner: anchors_for(requirement, owner, spec)}
    for dependency in m[requirement].requires:
        dependency_file = owning_file(dependency, spec)
        existing = anchors.get(dependency_file, ())
        anchors[dependency_file] = tuple(
            dict.fromkeys(existing + anchors_for(dependency, dependency_file, spec))
        )
    return Bundle(requirement=requirement, files=tuple(files), anchors=anchors)


def oversized(m: Manifest | None = None, spec: Spec | None = None) -> dict[str, int]:
    """`AC-DEP-06.2`: R1 requirements whose bundle exceeds `MAX_FILES`."""
    m = m or manifest()
    spec = spec or parse_spec()
    out: dict[str, int] = {}
    for entry in m:
        if entry.track != "R1":
            continue
        size = bundle_for(entry.id, m, spec).size
        if size > MAX_FILES:
            out[entry.id] = size
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def render(requirement: str, m: Manifest | None = None, spec: Spec | None = None) -> str:
    b = bundle_for(requirement, m, spec)
    entry = (m or manifest())[requirement]
    lines = [
        f"# bundle for {requirement}  ({entry.track} · {entry.phase or 'unphased'} · {entry.module})",
        "",
    ]
    for name in b.files:
        lines.append(f"docs/spec/{name}")
        for anchor in b.anchors.get(name, ()):
            lines.append(f"    §{anchor}")
    lines += [
        "",
        f"{b.size} file(s); direct requires: {', '.join(entry.requires) or 'none'}",
    ]
    return "\n".join(lines) + "\n"
