#!/usr/bin/env python
"""Scaffold a module - `FOUND-05`.

`01-foundations.md` §5: "Identical internal shape for every module, so that
finding the business rule for anything takes one guess."

`AC-FOUND-05.1`: "`make new-module NAME=demo` produces a module that passes
`lint-imports`, `mypy`, `ruff`, and its own placeholder test without edits."

The generated module is deliberately minimal but complete: every file §5 names,
a `README.md` with the four headings `AC-FOUND-04.4` requires, an `__init__.py`
whose `__all__` exports the service and nothing from `models.py` or
`repository.py`, and one passing test. It contains no placeholder markers,
because `AC-FOUND-15.7` forbids them on an R1 path, so a scaffold that shipped
one would fail the build the moment it was generated.

    py infra/scripts/new_module.py demo
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "apps" / "api" / "app" / "modules"
TESTS = ROOT / "apps" / "api" / "tests" / "unit"

NAME = re.compile(r"^[a-z][a-z0-9_]*$")

FILES: dict[str, str] = {
    "__init__.py": '''"""The {name} module's public API.

`01-foundations.md` §5: "`__all__` is the contract." A module's `__init__.py`
exports only its service class, its DTOs from `schemas.py`, its published event
types, and its exceptions - never a Beanie document, never a repository.
"""

from app.modules.{name}.service import {klass}Service

__all__ = ["{klass}Service"]
''',
    "router.py": '''"""HTTP for the {name} module.

Thin: validate -> call one service method -> map to a response. A route function
is at most ~15 lines and contains no `if` on business state
(`AC-FOUND-05.2`).
"""

from __future__ import annotations
''',
    "schemas.py": '''"""Pydantic DTOs for the {name} module - the API contract.

Separate from `models.py`, always: a response shape and a persistence shape that
share a class drift into each other.
"""

from __future__ import annotations
''',
    "models.py": '''"""Beanie documents for the {name} module - persistence only.

Never returned from a route (`AC-FOUND-05.4`), and never exported from
`__init__.py`.
"""

from __future__ import annotations
''',
    "service.py": '''"""Use cases for the {name} module - the ONLY place business rules live.

A service method never touches `fastapi`, never builds a Mongo filter, and never
calls an HTTP client directly; it calls an `infra` or `ai` interface.
"""

from __future__ import annotations


class {klass}Service:
    """Business rules for {name}."""
''',
    "repository.py": '''"""Queries for the {name} module.

Hides every Mongo detail, including index choices. A repository method never
contains a business rule: "active jobs for a user" belongs here, "should this
user see this job" belongs in `service.py`.
"""

from __future__ import annotations
''',
    "tasks.py": '''"""ARQ tasks for the {name} module.

Thin wrappers that call service methods. A task receives **IDs and small
scalars only** (`01-foundations.md` §10), and each states its idempotency key in
a docstring line beginning `Idempotency key:`.
"""

from __future__ import annotations
''',
    "events.py": '''"""Domain events the {name} module publishes.

Frozen, past-tense, carrying **IDs and primitives only** - no documents, no
nested aggregates (`01-foundations.md` §9).
"""

from __future__ import annotations
''',
    "README.md": """# {name}

## Purpose

What this module is responsible for.

## Public API

`{klass}Service` - see `__init__.py`'s `__all__`, which is the contract.

## Events published

None yet.

## Events consumed

None yet.
""",
}

TEST_TEMPLATE = '''"""Placeholder test for the {name} module.

`AC-FOUND-05.1`: a scaffolded module passes its own test without edits. This
asserts the anatomy rather than behaviour, so it stays meaningful as the module
fills in rather than being deleted on the first real commit.
"""

from __future__ import annotations

import app.modules.{name} as module


def test_the_public_surface_is_the_service():
    assert module.__all__ == ["{klass}Service"]
    assert hasattr(module, "{klass}Service")


def test_no_document_or_repository_is_exported():
    """§5 - "Never a Beanie document, never a repository"."""
    for name in module.__all__:
        assert not name.endswith("Repository")
        assert not name.endswith("Document")
'''


def klass_for(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


def create(name: str, force: bool = False) -> Path:
    if not NAME.fullmatch(name):
        raise SystemExit(f"module name must be lower_snake_case, got {name!r}")

    target = MODULES / name
    if target.exists() and not force:
        raise SystemExit(f"{target} already exists")
    target.mkdir(parents=True, exist_ok=True)

    klass = klass_for(name)
    for filename, template in FILES.items():
        (target / filename).write_text(
            template.format(name=name, klass=klass), encoding="utf-8", newline=""
        )

    TESTS.mkdir(parents=True, exist_ok=True)
    (TESTS / f"test_{name}_module.py").write_text(
        TEST_TEMPLATE.format(name=name, klass=klass), encoding="utf-8", newline=""
    )
    return target


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Scaffold a module (FOUND-05).")
    parser.add_argument("name", help="lower_snake_case module name")
    parser.add_argument(
        "--force", action="store_true", help="overwrite an existing module"
    )
    args = parser.parse_args(argv)

    target = create(args.name, force=args.force)
    print(f"created {target}")
    print("now run: py infra/scripts/gen_importlinter.py --write")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
