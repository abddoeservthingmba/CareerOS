"""The Makefile and the task runner offer the same targets.

`01-foundations.md` §1 requires a root `Makefile`, and CI runs it. Windows
development machines generally lack `make`, so `infra/scripts/tasks.py` carries
the same targets. Two entry points that drift are worse than one, so the target
sets are asserted equal: a target added to either must be added to both.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

MAKE_TARGET = re.compile(r"^([a-z][a-z0-9_-]*):.*?##", re.MULTILINE)


def make_targets(repo: Path) -> set[str]:
    makefile = repo / "Makefile"
    assert makefile.is_file(), "01-foundations.md §1 requires a root Makefile"
    return set(MAKE_TARGET.findall(makefile.read_text(encoding="utf-8")))


def task_targets(repo: Path) -> set[str]:
    sys.path.insert(0, str(repo / "infra" / "scripts"))
    import tasks

    return set(tasks.TARGETS)


def test_the_two_entry_points_offer_the_same_targets(repo: Path):
    make = make_targets(repo) - {"help"}  # `help` lists the Makefile's own targets
    tasks = task_targets(repo)
    assert make == tasks, (
        f"only in Makefile: {sorted(make - tasks)}\nonly in tasks.py: {sorted(tasks - make)}"
    )


def test_check_is_the_gate_claude_md_names(repo: Path):
    """CLAUDE.md's per-requirement loop runs `make check`, so it must exist and
    must cover lint, types and tests."""
    assert "check" in make_targets(repo)
    makefile = (repo / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^check:\s*lint lint-imports types test", makefile, re.MULTILINE), (
        "make check must run lint, types and test"
    )


# -- the workflow runs the same commands -------------------------------------
#
# The tests above compared target *names*. That is what let three definitions of
# "lint" coexist: the Makefile linted `apps/api/tests` and not `apps/api/app`,
# `tasks.py` linted `apps/api` from the repository root, and `api-ci.yml` linted
# `../../apps/api` from `apps/api`. All three had a target called `lint`, so name
# parity was green for six commits while CI failed on its first step.
#
# Ruff's configuration discovery depends on the working directory, and the only
# config here is `apps/api/pyproject.toml`. So the CI invocation applied
# line-length 100 and `E,F,I,UP,B,SIM` to `infra/scripts` while both local ones
# fell back to ruff's built-in defaults: same files, same ruff, same lockfile,
# different answer.
#
# These compare what actually runs.

WORKFLOW = Path(".github") / "workflows" / "api-ci.yml"


def workflow_steps(repo: Path) -> dict[str, Any]:
    """`api-ci.yml`'s `checks` job, by step name."""
    import yaml

    workflow = yaml.safe_load((repo / WORKFLOW).read_text(encoding="utf-8"))
    return {
        str(step.get("name")): step
        for step in workflow["jobs"]["checks"]["steps"]
        if step.get("name")
    }


def _tasks(repo: Path):
    sys.path.insert(0, str(repo / "infra" / "scripts"))
    import tasks

    return tasks


def test_the_workflow_lints_the_paths_tasks_py_lints(repo: Path):
    """The divergence that caused this section to exist.

    Compared as the set of paths, because that is what differed - the workflow
    covered `apps/api` and the Makefile covered `apps/api/tests`, so
    `apps/api/app` was linted by CI and by nothing a developer ran.
    """
    step = workflow_steps(repo)["ruff"]

    assert step.get("working-directory") == "apps/api", (
        "the workflow's ruff step must run from apps/api - ruff's config "
        "discovery depends on the working directory, and apps/api/pyproject.toml "
        "is the only config in this repository"
    )
    for path in _tasks(repo).LINT_PATHS:
        assert path in str(step["run"]), f"the workflow's ruff step does not cover {path}"


def test_the_workflow_format_check_matches(repo: Path):
    """`ruff format --check`, over the same paths, from the same directory.

    `--check` rather than a rewrite: CI cannot commit, so a workflow that
    rewrote files would pass while leaving the repository unformatted.
    """
    step = workflow_steps(repo)["ruff format"]
    run = str(step["run"])

    assert step.get("working-directory") == "apps/api"
    assert "--check" in run
    for path in _tasks(repo).LINT_PATHS:
        assert path in run


