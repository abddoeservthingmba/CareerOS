"""Command line for the spec gates and generators.

python -m specgate bundle MATCH-05     DEP-06
python -m specgate build-order [--write]   DEP-04
python -m specgate trace [--write] [--strict]  FOUND-06
python -m specgate status [--write]    FOUND-15
python -m specgate check               everything, as `make check-spec` runs it
"""

from __future__ import annotations

import argparse
import sys

from . import bundle as bundle_mod
from . import graph, metadata, repo_root, status, traceability
from .manifest import manifest
from .parser import parse_spec


def _report(title: str, findings: list[str]) -> bool:
    if not findings:
        print(f"  ok    {title}")
        return True
    print(f"  FAIL  {title} ({len(findings)})")
    for line in findings[:20]:
        print(f"          {line}")
    if len(findings) > 20:
        print(f"          ... and {len(findings) - 20} more")
    return False


def cmd_bundle(args: argparse.Namespace) -> int:
    print(bundle_mod.render(args.requirement), end="")
    return 0


def cmd_build_order(args: argparse.Namespace) -> int:
    rendered = graph.render_build_order()
    target = repo_root() / "docs" / "spec" / "BUILD-ORDER.md"
    if args.write:
        target.write_text(rendered, encoding="utf-8", newline="")
        print(f"wrote {target}")
    else:
        print(rendered, end="")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    rendered = status.render()
    target = repo_root() / "docs" / "spec" / "status.yaml"
    if args.write:
        target.write_text(rendered, encoding="utf-8", newline="")
        print(f"wrote {target}")
    else:
        print(rendered, end="")
    return 0


def cmd_spec_metadata(args: argparse.Namespace) -> int:
    rendered = metadata.render()
    if args.write:
        metadata.target_path().write_text(rendered, encoding="utf-8", newline="")
        print(f"wrote {metadata.target_path()}")
    else:
        print(rendered, end="")
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    report = traceability.run(check_existence=args.strict)
    if args.write:
        target = repo_root() / "docs" / "spec" / "TRACEABILITY.md"
        target.write_text(traceability.render(), encoding="utf-8", newline="")
        print(f"wrote {target}")
    print(f"{report.criteria} acceptance criteria, {report.tests} tests named")
    ok = True
    ok &= _report(
        "every AC has a matching T in the same file",
        [str(f) for f in report.unmatched_criteria],
    )
    ok &= _report("every T names a test location", [str(f) for f in report.unlocatable_tests])
    ok &= _report(
        "every R1 requirement has criteria",
        [str(f) for f in report.requirements_without_criteria],
    )
    ok &= _report("no identifier defined twice", [str(f) for f in report.duplicate_definitions])
    if args.strict:
        ok &= _report("every named test file exists", [str(f) for f in report.missing_paths])
    return 0 if ok else 1


def cmd_check(args: argparse.Namespace) -> int:
    m = manifest()
    spec = parse_spec()
    ok = True

    print("DEP-01  manifest")
    ok &= _report(
        "no dangling requires",
        [f"{e.id} requires unknown {r}" for e in m for r in e.requires if r not in m],
    )
    ok &= _report("acyclic", [" -> ".join(c) for c in m.cycles()])

    print("DEP-02  module graph")
    ok &= _report(
        "edges project onto the module graph",
        [str(v) for v in graph.module_edge_violations(m)],
    )
    ok &= _report("ai and connectors are leaves", [str(v) for v in graph.leaf_violations(m)])
    ok &= _report("no cross-module collection writes", graph.read_write_conflicts(m))
    ok &= _report("admin can be removed", graph.satisfied_without("admin", m))

    print("DEP-03  track closure")
    ok &= _report(
        "R1 closure contains only R1",
        [str(v) for v in graph.track_closure_violations(m)],
    )

    print("DEP-04  phase closure")
    ok &= _report(
        "dependencies sit in an earlier or equal phase",
        [str(v) for v in graph.phase_closure_violations(m)],
    )
    committed = (repo_root() / "docs" / "spec" / "BUILD-ORDER.md").read_text(encoding="utf-8")
    ok &= _report(
        "BUILD-ORDER.md matches the graph",
        [] if graph.render_build_order(m) == committed else ["regenerate with `make build-order`"],
    )

    print("DEP-06  handoff bundle")
    oversized = bundle_mod.oversized(m, spec)
    ok &= _report(
        f"no R1 bundle exceeds {bundle_mod.MAX_FILES} files",
        [f"{r}: {n} files" for r, n in oversized.items()],
    )

    print("FOUND-06  traceability")
    ok &= cmd_trace(argparse.Namespace(strict=False, write=False)) == 0

    print("FOUND-15  status registry")
    undeclared = status.undeclared_sections(spec)
    if undeclared:
        # AC-FOUND-15.1, open by decision: no section carries a **Status:** line
        # yet, so the registry derives each state from the Track annotation. The
        # count is asserted by tests/spec/test_status_declared.py against the
        # ledger, so it cannot drift unnoticed. Reported, not failed.
        print(
            f"  open  {len(undeclared)} sections carry no Status line "
            "(AC-FOUND-15.1; state derived from Track)"
        )
    else:
        ok &= _report("every section declares a status", [])
    ok &= _report("status follows default-by-track", status.default_by_track_violations(spec))
    ok &= _report("no placeholder on an R1 path", status.placeholder_findings())
    ok &= _report("absent sections have no code", status.absent_findings(spec=spec))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="specgate")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("bundle")
    p.add_argument("requirement")
    p.set_defaults(func=cmd_bundle)

    p = sub.add_parser("build-order")
    p.add_argument("--write", action="store_true")
    p.set_defaults(func=cmd_build_order)

    p = sub.add_parser("status")
    p.add_argument("--write", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("trace")
    p.add_argument("--write", action="store_true")
    p.add_argument("--strict", action="store_true")
    p.set_defaults(func=cmd_trace)

    p = sub.add_parser("spec-metadata")
    p.add_argument("--write", action="store_true")
    p.set_defaults(func=cmd_spec_metadata)

    p = sub.add_parser("check")
    p.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    exit_code: int = args.func(args)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
