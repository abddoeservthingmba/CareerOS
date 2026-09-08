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
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "apps" / "api"

#: The paths ruff and `ruff format` cover, **spelled as `api-ci.yml` spells
#: them** - relative to `apps/api`, because that is the workflow's
#: `working-directory` and ruff's configuration discovery depends on the
#: working directory.
#:
#: There is exactly one ruff config in this repository, `apps/api/pyproject.toml`,
#: and no root `pyproject.toml`. For a file under `infra/scripts`, ruff walks up
#: from the file, finds nothing, and falls back to the config discovered from the
#: *current directory*. Run from `apps/api` that is our config: line-length 100
#: and `E,F,I,UP,B,SIM`. Run from the repository root it is ruff's built-in
#: default: line-length 88 and a much smaller rule set.
#:
#: So the same files, the same ruff and the same lockfile produced a pass
#: locally and a failure in CI for six commits. The lesson is not "remember the
#: directory" - it is that a local gate which does not run the CI command is not
#: a gate. `tests/spec/test_task_parity.py` now compares the two.
LINT_PATHS = ("../../apps/api", "../../infra/scripts")


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["UV_SYSTEM_CERTS"] = "1"
    env["PYTHONPATH"] = str(ROOT / "infra" / "scripts")
    return env


def run(command: list[str], cwd: Path = ROOT) -> int:
    print(f"$ {' '.join(command)}", flush=True)
    return subprocess.call(command, cwd=cwd, env=_env())


def venv_bin(name: str) -> str:
    """A tool from `apps/api/.venv`, by absolute path.

    **Not `uv run <tool>`, and that is the fix for a whole class of failure.**
    `uv run` needs `uv`, and how to reach `uv` depends on how this script was
    launched:

    * `py infra/scripts/tasks.py` - the launcher is the system Python, and
      `sys.executable -m uv` works;
    * `uv run --project apps/api python infra/scripts/tasks.py` - which is how
      `api-ci.yml` invokes it - the launcher is the project venv, which has no
      `uv` module, and `uv` is not on the subprocess PATH either.

    The second is how `generate` came to die at `error-codes` with "No module
    named uv" on every CI run. And because the step's `git diff` never ran, no
    check ever reported whether the committed artifacts were stale.

    Every tool this script needs is already installed in the project venv as an
    executable, so addressing it directly removes the launcher from the
    question. `uv` is used for one thing only now: `install`, which is the one
    target whose job *is* to manage the environment.
    """
    scripts = API / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    exe = scripts / (f"{name}.exe" if os.name == "nt" else name)
    if exe.is_file():
        return str(exe)
    # No venv yet - `install` has not run. Fall back to whatever launched us,
    # which is right when that is already the project interpreter.
    found = shutil.which(name)
    return found or str(exe)


def venv_python() -> str:
    """The interpreter with the app importable."""
    return venv_bin("python")


def uv(args: list[str], cwd: Path = ROOT) -> int:
    """Only `install` uses this - see `venv_bin`."""
    command = [sys.executable, "-m", "uv"]
    probe = subprocess.run([*command, "--version"], capture_output=True, cwd=ROOT)
    if probe.returncode != 0:
        found = shutil.which("uv")
        if found is None:
            print(
                "uv is not available as a module or on PATH. Install it with `pip install uv`.",
                file=sys.stderr,
            )
            return 2
        command = [found]
    return run([*command, *args], cwd)


def specgate(args: list[str]) -> int:
    return run([venv_python(), "-m", "specgate", *args])


# -- targets ----------------------------------------------------------------


def install(_: list[str]) -> int:
    return uv(["sync", "--project", "apps/api"])


def lint(_: list[str]) -> int:
    """`api-ci.yml`'s `ruff` step, verbatim - same cwd, same paths."""
    return run([venv_bin("ruff"), "check", *LINT_PATHS], cwd=API)


def format_check(_: list[str]) -> int:
    """`api-ci.yml`'s `ruff format` step. `--check`, because CI does not rewrite
    files and a local target that did would hide the difference."""
    return run([venv_bin("ruff"), "format", "--check", *LINT_PATHS], cwd=API)


def format_(_: list[str]) -> int:
    """Rewrite. Not what CI runs, and deliberately a separate target so
    `format` cannot be mistaken for the check that gates a merge."""
    return run([venv_bin("ruff"), "format", *LINT_PATHS], cwd=API)


def types(_: list[str]) -> int:
    return run([venv_bin("mypy")], cwd=API)


def test(args: list[str]) -> int:
    return run([venv_bin("pytest"), *args], cwd=API)


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
    return run([venv_bin("lint-imports"), "--config", ".importlinter"], cwd=API)


def new_module(args: list[str]) -> int:
    if not args:
        print("usage: tasks.py new-module <name>", file=sys.stderr)
        return 2
    code = run([sys.executable, str(ROOT / "infra" / "scripts" / "new_module.py"), args[0]])
    return code or import_contracts([])


def error_codes(_: list[str]) -> int:
    target = ROOT / "docs" / "error-codes.md"
    script = (
        "from app.core.errors import render_error_codes; "
        f"open(r'{target}', 'w', encoding='utf-8', newline='')"
        ".write(render_error_codes())"
    )
    code = run([venv_python(), "-c", script], cwd=API)
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
    code = run([venv_python(), "-c", script], cwd=API)
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
    return run(
        [venv_python(), "../../infra/scripts/export_openapi.py", "--write", *argv],
        cwd=API,
    )


def api_diff(argv: list[str]) -> int:
    """Classify a change to the API surface as additive or breaking.

    Locally this takes two files; in CI `contracts.yml` passes the base commit's
    document and the PR body. Available here so the answer can be had before the
    PR rather than from it.
    """
    return run([venv_python(), "../../infra/scripts/diff_openapi.py", *argv], cwd=API)


def check(_: list[str]) -> int:
    """Everything that must be green before a commit."""
    for name, target in (
        ("lint", lint),
        ("format-check", format_check),
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
    "format-check": format_check,
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
