"""Module graph, track closure, phase closure and build order.

`18-dependency-closure.md` §2 (`DEP-02`), §3 (`DEP-03`), §4 (`DEP-04`).

Two closure properties, and they are different. **Track closure** asks whether
R1 can ship without R2 or R3 code existing. **Phase closure** asks whether each
phase can be built with only what earlier phases produced.
"""

from __future__ import annotations

from dataclasses import dataclass

from .manifest import Manifest, manifest

# ---------------------------------------------------------------------------
# DEP-02 - the module graph
# ---------------------------------------------------------------------------
# Transcribed from the diagram in `18-dependency-closure.md` §2 together with
# the five rules stated beneath it. An arrow means "may call the public API of"
# or "may consume events from". `core` is foundations (core, shared, infra
# interfaces) and everything may depend on it, which is why it is implicit in
# every row rather than repeated.
#
# The rules the picture encodes, each asserted by a test in
# `tests/spec/test_module_graph.py`:
#   - `ai` and `connectors` are leaves.
#   - `resume` does not write the profile; it publishes `ResumeExtracted`.
#   - `matching` is downstream of `profile` and `jobs`, upstream of `apply`.
#   - `admin` reads every module and nothing depends on it.
#   - `notifications` is the terminal consumer.
#   - The one upward edge is `auth -> tracker/notifications` for the user's
#     timezone and notification settings, taken through `AuthService`.
FOUNDATIONS = "core"

MODULE_EDGES: dict[str, frozenset[str]] = {
    "core": frozenset(),
    "ai": frozenset(),
    "connectors": frozenset(),
    "auth": frozenset(),
    "resume": frozenset({"auth", "ai", "profile"}),
    "profile": frozenset({"ai", "resume"}),
    "jobs": frozenset({"connectors", "ai", "profile"}),
    "matching": frozenset({"profile", "jobs", "ai"}),
    "apply": frozenset({"profile", "matching", "ai", "tracker", "connectors"}),
    "tracker": frozenset({"jobs", "apply", "auth", "notifications"}),
    "notifications": frozenset({"tracker", "auth"}),
    "admin": frozenset(
        {"auth", "profile", "resume", "jobs", "matching", "apply", "tracker",
         "notifications", "ai", "connectors", "web", "mobile"}
    ),
    # The clients and the build/ops surface consume contracts, not modules.
    "web": frozenset(
        {"auth", "profile", "resume", "jobs", "matching", "apply", "tracker",
         "notifications", "admin", "ai", "mobile"}
    ),
    "mobile": frozenset(
        {"auth", "profile", "resume", "jobs", "matching", "apply", "tracker",
         "notifications", "ai", "web"}
    ),
    "infra": frozenset(
        {"auth", "profile", "resume", "jobs", "matching", "apply", "tracker",
         "notifications", "admin", "ai", "connectors", "web", "mobile"}
    ),
}

LEAF_MODULES = ("ai", "connectors")

# The diagram in §2 models the API's own modules. The manifest additionally uses
# `core` for the cross-cutting `SEC-*` family, `infra` for `OPS-*`, and `web` /
# `mobile` for the clients. Those four verify or render the modules rather than
# being imported by them, so the §2 picture states no edges for them and their
# *outgoing* edges are outside the projection rule. Their incoming edges are
# not exempt: a module depending on a client is a real inversion and is
# reported. Recorded here because `AC-DEP-02.1` says "every edge" without
# saying which graph the four cross-cutting families belong to.
CROSS_CUTTING_SOURCES = frozenset({"core", "infra", "web", "mobile"})


@dataclass(frozen=True)
class EdgeViolation:
    requirement: str
    module: str
    dependency: str
    dependency_module: str

    def __str__(self) -> str:
        return (
            f"{self.requirement} ({self.module}) requires {self.dependency} "
            f"({self.dependency_module}) - no module-level edge "
            f"{self.module} -> {self.dependency_module}"
        )


def module_edge_violations(m: Manifest | None = None) -> list[EdgeViolation]:
    """`AC-DEP-02.1`: every manifest edge projects onto a module-level edge."""
    m = m or manifest()
    out: list[EdgeViolation] = []
    for entry in m:
        if entry.module in CROSS_CUTTING_SOURCES:
            continue
        for dependency in entry.requires:
            other = m[dependency].module
            if other in (entry.module, FOUNDATIONS):
                continue
            if other in MODULE_EDGES.get(entry.module, frozenset()):
                continue
            out.append(EdgeViolation(entry.id, entry.module, dependency, other))
    return out


def leaf_violations(m: Manifest | None = None) -> list[EdgeViolation]:
    """`AC-DEP-02.2`: `ai` and `connectors` have no outgoing edges to a module."""
    m = m or manifest()
    out: list[EdgeViolation] = []
    for entry in m:
        if entry.module not in LEAF_MODULES:
            continue
        for dependency in entry.requires:
            other = m[dependency].module
            if other in (entry.module, FOUNDATIONS):
                continue
            out.append(EdgeViolation(entry.id, entry.module, dependency, other))
    return out


