"""`docs/spec/dependencies.yaml` - the dependency manifest (`DEP-01`).

Loaded by a dedicated reader rather than a YAML library: the manifest's shape is
fixed by `18-dependency-closure.md` §1 (a flat map of requirement id to five
scalar/list keys) and a strict reader that refuses anything else is a better
check on the file than a permissive parser that quietly accepts a typo. This
also keeps the spec gates free of third-party dependencies, so they run before
`apps/api` has an environment.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import spec_dir

ENTRY = re.compile(r"^([A-Z][A-Za-z0-9-]*):$")
KEY = re.compile(r"^  ([a-z_]+):\s*(.*)$")
LIST_VALUE = re.compile(r"^\[(.*)\]$")

SCALAR_KEYS = frozenset({"track", "phase", "module", "enabled_in"})
LIST_KEYS = frozenset(
    {"requires", "consumes_events", "publishes_events", "reads_collections", "writes_collections"}
)

# `00-scope-and-phases.md` §4 and §4.1. `None` is the unphased R3 backlog.
PHASE_ORDER: tuple[str | None, ...] = (
    "P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7",
    "S1", "S2", "S3", "S4", "S5",
    None,
)

TRACKS = frozenset({"R1", "R2", "R3"})

# `01-foundations.md` §4 / §5: a module is a directory under `modules/`, or one
# of the non-module homes a requirement can belong to.
MODULES = frozenset(
    {
        "core", "ai", "connectors", "infra", "web", "mobile",
        "auth", "profile", "resume", "jobs", "matching", "apply",
        "tracker", "notifications", "admin",
    }
)


class ManifestError(ValueError):
    """The manifest is malformed - a defect in the file, not in a caller."""


@dataclass(frozen=True)
class Entry:
    id: str
    track: str
    phase: str | None
    module: str
    enabled_in: str | None = None
    requires: tuple[str, ...] = ()
    consumes_events: tuple[str, ...] = ()
    publishes_events: tuple[str, ...] = ()
    reads_collections: tuple[str, ...] = ()
    writes_collections: tuple[str, ...] = ()
    line: int = 0

    @property
    def phase_index(self) -> int:
        return PHASE_ORDER.index(self.phase)

    @property
    def effective_track(self) -> str:
        """`DEP-03`: the one deliberate straddle counts as R1 for closure."""
        return "R1 code, R2 on" if self.enabled_in == "R2" else self.track


@dataclass
class Manifest:
    path: Path
    entries: dict[str, Entry] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Entry:
        return self.entries[key]

    def __contains__(self, key: str) -> bool:
        return key in self.entries

    def __iter__(self) -> Iterator[Entry]:
        return iter(self.entries.values())

    @property
    def ids(self) -> set[str]:
        return set(self.entries)

    def closure(self, requirement: str) -> set[str]:
        """Transitive `requires` set, excluding the requirement itself."""
        seen: set[str] = set()
        stack = list(self.entries[requirement].requires)
        while stack:
            current = stack.pop()
            if current in seen or current not in self.entries:
                continue
            seen.add(current)
            stack.extend(self.entries[current].requires)
        return seen

    def path_to(self, start: str, target: str) -> list[str] | None:
        """A concrete `requires` path from `start` to `target`, for error output."""
        stack: list[list[str]] = [[start]]
        seen = {start}
        while stack:
            trail = stack.pop(0)
            for nxt in self.entries[trail[-1]].requires:
                if nxt == target:
                    return trail + [nxt]
                if nxt in seen or nxt not in self.entries:
                    continue
                seen.add(nxt)
                stack.append(trail + [nxt])
        return None

    def cycles(self) -> list[list[str]]:
        """Every elementary cycle reachable by depth-first search."""
        found: list[list[str]] = []
        colour: dict[str, int] = {}
        trail: list[str] = []

        def visit(node: str) -> None:
            colour[node] = 1
            trail.append(node)
            for nxt in self.entries[node].requires:
                if nxt not in self.entries:
                    continue
                if colour.get(nxt, 0) == 1:
                    found.append(trail[trail.index(nxt) :] + [nxt])
                elif colour.get(nxt, 0) == 0:
                    visit(nxt)
            trail.pop()
            colour[node] = 2

        for node in self.entries:
            if colour.get(node, 0) == 0:
                visit(node)
        return found


def _parse_list(raw: str, key: str, entry_id: str, line: int) -> tuple[str, ...]:
    m = LIST_VALUE.fullmatch(raw)
    if not m:
        raise ManifestError(f"{entry_id}.{key} (line {line}): expected [a, b], got {raw!r}")
    inner = m.group(1).strip()
    if not inner:
        return ()
    return tuple(part.strip() for part in inner.split(",") if part.strip())


def load(path: Path | None = None) -> Manifest:
    target = path or (spec_dir() / "dependencies.yaml")
    manifest = Manifest(path=target)
    current: dict[str, Any] | None = None
    current_id: str | None = None

    def flush() -> None:
        nonlocal current, current_id
        if current_id is None or current is None:
            return
        missing = {"track", "phase", "module"} - current.keys()
        if missing:
            raise ManifestError(f"{current_id}: missing required key(s) {sorted(missing)}")
        manifest.entries[current_id] = Entry(id=current_id, **current)
        current, current_id = None, None

    for number, raw_line in enumerate(target.read_text(encoding="utf-8").split("\n"), start=1):
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        entry_match = ENTRY.fullmatch(line)
        if entry_match:
            flush()
            current_id = entry_match.group(1)
            if current_id in manifest.entries:
                raise ManifestError(f"{current_id} (line {number}): declared twice")
            current = {"line": number}
            continue
        key_match = KEY.fullmatch(line)
        if not key_match:
            raise ManifestError(f"line {number}: unparseable {line!r}")
        if current is None:
            raise ManifestError(f"line {number}: key outside any entry: {line!r}")
        key, raw_value = key_match.group(1), key_match.group(2).strip()
        if key in SCALAR_KEYS:
            current[key] = None if raw_value == "null" else raw_value
        elif key in LIST_KEYS:
            current[key] = _parse_list(raw_value, key, current_id or "?", number)
        else:
            raise ManifestError(f"{current_id} (line {number}): unknown key {key!r}")
    flush()

    if not manifest.entries:
        raise ManifestError(f"{target} contained no entries")
    return manifest


@lru_cache(maxsize=1)
def manifest() -> Manifest:
    return load()
