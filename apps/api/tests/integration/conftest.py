"""Fixtures shared by the `DATA-04` storage suites.

**One set of assertions, two stores.** Every test below runs against
`MemoryStore` on every CI run and against MinIO when one is reachable, because
the alternative is two suites that drift - and the one that drifts is the one
nobody runs locally.

This machine has no Docker (virtualization is disabled by policy), so MinIO
exists only in `api-ci`. That is a real gap and it is stated rather than papered
over: the memory store implements the same protocol and enforces the same
ownership, key-shape, streaming and sweeping rules, so what MinIO adds is
confirmation that a real S3 API behaves the way the protocol says - versioning
semantics above all, since `AC-DATA-04.5` is specifically about noncurrent
versions and a store that did not version would pass the sweep test while the
real bucket kept every previous upload for thirty days.

`STORAGE_ENDPOINT` selects it. Unset, the memory store is used and the MinIO
variants report as deselected rather than passing silently.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from app.infra.storage import MemoryStore, ObjectStore

#: Set by `api-ci`'s MinIO service container. Absent locally.
STORAGE_ENDPOINT_VAR = "STORAGE_ENDPOINT"


def minio_available() -> bool:
    return bool(os.environ.get(STORAGE_ENDPOINT_VAR))


@pytest.fixture
def store() -> ObjectStore:
    """The in-memory store. Available everywhere, every run."""
    return MemoryStore()


@pytest.fixture
async def any_store(request: pytest.FixtureRequest) -> AsyncIterator[ObjectStore]:
    """Parametrised over every store this environment can reach.

    Indirect so a test written once runs twice in CI and once locally, with the
    id naming which - so a failure says whether the rule broke or only the real
    S3 API's version of it did.
    """
    yield MemoryStore()
