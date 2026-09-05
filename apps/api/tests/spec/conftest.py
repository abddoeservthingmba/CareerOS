"""Fixtures for the specification gates.

The gates read `docs/spec/` and the repository tree; they import no product
code, so they run from the first commit onward with no application environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "infra" / "scripts"))

from specgate import manifest as manifest_mod  # noqa: E402
from specgate import parser as parser_mod  # noqa: E402


@pytest.fixture(scope="session")
def repo() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def spec() -> parser_mod.Spec:
    return parser_mod.parse_spec()


@pytest.fixture(scope="session")
def manifest() -> manifest_mod.Manifest:
    return manifest_mod.manifest()
