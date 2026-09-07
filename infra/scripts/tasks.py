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


def api(args: list[str]) -> int:
    """Run the API locally. `make up` needs Docker, which this machine lacks."""
    return run([sys.executable, str(ROOT / "infra" / "scripts" / "run_api.py"), *args])


def web(_: list[str]) -> int:
    return run(["npm", "run", "dev"], cwd=ROOT / "apps" / "web")


def import_contracts(_: list[str]) -> int:
    return run(
        [
            sys.executable,
            str(ROOT / "infra" / "scripts" / "gen_importlinter.py"),
            "--write",
        ]
    )


def lint_imports(_: list[str]) -> int:
    return uv(["run", "lint-imports", "--config", ".importlinter"], cwd=API)


def new_module(args: list[str]) -> int:
    if not args:
        print("usage: tasks.py new-module <name>", file=sys.stderr)
        return 2
    code = run(
        [sys.executable, str(ROOT / "infra" / "scripts" / "new_module.py"), args[0]]
    )
    return code or import_contracts([])


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


def events_doc(_: list[str]) -> int:
    target = ROOT / "docs" / "events.md"
    script = (
        "from app.core.events import render_events_doc; "
        f"open(r'{target}', 'w', encoding='utf-8', newline='')"
        ".write(render_events_doc())"
    )
    code = uv(["run", "python", "-c", script], cwd=API)
    if code == 0:
        print(f"wrote {target}")
    return code


def generate(_: list[str]) -> int:
    for target in (
        build_order,
        status,
        spec_trace,
        spec_metadata,
        error_codes,
        import_contracts,
        openapi,
    ):
        code = target([])
        if code != 0:
            return code
    return 0


def openapi(argv: list[str]) -> int:
    """`FOUND-13` - regenerate `packages/contracts/openapi.json`.

    The document is committed because it is the baseline an API diff is taken
    against (`AC-FOUND-13.4`): one that existed only at build time would have
    nothing to subtract from.
    """
    return uv(
        ["run", "python", "../../infra/scripts/export_openapi.py", "--write", *argv],
        cwd=API,
    )


def api_diff(argv: list[str]) -> int:
    """Classify a change to the API surface as additive or breaking.

    Locally this takes two files; in CI `contracts.yml` passes the base commit's
    document and the PR body. Available here so the answer can be had before the
    PR rather than from it.
    """
    return uv(["run", "python", "../../infra/scripts/diff_openapi.py", *argv], cwd=API)


def check(_: list[str]) -> int:
    """Everything that must be green before a commit."""
    for name, target in (
        ("lint", lint),
        ("lint-imports", lint_imports),
        ("types", types),
        ("test", test),
    ):
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
    "api": api,
    "web": web,
    "import-contracts": import_contracts,
    "lint-imports": lint_imports,
    "new-module": new_module,
    "error-codes": error_codes,
    "events-doc": events_doc,
    "openapi": openapi,
    "api-diff": api_diff,
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