def test_the_lint_paths_cover_the_application_and_not_only_the_tests(repo: Path):
    """The specific hole: a `lint` target that skipped `apps/api/app`.

    Asserted on resolved directories rather than on the strings, so a
    respelling that still misses the application fails.
    """
    tasks = _tasks(repo)
    covered = {(repo / "apps" / "api" / path).resolve() for path in tasks.LINT_PATHS}

    assert (repo / "apps" / "api").resolve() in covered, (
        "apps/api is not linted, so apps/api/app is not linted"
    )
    assert (repo / "infra" / "scripts").resolve() in covered, "infra/scripts is not linted"


def test_the_makefile_gate_delegates_rather_than_duplicating(repo: Path):
    """One definition of each command.

    The Makefile is required by `01-foundations.md` §1 and CI may call either
    entry point, so both have to mean the same thing. Delegation is the only
    arrangement where that is true by construction rather than by comparison.
    """
    makefile = (repo / "Makefile").read_text(encoding="utf-8")

    for target in ("lint", "format", "format-check", "types", "test"):
        body = re.search(rf"^{re.escape(target)}:.*?\n\t(.+)$", makefile, re.MULTILINE)
        assert body is not None, f"the Makefile has no body for {target}"
        assert "$(TASKS)" in body.group(1), (
            f"make {target} does not delegate to tasks.py: {body.group(1)!r}. Three "
            "definitions of one command is how CI and the local gate came to disagree."
        )


def test_every_gate_step_in_the_workflow_has_a_local_equivalent(repo: Path):
    """A CI step nobody can run locally is a step that fails for the first time
    on a push."""
    equivalents = {
        "ruff": "lint",
        "ruff format": "format-check",
        "import-linter": "lint-imports",
        "mypy": "types",
        "pytest": "test",
        "spec gates": "check-spec",
        "generated artifacts are current": "generate",
    }
    steps = workflow_steps(repo)
    targets = _tasks(repo).TARGETS

    for step, target in equivalents.items():
        assert step in steps, f"api-ci.yml has no {step!r} step"
        assert target in targets, f"tasks.py has no {target!r} target for {step!r}"


def test_the_workflow_supplies_what_the_test_suite_needs(repo: Path):
    """`tests/conftest.py` raises without `MONGODB_URI`, deliberately -
    `AC-FOUND-15.7` forbids a skipped test on an R1 path, so a missing database
    is a loud failure rather than a quiet no-op.

    Which means the workflow has to provide one. It did not: the conftest's
    docstring said "a service container in CI" and there was no container, so
    every integration test would have failed the moment `ruff` stopped failing
    first.
    """
    import yaml

    workflow = yaml.safe_load((repo / WORKFLOW).read_text(encoding="utf-8"))
    job = workflow["jobs"]["checks"]

    assert "mongo" in job.get("services", {}), (
        "api-ci.yml has no MongoDB service; tests/conftest.py requires a real one "
        "because DATA-03 and DATA-05 assert Mongo's own index, TTL and "
        "partial-filter behaviour and nothing in-memory shares it"
    )
    environment: dict[str, str] = workflow_steps(repo)["pytest"].get("env", {})
    assert "MONGODB_URI" in environment
    assert "SECRET_KEY" in environment, (
        "Settings has required fields with no defaults and .env is gitignored, "
        "so CI has to supply them"
    )


def test_the_contracts_workflow_uses_a_valid_app_env(repo: Path):
    """`APP_ENV` is `Literal["local", "staging", "prod"]`.

    `contracts.yml` set `test`, which failed `Settings` validation on every run
    that workflow has ever had - its export step never once produced a document.
    Asserted against the type rather than the string, so a fourth environment
    added to `Settings` does not need this test edited.
    """
    import yaml

    from app.core.config import AppEnv

    workflow = yaml.safe_load(
        (repo / ".github" / "workflows" / "contracts.yml").read_text(encoding="utf-8")
    )
    steps = {s.get("name"): s for s in workflow["jobs"]["contract"]["steps"] if s.get("name")}
    configured = steps["export-openapi"]["env"]["APP_ENV"]

    valid = {member.value for member in AppEnv}
    assert configured in valid, (
        f"contracts.yml sets APP_ENV={configured!r}, which Settings rejects; valid: {sorted(valid)}"
    )
