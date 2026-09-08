#!/usr/bin/env python
"""Export the OpenAPI document - `FOUND-13`.

`01-foundations.md` §13: "The OpenAPI document is exported by CI and committed
to `packages/contracts/openapi.json`."

Committed, not generated on demand, because it is the artifact the two clients
are generated from and the thing an API diff is taken against. A document that
existed only at build time could not be compared with the previous one, and
`AC-FOUND-13.4`'s "a removed field fails CI" has nothing to subtract from.

Written by CI and nobody else (`AC-FOUND-01.5`), which is what makes the diff
trustworthy: a hand-edited `openapi.json` would let a breaking change be
declared additive by editing the evidence.

**Deterministic.** Sorted keys, two-space indent, trailing newline. FastAPI
builds the document from dictionaries whose order follows route registration, so
without sorting a harmless reordering of `include_router` calls produces a
diff that looks like an API change - and after the third false alarm nobody
reads the diff at all.

    py infra/scripts/export_openapi.py --write
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "packages" / "contracts" / "openapi.json"

#: `AC-FOUND-13.5`: "No route outside `/api/v1` appears in either generated
#: client." `/healthz`, `/readyz` and `/metrics` are for a load balancer and a
#: scrape job, which are not API consumers; the bounce webhook is a provider
#: calling us. All of them are `include_in_schema=False`, and this is the second
#: lock on the same door.
PUBLIC_PREFIX = "/api/v1"


def _load_env() -> None:
    """Populate the environment from `.env`, if present.

    `Settings` is fail-fast by design (`AC-FOUND-02.1`), so building the app to
    read its routes needs the same variables a running container needs. CI sets
    them directly; locally they live in the gitignored `.env`.
    """
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def document() -> dict[str, Any]:
    """The OpenAPI document the current code produces."""
    sys.path.insert(0, str(ROOT / "apps" / "api"))
    _load_env()

    from app.main import create_app

    schema: dict[str, Any] = create_app().openapi()
    return prune(schema)


def prune(schema: dict[str, Any]) -> dict[str, Any]:
    """Drop everything outside `/api/v1`.

    `include_in_schema=False` already keeps the operational routes out, so this
    normally removes nothing. It is here because "normally" is doing a lot of
    work: a route added without that flag would otherwise appear in both
    generated clients, and `AC-FOUND-13.5` would be discovered by a client
    developer rather than by CI.
    """
    paths = schema.get("paths", {})
    schema["paths"] = {
        path: operations
        for path, operations in paths.items()
        if path.startswith(PUBLIC_PREFIX)
    }
    return schema


def render(schema: dict[str, Any]) -> str:
    """Bytes that only change when the API does."""
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="write packages/contracts/openapi.json"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the committed document is stale (AC-FOUND-13.2)",
    )
    args = parser.parse_args(argv)

    rendered = render(document())

    if args.check:
        if not TARGET.is_file():
            print(f"{TARGET.relative_to(ROOT)} does not exist; run with --write")
            return 1
        committed = TARGET.read_text(encoding="utf-8")
        if committed != rendered:
            print(
                f"{TARGET.relative_to(ROOT)} is stale. The API changed and the "
                "contract was not regenerated, so both generated clients are "
                "describing a server that no longer exists.\n"
                "Run: py infra/scripts/export_openapi.py --write"
            )
            return 1
        print(f"{TARGET.relative_to(ROOT)} is current")
        return 0

    if args.write:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(rendered, encoding="utf-8", newline="")
        paths = len(json.loads(rendered).get("paths", {}))
        print(
            f"wrote {TARGET.relative_to(ROOT)} ({paths} path(s) under {PUBLIC_PREFIX})"
        )
        return 0

    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
