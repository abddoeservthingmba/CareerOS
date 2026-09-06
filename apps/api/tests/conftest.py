"""Fixtures shared by every suite.

The spec gates read `docs/spec/` and the repository tree, and several unit tests
assert a code artifact against the specification that requires it, so `repo` and
the parsed specification live here rather than under `tests/spec/`.

Integration tests use a **real** MongoDB. There is no in-memory substitute that
shares Mongo's index, TTL and partial-filter behaviour, and those are exactly
what `DATA-03` and `DATA-05` assert. The connection comes from `MONGODB_URI`:
the repository's `.env` locally, a service container in CI. Each test gets its
own database, dropped afterwards, so a run never sees another run's rows.

Nothing here skips. `AC-FOUND-15.7` forbids a skipped test on an R1 path, so a
missing `MONGODB_URI` fails loudly with an instruction rather than turning the
integration suite into a quiet no-op.
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "infra" / "scripts"))

from specgate import manifest as manifest_mod  # noqa: E402
from specgate import parser as parser_mod  # noqa: E402


def _load_dotenv() -> None:
    """Populate the environment from the repository's `.env`, if present.

    CI sets the variables directly; locally they live in `.env`, which is
    gitignored (`CLAUDE.md`: "Secrets never enter the repo").
    """
    env_file = REPO_ROOT / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


@pytest.fixture(scope="session")
def repo() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def spec() -> parser_mod.Spec:
    return parser_mod.parse_spec()


@pytest.fixture(scope="session")
def manifest() -> manifest_mod.Manifest:
    return manifest_mod.manifest()


@pytest.fixture(scope="session")
def mongodb_uri() -> str:
    uri = os.environ.get("MONGODB_URI", "").strip()
    if not uri:
        raise RuntimeError(
            "MONGODB_URI is not set. The integration suite uses a real MongoDB, "
            "because Mongo's index, TTL and partial-filter behaviour is what "
            "DATA-03 and DATA-05 assert and no in-memory substitute shares it. "
            "Set it in .env locally, or as a service container in CI."
        )
    return uri


# Atlas caps a database name at 38 bytes and a free cluster at a small number of
# databases, so the suite uses one and clears its collections between tests
# rather than minting a database per test.
TEST_DATABASE = "jobpilot_test"


@pytest.fixture
async def database(mongodb_uri: str) -> AsyncIterator[Any]:
    """The test database, emptied before and after each test."""
    from pymongo import AsyncMongoClient

    # Beanie 2.x uses PyMongo's native async driver; Motor is deprecated and
    # `init_beanie` will not accept a Motor database.
    # `tz_aware=True` is not optional. BSON stores a datetime as UTC
    # milliseconds with no zone, so without it every timestamp read back is
    # naive and HR-10's "every stored datetime is timezone-aware UTC" fails on
    # the way *out* rather than on the way in. The production client sets it for
    # the same reason.
    client: AsyncMongoClient[Any] = AsyncMongoClient(
        mongodb_uri,
        serverSelectionTimeoutMS=20000,
        uuidRepresentation="standard",
        tz_aware=True,
    )
    db = client[TEST_DATABASE]

    async def clear() -> None:
        for name in await db.list_collection_names():
            await db.drop_collection(name)

    await clear()
    try:
        yield db
    finally:
        await clear()
        await client.close()
