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
