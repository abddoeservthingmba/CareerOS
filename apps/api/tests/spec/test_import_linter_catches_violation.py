"""T-FOUND-04.3 - the contracts actually catch a violation.

`AC-FOUND-04.3`: "A deliberately introduced cross-module model import fails CI
(verified by a test that runs `lint-imports` against a fixture package
containing the violation)."

Extended by `T-AI-05.3` with the OAuth fixture (`AC-AI-05.3`): "a fixture that
adds `import google.auth` to `ai/gemini.py` fails CI".

A green contract set proves nothing on its own - contracts that bind no code, or
a config the tool silently ignores, also come out green. This runs the linter
against a tree that *should* fail and asserts that it does.
"""

from __future__ import annotations

import configparser
import shutil
import subprocess
import sys
from pathlib import Path


def lint_imports_command() -> list[str]:
    """The `lint-imports` entry point, resolved inside whatever venv is running.

    `python -m importlinter.cli` is a Click *group* and exits 0 without doing
    anything, which would make every fixture below pass for the wrong reason.
    The console script is the only invocation that runs the check.
    """
    script = shutil.which("lint-imports")
    if script:
        return [script]
    candidate = Path(sys.executable).parent / "lint-imports"
    return [str(candidate)]


def _fixture_tree(repo: Path, tmp_path: Path) -> Path:
    """A copy of the app with the real contracts, ready to be broken."""
    api = repo / "apps" / "api"
    workspace = tmp_path / "api"
    workspace.mkdir()
    shutil.copytree(
        api / "app",
        workspace / "app",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy(api / ".importlinter", workspace / ".importlinter")
    return workspace


def _lint(workspace: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*lint_imports_command(), "--config", ".importlinter"],
        cwd=workspace,
        capture_output=True,
        text=True,
    )


def test_the_fixture_tree_is_clean_before_it_is_broken(repo: Path, tmp_path: Path):
    """Without this, a fixture that fails for an unrelated reason would look
    like the contract working."""
    workspace = _fixture_tree(repo, tmp_path)
    result = _lint(workspace)
    assert result.returncode == 0, (
        "the unmodified copy must pass, or the tests below prove nothing:\n"
        + result.stdout
        + result.stderr
    )


