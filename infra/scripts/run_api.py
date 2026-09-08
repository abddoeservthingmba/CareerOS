#!/usr/bin/env python
"""Run the API locally without Docker.

`make up` boots the whole stack in Compose, which this machine cannot do -
virtualization is disabled, so Docker Desktop will not start. This runs the same
app factory directly against the services that are reachable: MongoDB from
`MONGODB_URI` in `.env`.

    py infra/scripts/run_api.py            # http://localhost:8000
    py infra/scripts/run_api.py --port 8080

The `api` entrypoint in the image (`OPS-01`, ADR-002) runs the same
`app.main:create_app`, so this is the same process the container starts, minus
the container.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "apps" / "api"


def load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.is_file():
        raise SystemExit(f"{env_file} is missing. Copy .env.example to .env and fill it in.")
    for line in env_file.read_text(encoding="utf-8").split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    load_env()
    sys.path.insert(0, str(API))

    import uvicorn

    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=os.environ.get("LOG_LEVEL", "INFO").lower(),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
