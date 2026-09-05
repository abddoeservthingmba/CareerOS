#!/usr/bin/env python
"""The Makefile's targets, runnable without `make`.

`01-foundations.md` §1 requires a root `Makefile`, and CI runs it - the GitHub
runners have `make`. Windows development machines generally do not, and this
one does not, so the same targets live here too and the two are kept in step by
`tests/spec/test_task_parity.py`.

    py infra/scripts/tasks.py check
    py infra/scripts/tasks.py bundle MATCH-05
    py infra/scripts/tasks.py generate

`uv` needs the system certificate store on a machine whose TLS is intercepted,
so `UV_SYSTEM_CERTS` is set here rather than remembered.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "apps" / "api"

LINT_PATHS = ("apps/api", "infra/scripts")


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["UV_SYSTEM_CERTS"] = "1"
    env["PYTHONPATH"] = str(ROOT / "infra" / "scripts")
    return env


def run(command: list[str], cwd: Path = ROOT) -> int:
    print(f"$ {' '.join(command)}", flush=True)
    return subprocess.call(command, cwd=cwd, env=_env())


def uv(args: list[str], cwd: Path = ROOT) -> int:
    return run([sys.executable, "-m", "uv", *args], cwd)


def specgate(args: list[str]) -> int:
    return run([sys.executable, "-m", "specgate", *args])


# -- targets ----------------------------------------------------------------


def install(_: list[str]) -> int:
    return uv(["sync", "--project", "apps/api"])


def lint(_: list[str]) -> int:
    return uv(["run", "--project", "apps/api", "ruff", "check", *LINT_PATHS])


def format_(_: list[str]) -> int:
    return uv(["run", "--project", "apps/api", "ruff", "format", *LINT_PATHS])


def types(_: list[str]) -> int:
    return uv(["run", "mypy"], cwd=API)


def test(args: list[str]) -> int:
    return uv(["run", "pytest", *args], cwd=API)


def bundle(args: list[str]) -> int:
    if not args:
        print("usage: tasks.py bundle <REQUIREMENT-ID>", file=sys.stderr)
        return 2
    return specgate(["bundle", args[0]])


def build_order(_: list[str]) -> int:
    return specgate(["build-order", "--write"])


def status(_: list[str]) -> int:
    return specgate(["status", "--write"])


def spec_trace(_: list[str]) -> int:
    return specgate(["trace", "--write"])


def spec_trace_strict(_: list[str]) -> int:
    return specgate(["trace", "--strict"])


def spec_metadata(_: list[str]) -> int:
    return specgate(["spec-metadata", "--write"])


def check_spec(_: list[str]) -> int:
    return specgate(["check"])


def error_codes(_: list[str]) -> int:
    target = ROOT / "docs" / "error-codes.md"
    script = (
        "from app.core.errors import render_error_codes; "
        f"open(r'{target}', 'w', encoding='utf-8', newline='')"
        ".write(render_error_codes())"
    )
    code = uv(["run", "python", "-c", script], cwd=API)
    if code == 0:
        print(f"wrote {target}")
    return code


def generate(_: list[str]) -> int:
    for target in (build_order, status, spec_trace, spec_metadata, error_codes):
        code = target([])
        if code != 0:
            return code
    return 0


def check(_: list[str]) -> int:
    """Everything that must be green before a commit."""
    for name, target in (("lint", lint), ("types", types), ("test", test)):
        code = target([])
        if code != 0:
            print(f"\ncheck: {name} failed", file=sys.stderr)
            return code
    print("\ncheck: green")
    return 0


TARGETS = {
    "install": install,
    "lint": lint,
    "format": format_,
    "types": types,
    "test": test,
    "check": check,
    "bundle": bundle,
    "build-order": build_order,
    "status": status,
    "spec-trace": spec_trace,
    "spec-trace-strict": spec_trace_strict,
    "spec-metadata": spec_metadata,
    "check-spec": check_spec,
    "error-codes": error_codes,
    "generate": generate,
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        print("targets: " + ", ".join(sorted(TARGETS)))
        return 0 if argv else 2
    target = argv[0]
    if target not in TARGETS:
        print(
            f"unknown target {target!r}; try: {', '.join(sorted(TARGETS))}",
            file=sys.stderr,
        )
        return 2
    return TARGETS[target](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
