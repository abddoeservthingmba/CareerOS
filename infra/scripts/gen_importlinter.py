#!/usr/bin/env python
"""Generate `apps/api/.importlinter` - `FOUND-04`.

`01-foundations.md` §4 names eight contracts. Two of them - `module-independence`
and `no-http-in-domain` - enumerate every module by name, so a hand-maintained
file silently stops covering a module the day someone adds one and forgets.

import-linter also refuses to start when a contract names something that does
not exist, so a contract may only bind what has been built.

Both problems have the same answer: generate the file from the tree.
`tests/spec/test_import_contracts.py` asserts the committed file matches what
the generator produces, so a new module fails the build until the contracts are
regenerated with it, and asserts that the full set of eight is reached once
there is a module to bind - so a permanently short list cannot look correct.

    py infra/scripts/gen_importlinter.py --write
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps" / "api" / "app"
MODULES_DIR = APP / "modules"
TARGET = ROOT / "apps" / "api" / ".importlinter"

HEADER = """; Module boundaries, by machine - `FOUND-04`, HR-12.
;
; Generated. Do not edit; run `py infra/scripts/gen_importlinter.py --write`.
;
; `01-foundations.md` §4: "Make the modular monolith actually modular, by
; machine, so that any module could be extracted into a service later without
; archaeology."
;
; `AC-FOUND-04.1`: "`lint-imports` exits 0 with all eight contracts active and
; **zero** `ignore_imports` entries. An exemption requires a new ADR." There are
; no `ignore_imports` entries here and the test asserts there are none, so
; adding one is a visible act rather than a quiet line.

[importlinter]
root_packages =
    app
include_external_packages = True
"""

# innermost last: shared <- core <- infra(interfaces) <- {ai, connectors} <- modules <- main
LAYERS = (
    "app.main",
    "app.modules",
    "app.connectors | app.ai | app.infra",
    "app.core",
    "app.shared",
)

CONCRETE_ADAPTERS = (
    "app.ai.gemini",
    "app.ai.openai",
    "app.ai.anthropic",
    "app.ai.ollama",
    "app.ai.stubs",
)

REST = """
; --- 4. ai-is-leaf ---------------------------------------------------------
[importlinter:contract:ai-is-leaf]
name = ai-is-leaf
type = forbidden
source_modules =
    app.ai
forbidden_modules =
    app.modules
    app.connectors

; --- 5. connectors-are-leaf ------------------------------------------------
; "A connector normalizes; enrichment is the ingestion service's job."
[importlinter:contract:connectors-are-leaf]
name = connectors-are-leaf
type = forbidden
source_modules =
    app.connectors
forbidden_modules =
    app.modules
    app.ai

; --- 6. no-oauth-in-ai -----------------------------------------------------
; HR-6. Sign-in and inference share the word "Google" and nothing else. A change
; reaching for an available Google credential in the AI path would attach a
; user's identity to inference calls.
;
; import-linter cannot forbid a subpackage of an external package, so
; `google.auth` and `google.oauth2` cannot be named here - and forbidding
; `google` wholesale would also forbid `google.genai`, which `ai/gemini.py`
; legitimately needs. Those two are asserted by AST in
; `tests/spec/test_import_contracts.py::test_no_google_credential_import_in_ai`,
; which is what `AC-AI-05.3` actually requires. `app.modules.auth` needs no
; entry: `ai-is-leaf` already forbids `app.ai -> app.modules` entirely.
[importlinter:contract:no-oauth-in-ai]
name = no-oauth-in-ai
type = forbidden
source_modules =
    app.ai
forbidden_modules =
    authlib
    googleapiclient

; --- 7. infra-is-dumb ------------------------------------------------------
[importlinter:contract:infra-is-dumb]
name = infra-is-dumb
type = forbidden
source_modules =
    app.infra
forbidden_modules =
    app.modules
    app.ai
    app.connectors
"""

PENDING_NOTE = """
; --- 2. module-independence, 8. no-http-in-domain --------------------------
; Both enumerate every module by name and appear here as soon as the first
; module exists. `app/modules/` is empty today, so there is nothing to bind;
; `AC-FOUND-04.1`'s "all eight contracts" is reached when `auth` lands in P1.
"""


def exists(dotted: str) -> bool:
    """Whether `app.x.y` is a real module or package on disk."""
    relative = dotted.removeprefix("app.").replace(".", "/")
    base = APP / relative
    return (base / "__init__.py").is_file() or base.with_suffix(".py").is_file()


def modules() -> list[str]:
    if not MODULES_DIR.is_dir():
        return []
    return sorted(
        path.name
        for path in MODULES_DIR.iterdir()
        if path.is_dir()
        and (path / "__init__.py").is_file()
        and not path.name.startswith("_")
    )


def _block(title: str, comment: str, lines: list[str]) -> str:
    rule = "-" * max(3, 74 - len(title))
    out = [f"\n; --- {title} {rule}"]
    if comment:
        out.append(comment)
    out.extend(lines)
    return "\n".join(out) + "\n"


def _layers() -> str:
    present = [
        layer
        for layer in LAYERS
        if all(exists(part.strip()) for part in layer.split("|"))
    ]
    return _block(
        "1. layers",
        "; shared <- core <- infra <- {ai, connectors} <- modules <- main",
        [
            "[importlinter:contract:layers]",
            "name = layers",
            "type = layers",
            "layers =",
            *(f"    {layer}" for layer in present),
            "exhaustive = False",
        ],
    )


def _no_concrete_ai() -> str:
    present = [name for name in CONCRETE_ADAPTERS if exists(name)]
    return _block(
        "3. no-concrete-ai",
        "; HR-5: a feature module names a capability, never a provider.",
        [
            "[importlinter:contract:no-concrete-ai]",
            "name = no-concrete-ai",
            "type = forbidden",
            "source_modules =",
            "    app.modules",
            "    app.connectors",
            "forbidden_modules =",
            *(f"    {name}" for name in present),
        ],
    )


def _module_independence(found: list[str]) -> str:
    return _block(
        "2. module-independence",
        "; Only another module's `__init__.py` public surface may be imported.",
        [
            "[importlinter:contract:module-independence]",
            "name = module-independence",
            "type = independence",
            "modules =",
            *(f"    app.modules.{name}" for name in found),
        ],
    )


def _no_http_in_domain(found: list[str]) -> str:
    return _block(
        "8. no-http-in-domain",
        "; Services take and return plain objects; HTTP lives in `router.py`.",
        [
            "[importlinter:contract:no-http-in-domain]",
            "name = no-http-in-domain",
            "type = forbidden",
            "source_modules =",
            *(f"    app.modules.{name}.service" for name in found),
            "forbidden_modules =",
            "    fastapi",
            "    starlette",
            "    motor",
            "    pymongo",
        ],
    )


def render() -> str:
    found = modules()
    out = [HEADER, _layers(), _no_concrete_ai(), REST]
    if not found:
        out.append(PENDING_NOTE)
    else:
        out.append(_module_independence(found))
        out.append(_no_http_in_domain(found))
    return "".join(out)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    rendered = render()
    if args.write:
        TARGET.write_text(rendered, encoding="utf-8", newline="")
        print(f"wrote {TARGET} ({len(modules())} module(s) enumerated)")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