def read_write_conflicts(m: Manifest | None = None) -> list[str]:
    """`AC-DEP-02.3`: no module both reads and writes another module's collections."""
    m = m or manifest()
    owner: dict[str, str] = {}
    for entry in m:
        for collection in entry.writes_collections:
            owner.setdefault(collection, entry.module)
    reads: dict[str, set[str]] = {}
    writes: dict[str, set[str]] = {}
    for entry in m:
        for collection in entry.reads_collections:
            reads.setdefault(entry.module, set()).add(collection)
        for collection in entry.writes_collections:
            writes.setdefault(entry.module, set()).add(collection)
    out: list[str] = []
    for module, written in writes.items():
        for collection in written:
            if owner.get(collection, module) != module:
                out.append(
                    f"{module} writes {collection}, owned by {owner[collection]}"
                )
    return sorted(out)


def satisfied_without(module: str, m: Manifest | None = None) -> list[str]:
    """`AC-DEP-02.4`: which requirements break if `module` is removed."""
    m = m or manifest()
    removed = {e.id for e in m if e.module == module}
    broken: list[str] = []
    for entry in m:
        if entry.module == module:
            continue
        for dependency in entry.requires:
            if dependency in removed:
                broken.append(f"{entry.id} requires {dependency} ({module})")
    return sorted(broken)


# ---------------------------------------------------------------------------
# DEP-03 - track closure
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TrackViolation:
    requirement: str
    dependency: str
    dependency_track: str
    path: list[str]

    def __str__(self) -> str:
        return (
            f"R1 {self.requirement} depends on {self.dependency_track} "
            f"{self.dependency} via {' -> '.join(self.path)}"
        )


def track_closure_violations(m: Manifest | None = None) -> list[TrackViolation]:
    """`AC-DEP-03.1`: the closure of every R1 requirement contains only R1."""
    m = m or manifest()
    out: list[TrackViolation] = []
    for entry in m:
        if entry.track != "R1":
            continue
        for dependency in sorted(m.closure(entry.id)):
            if m[dependency].track != "R1":
                trail = m.path_to(entry.id, dependency) or [entry.id, dependency]
                out.append(
                    TrackViolation(entry.id, dependency, m[dependency].track, trail)
                )
    return out


# ---------------------------------------------------------------------------
# DEP-04 - phase closure and the build order
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PhaseViolation:
    requirement: str
    phase: str | None
    dependency: str
    dependency_phase: str | None

    def __str__(self) -> str:
        return (
            f"{self.requirement} ({self.phase}) requires {self.dependency} "
            f"({self.dependency_phase}) - a later phase"
        )


def phase_closure_violations(m: Manifest | None = None) -> list[PhaseViolation]:
    """`AC-DEP-04.1`: every dependency sits in an earlier or equal phase."""
    m = m or manifest()
    out: list[PhaseViolation] = []
    for entry in m:
        if entry.phase is None:
            continue
        for dependency in entry.requires:
            other = m[dependency]
            if other.phase is None:
                continue
            if other.phase_index > entry.phase_index:
                out.append(
                    PhaseViolation(entry.id, entry.phase, dependency, other.phase)
                )
    return out


def build_order(m: Manifest | None = None) -> list[str]:
    """Topological sort, phase-major, ties broken by requirement id.

    Reproduces the algorithm in `docs/spec/gen_dependencies.py` exactly, because
    `AC-DEP-04.4` requires the rendered file to be byte-identical to the
    committed copy: walk the phases in order; inside a phase, repeatedly take
    every requirement whose dependencies are already placed, sorted by id; if
    none qualifies (a cycle, or a dependency in a later phase), force the
    lowest-id one so the order stays total.
    """
    m = m or manifest()
    from .manifest import PHASE_ORDER

    order: list[str] = []
    placed: set[str] = set()
    for phase in PHASE_ORDER:
        pool = [e for e in m if e.phase == phase]
        while pool:
            ready = sorted(
                (e for e in pool if all(r in placed for r in e.requires)),
                key=lambda e: e.id,
            )
            if not ready:
                ready = sorted(pool, key=lambda e: e.id)[:1]
            for entry in ready:
                order.append(entry.id)
                placed.add(entry.id)
                pool.remove(entry)
    return order


BUILD_ORDER_HEADER = (
    "# Build order — generated from dependencies.yaml\n"
    "\n"
    "Do not edit. Regenerate with `make build-order`.\n"
    "\n"
)


def render_build_order(m: Manifest | None = None) -> str:
    m = m or manifest()
    rows = []
    for position, requirement in enumerate(build_order(m), start=1):
        entry = m[requirement]
        phase = entry.phase or "unphased"
        rows.append(
            f"{position:3d}. `{entry.id}` — {phase} · {entry.track} · {entry.module}"
        )
    return BUILD_ORDER_HEADER + "\n".join(rows) + "\n"
