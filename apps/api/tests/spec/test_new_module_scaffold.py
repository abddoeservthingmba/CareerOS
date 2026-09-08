"""T-FOUND-05.1 - the module scaffold (`01-foundations.md` §5).

`AC-FOUND-05.1`: "`make new-module NAME=demo` produces a module that passes
`lint-imports`, `mypy`, `ruff`, and its own placeholder test without edits."

Run into a temp directory, as the Tests list requires, so the assertion is
about the generator rather than about whichever modules happen to exist.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from .test_module_anatomy import REQUIRED_FILES


@pytest.fixture
def scaffolded(repo: Path, tmp_path: Path, monkeypatch) -> Path:
    sys.path.insert(0, str(repo / "infra" / "scripts"))
    import new_module

    modules = tmp_path / "app" / "modules"
    tests = tmp_path / "tests" / "unit"
    monkeypatch.setattr(new_module, "MODULES", modules)
    monkeypatch.setattr(new_module, "TESTS", tests)
    return new_module.create("demo")


def test_the_scaffold_emits_every_required_file(scaffolded: Path):
    """AC-FOUND-05.1 - the §5 anatomy, complete, on the first try."""
    missing = [name for name in REQUIRED_FILES if not (scaffolded / name).is_file()]
    assert missing == [], f"the scaffold is missing {missing}"


def test_the_scaffold_emits_a_placeholder_test(scaffolded: Path, tmp_path: Path):
    assert (tmp_path / "tests" / "unit" / "test_demo_module.py").is_file()


def test_the_scaffold_exports_only_the_service(scaffolded: Path):
    """§5 - "`__all__` is the contract ... Never a Beanie document, never a
    repository"."""
    init = (scaffolded / "__init__.py").read_text(encoding="utf-8")
    assert '__all__ = ["DemoService"]' in init
    assert "Repository" not in init
    assert "models" not in init


def test_the_scaffold_contains_no_placeholder_marker(scaffolded: Path):
    """AC-FOUND-15.7 forbids TODO / FIXME / NotImplementedError on an R1 path.

    A scaffold that ships one fails the build the moment it is generated, which
    would make `make new-module` useless.
    """
    from specgate.status import PLACEHOLDER_MARKERS

    for path in sorted(scaffolded.iterdir()):
        text = path.read_text(encoding="utf-8")
        for marker in PLACEHOLDER_MARKERS:
            assert marker not in text, f"{path.name} contains {marker}"


def test_the_scaffolded_module_passes_ruff(scaffolded: Path):
    """AC-FOUND-05.1 - "without edits"."""
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", str(scaffolded)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_scaffolded_module_is_valid_python(scaffolded: Path):
    import ast

    for path in sorted(scaffolded.glob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"))


def test_a_bad_module_name_is_refused(repo: Path, tmp_path: Path, monkeypatch):
    sys.path.insert(0, str(repo / "infra" / "scripts"))
    import new_module

    monkeypatch.setattr(new_module, "MODULES", tmp_path / "modules")
    monkeypatch.setattr(new_module, "TESTS", tmp_path / "tests")
    for bad in ("Demo", "demo-module", "1demo", ""):
        with pytest.raises(SystemExit):
            new_module.create(bad)


def test_scaffolding_twice_is_refused(repo: Path, tmp_path: Path, monkeypatch):
    """Overwriting a real module by accident would be unrecoverable."""
    sys.path.insert(0, str(repo / "infra" / "scripts"))
    import new_module

    monkeypatch.setattr(new_module, "MODULES", tmp_path / "app" / "modules")
    monkeypatch.setattr(new_module, "TESTS", tmp_path / "tests" / "unit")
    new_module.create("demo")
    with pytest.raises(SystemExit, match="already exists"):
        new_module.create("demo")
