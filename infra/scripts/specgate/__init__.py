"""Specification gates and generators.

One package so that the traceability gate (`FOUND-06`), the status registry
(`FOUND-15`) and the dependency-closure checks (`DEP-01`...`DEP-06`) share a
single parse of `docs/spec/`. Three readers of the same files that disagree
about what those files say is the failure this package exists to prevent.

Nothing here imports product code; nothing in product code imports this.
"""

from __future__ import annotations

__all__ = ["repo_root", "spec_dir"]

from pathlib import Path


def repo_root(start: Path | None = None) -> Path:
    """Walk up from `start` until the directory holding `docs/spec/` is found."""
    here = (start or Path(__file__)).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "docs" / "spec" / "README.md").is_file():
            return candidate
    raise RuntimeError(
        f"repository root (containing docs/spec/) not found above {here}"
    )


def spec_dir(start: Path | None = None) -> Path:
    return repo_root(start) / "docs" / "spec"
