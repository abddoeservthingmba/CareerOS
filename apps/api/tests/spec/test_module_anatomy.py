"""T-FOUND-04.2 - every module has the same internal shape.

`AC-FOUND-04.2`: "Every `modules/*/` directory contains exactly the files in §5
below, and every one of them has an `__init__.py` whose `__all__` is non-empty
and contains no name defined in `models.py` or `repository.py`."

`01-foundations.md` §5's reason: "Identical internal shape for every module, so
that finding the business rule for anything takes one guess."
"""

from __future__ import annotations

import ast
from pathlib import Path

# `01-foundations.md` §5, exactly.
REQUIRED_FILES = (
    "__init__.py",
    "router.py",
    "schemas.py",
    "models.py",
    "service.py",
    "repository.py",
    "tasks.py",
    "events.py",
    "README.md",
)

# The pure-logic files §5 permits alongside them, per module.
OPTIONAL_FILES = (
    "scoring.py",
    "normalize.py",
    "state.py",
    "fabrication.py",
    "skills.py",
    "questions.yaml",
    "skills_seed.yaml",
    "title_families.yaml",
    "weights",
)


def module_dirs(repo: Path) -> list[Path]:
    base = repo / "apps" / "api" / "app" / "modules"
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir() and (p / "__init__.py").is_file())


def _defined_names(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return names


def _dunder_all(path: Path) -> list[str] | None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)
            and isinstance(node.value, ast.List)
        ):
            return [
                e.value
                for e in node.value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            ]
    return None


def test_every_module_has_the_required_files(repo: Path):
    """AC-FOUND-04.2, first half."""
    found = module_dirs(repo)
    # Vacuous while `app/modules/` is empty; the first module arrives with
    # `AUTH-01` in P1. Not skipped: `AC-FOUND-15.7` forbids a skipped test on
    # an R1 path, and a skip would hide this the day a module lands.
    for module in found:
        missing = [name for name in REQUIRED_FILES if not (module / name).is_file()]
        assert missing == [], f"{module.name} is missing {missing}"


def test_no_module_has_an_unexpected_file(repo: Path):
    """The shape is "exactly the files in §5", plus the pure-logic files it
    names. Anything else means the anatomy is drifting."""
    found = module_dirs(repo)
    # Vacuous while `app/modules/` is empty; the first module arrives with
    # `AUTH-01` in P1. Not skipped: `AC-FOUND-15.7` forbids a skipped test on
    # an R1 path, and a skip would hide this the day a module lands.
    permitted = set(REQUIRED_FILES) | set(OPTIONAL_FILES)
    for module in found:
        unexpected = sorted(
            entry.name
            for entry in module.iterdir()
            if entry.name not in permitted
            and entry.name != "__pycache__"
            and not entry.name.startswith(".")
        )
        assert unexpected == [], f"{module.name} has unexpected {unexpected}"


def test_every_all_is_non_empty(repo: Path):
    """AC-FOUND-04.2 - "`__all__` is non-empty"."""
    found = module_dirs(repo)
    # Vacuous while `app/modules/` is empty; the first module arrives with
    # `AUTH-01` in P1. Not skipped: `AC-FOUND-15.7` forbids a skipped test on
    # an R1 path, and a skip would hide this the day a module lands.
    for module in found:
        exported = _dunder_all(module / "__init__.py")
        assert exported is not None, f"{module.name}/__init__.py declares no __all__"
        assert exported, f"{module.name}/__init__.py exports nothing"


def test_no_model_or_repository_name_is_exported(repo: Path):
    """AC-FOUND-04.2 - "contains no name defined in `models.py` or
    `repository.py`". §5: "Never a Beanie document, never a repository"."""
    found = module_dirs(repo)
    # Vacuous while `app/modules/` is empty; the first module arrives with
    # `AUTH-01` in P1. Not skipped: `AC-FOUND-15.7` forbids a skipped test on
    # an R1 path, and a skip would hide this the day a module lands.
    for module in found:
        exported = set(_dunder_all(module / "__init__.py") or [])
        internal = _defined_names(module / "models.py") | _defined_names(module / "repository.py")
        leaked = sorted(exported & internal)
        assert leaked == [], f"{module.name} exports persistence names: {leaked}"


def test_the_required_file_list_is_the_one_the_spec_states():
    """The list is transcribed from §5, so the transcription is asserted."""
    assert REQUIRED_FILES == (
        "__init__.py",
        "router.py",
        "schemas.py",
        "models.py",
        "service.py",
        "repository.py",
        "tasks.py",
        "events.py",
        "README.md",
    )
