"""T-FOUND-04.4 - every module documents its contract.

`AC-FOUND-04.4`: "Every module has a `README.md` stating purpose, public API,
events published, and events consumed."

The events sections are the ones that earn their keep: `01-foundations.md` §9's
reaction graph is readable in one file, but knowing which module *reacts* to a
given event otherwise means grepping.
"""

from __future__ import annotations

from pathlib import Path

REQUIRED_HEADINGS = ("Purpose", "Public API", "Events published", "Events consumed")


def module_dirs(repo: Path) -> list[Path]:
    base = repo / "apps" / "api" / "app" / "modules"
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir() and (p / "__init__.py").is_file())


def test_every_module_has_a_readme(repo: Path):
    found = module_dirs(repo)
    # Vacuous while `app/modules/` is empty; the first module arrives with
    # `AUTH-01` in P1. Not skipped: `AC-FOUND-15.7` forbids a skipped test on
    # an R1 path, and a skip would hide this the day a module lands.
    for module in found:
        assert (module / "README.md").is_file(), f"{module.name} has no README.md"


def test_every_readme_has_the_four_sections(repo: Path):
    """AC-FOUND-04.4."""
    found = module_dirs(repo)
    # Vacuous while `app/modules/` is empty; the first module arrives with
    # `AUTH-01` in P1. Not skipped: `AC-FOUND-15.7` forbids a skipped test on
    # an R1 path, and a skip would hide this the day a module lands.
    for module in found:
        text = (module / "README.md").read_text(encoding="utf-8")
        missing = [h for h in REQUIRED_HEADINGS if f"## {h}" not in text]
        assert missing == [], f"{module.name}/README.md is missing {missing}"


def test_the_scaffold_produces_a_conforming_readme(repo: Path, tmp_path: Path):
    """The generator is what makes the criterion cheap to keep true, so it is
    asserted directly rather than only through the modules that exist."""
    import sys

    sys.path.insert(0, str(repo / "infra" / "scripts"))
    import new_module

    template = new_module.FILES["README.md"].format(name="demo", klass="Demo")
    missing = [h for h in REQUIRED_HEADINGS if f"## {h}" not in template]
    assert missing == [], f"the scaffold's README template is missing {missing}"