def test_an_ai_module_importing_a_feature_module_fails(repo: Path, tmp_path: Path):
    """AC-FOUND-04.3 - `ai-is-leaf`. `ai` may not reach into `modules`."""
    workspace = _fixture_tree(repo, tmp_path)
    (workspace / "app" / "modules" / "victim").mkdir(parents=True)
    (workspace / "app" / "modules" / "victim" / "__init__.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    violation = workspace / "app" / "ai" / "leak.py"
    violation.write_text("from app.modules.victim import VALUE\n\nUSED = VALUE\n", encoding="utf-8")

    result = _lint(workspace)
    assert result.returncode != 0, "ai-is-leaf did not catch ai -> modules"
    assert "ai-is-leaf" in result.stdout


def test_a_connector_importing_ai_fails(repo: Path, tmp_path: Path):
    """`connectors-are-leaf`: "A connector normalizes; enrichment is the
    ingestion service's job"."""
    workspace = _fixture_tree(repo, tmp_path)
    violation = workspace / "app" / "connectors" / "leak.py"
    violation.write_text("from app.ai import base\n\nUSED = base\n", encoding="utf-8")

    result = _lint(workspace)
    assert result.returncode != 0, "connectors-are-leaf did not catch connectors -> ai"
    assert "connectors-are-leaf" in result.stdout


def test_a_module_importing_a_concrete_adapter_fails(repo: Path, tmp_path: Path):
    """HR-5 / `no-concrete-ai` - a feature module names a capability, never a
    provider."""
    workspace = _fixture_tree(repo, tmp_path)
    (workspace / "app" / "modules" / "greedy").mkdir(parents=True)
    (workspace / "app" / "modules" / "greedy" / "__init__.py").write_text(
        "from app.ai.stubs import OpenAIProvider\n\nUSED = OpenAIProvider\n",
        encoding="utf-8",
    )

    result = _lint(workspace)
    assert result.returncode != 0, "no-concrete-ai did not catch modules -> ai.stubs"
    assert "no-concrete-ai" in result.stdout


def test_shared_importing_core_fails(repo: Path, tmp_path: Path):
    """`layers` - `shared` is the innermost layer.

    This is the violation the contract caught for real: `shared/ulid.py`
    originally imported `core.clock`, which is why `new_ulid` takes its instant
    explicitly and `core.ids.new_id` supplies it.
    """
    workspace = _fixture_tree(repo, tmp_path)
    violation = workspace / "app" / "shared" / "leak.py"
    violation.write_text("from app.core import clock\n\nUSED = clock\n", encoding="utf-8")

    result = _lint(workspace)
    assert result.returncode != 0, "layers did not catch shared -> core"
    assert "layers" in result.stdout


def test_an_oauth_import_in_the_ai_path_fails(repo: Path, tmp_path: Path):
    """AC-AI-05.3 / HR-6, the `authlib` half.

    `google.auth` cannot be expressed as an import-linter contract - subpackages
    of external packages are not valid targets, and forbidding `google`
    wholesale would also forbid `google.genai`, which `ai/gemini.py` needs. That
    half is asserted by `test_no_google_credential_import_in_ai` in
    `test_import_contracts.py`.
    """
    workspace = _fixture_tree(repo, tmp_path)
    violation = workspace / "app" / "ai" / "oauth_leak.py"
    violation.write_text("import authlib\n\nUSED = authlib\n", encoding="utf-8")

    result = _lint(workspace)
    assert result.returncode != 0, "no-oauth-in-ai did not catch ai -> authlib"
    assert "no-oauth-in-ai" in result.stdout


def test_two_modules_importing_each_others_internals_fails(repo: Path, tmp_path: Path):
    """AC-FOUND-04.3, the criterion's own wording: "a deliberately introduced
    cross-module model import"."""
    workspace = _fixture_tree(repo, tmp_path)
    for name in ("alpha", "beta"):
        module = workspace / "app" / "modules" / name
        module.mkdir(parents=True)
        (module / "__init__.py").write_text("", encoding="utf-8")
        (module / "models.py").write_text("VALUE = 1\n", encoding="utf-8")
        (module / "service.py").write_text("", encoding="utf-8")
    # alpha reaches into beta's models - forbidden by `module-independence`.
    (workspace / "app" / "modules" / "alpha" / "service.py").write_text(
        "from app.modules.beta.models import VALUE\n\nUSED = VALUE\n", encoding="utf-8"
    )

    # `module-independence` enumerates modules by name, so the copied contract
    # lists the nine real ones and knows nothing about `alpha` and `beta`. The
    # fixture has to extend it, or the violation it introduces is not covered by
    # any contract and this test passes for the wrong reason - which is exactly
    # what happened when `DATA-02` created the first real modules: the assertion
    # went from "the contract is absent, nothing to violate" straight to
    # "lint-imports found nothing wrong".
    _register_fixture_modules(workspace, ("alpha", "beta"))

    result = _lint(workspace)
    assert result.returncode != 0, (
        "module-independence did not catch alpha -> beta.models:\n" + result.stdout
    )
    assert "module-independence" in result.stdout


def _register_fixture_modules(workspace: Path, names: tuple[str, ...]) -> None:
    """Add `names` to the copied contract's `module-independence` list.

    Editing the copy rather than re-running the generator: the generator reads
    the *repository's* `app/modules/`, not the workspace's, so regenerating
    would produce the same nine names and leave the fixture uncovered.
    """
    config = configparser.ConfigParser()
    config.read(workspace / ".importlinter", encoding="utf-8")
    section = "importlinter:contract:module-independence"

    assert section in config.sections(), (
        f"the copied contract has no {section}. It is emitted once a real module "
        "exists, and `DATA-02` landed nine - so its absence now means the "
        "generator stopped emitting it."
    )
    existing = [line for line in config[section]["modules"].split("\n") if line.strip()]
    config[section]["modules"] = "\n".join(existing + [f"app.modules.{name}" for name in names])
    with (workspace / ".importlinter").open("w", encoding="utf-8") as handle:
        config.write(handle)
