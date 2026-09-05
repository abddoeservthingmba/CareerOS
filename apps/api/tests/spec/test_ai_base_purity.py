"""T-AI-01.1 - `ai/base.py` touches no network and no provider SDK.

`AC-AI-01.1`: "`ai/base.py` imports nothing outside the standard library,
`pydantic`, and `app.shared` - in particular no HTTP client and no provider
SDK."

This is what makes HR-5 structural. A contract file that can reach `httpx` will
eventually contain a call, and then a provider type is in a signature.
"""

from __future__ import annotations

import ast
from pathlib import Path

BASE = "apps/api/app/ai/base.py"

PERMITTED_THIRD_PARTY = {"pydantic"}
PERMITTED_FIRST_PARTY_PREFIX = "app.shared"

FORBIDDEN = {
    # HTTP clients
    "httpx",
    "requests",
    "aiohttp",
    "urllib3",
    "http.client",
    # Provider SDKs (HR-5)
    "google",
    "google.genai",
    "google.generativeai",
    "openai",
    "anthropic",
    "ollama",
    "cohere",
    "mistralai",
    # Anything that would make the contract file do I/O
    "motor",
    "pymongo",
    "redis",
    "boto3",
    "fastapi",
    "starlette",
}

STDLIB_ALLOWED = {
    "__future__",
    "collections",
    "collections.abc",
    "dataclasses",
    "enum",
    "typing",
    "abc",
    "types",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_base_imports_nothing_it_should_not(repo: Path):
    """AC-AI-01.1."""
    imported = _imports(repo / BASE)
    for name in sorted(imported):
        root = name.split(".")[0]
        if name in STDLIB_ALLOWED or root in STDLIB_ALLOWED:
            continue
        if root in PERMITTED_THIRD_PARTY:
            continue
        if name.startswith(PERMITTED_FIRST_PARTY_PREFIX):
            continue
        raise AssertionError(
            f"{BASE} imports {name!r}; only the standard library, "
            f"{sorted(PERMITTED_THIRD_PARTY)} and {PERMITTED_FIRST_PARTY_PREFIX} are allowed"
        )


def test_no_forbidden_import_anywhere_in_base(repo: Path):
    imported = _imports(repo / BASE)
    offending = sorted({n for n in imported if n.split(".")[0] in FORBIDDEN})
    assert offending == [], f"{BASE} must not import {offending}"


def test_no_provider_sdk_outside_its_own_adapter(repo: Path):
    """AC-AI-01.3 / AC-FOUND-01.4 - no provider SDK import outside `ai/<provider>.py`.

    Shared with `T-FOUND-01.4` (`tests/spec/test_layer_leaks.py`), which runs
    the same search across the whole tree; here it is asserted for the AI
    package specifically, because that is where the temptation lives.
    """
    sdk_roots = {"openai", "anthropic", "ollama", "cohere", "mistralai"}
    google_sdks = {"google.genai", "google.generativeai"}
    base = repo / "apps" / "api" / "app" / "ai"
    offenders: list[str] = []
    for path in sorted(base.rglob("*.py")):
        stem = path.stem
        for name in _imports(path):
            root = name.split(".")[0]
            if root in sdk_roots and stem != root:
                offenders.append(f"{path.relative_to(repo).as_posix()} imports {name}")
            if name in google_sdks and stem != "gemini":
                offenders.append(f"{path.relative_to(repo).as_posix()} imports {name}")
    assert offenders == [], "\n".join(offenders)


def test_modules_do_not_import_a_concrete_adapter(repo: Path):
    """AC-AI-01.3 - "no `modules/*` import of `ai.gemini` or any other concrete
    adapter". Enforced by the `no-concrete-ai` import contract too; asserted
    here so it holds before `FOUND-04` wires import-linter in."""
    modules = repo / "apps" / "api" / "app" / "modules"
    if not modules.is_dir():
        return  # no modules yet; the contract lands with them
    concrete = {"app.ai.gemini", "app.ai.openai", "app.ai.anthropic", "app.ai.ollama"}
    offenders = [
        f"{path.relative_to(repo).as_posix()} imports {name}"
        for path in sorted(modules.rglob("*.py"))
        for name in _imports(path)
        if name in concrete
    ]
    assert offenders == [], "\n".join(offenders)
