"""T-FOUND-12.4 / T-FOUND-12.5 - the error code registry.

`AC-FOUND-12.4`: "A grep finds no string literal used as an error code outside
`core/errors.py`."
`AC-FOUND-12.5`: "`docs/error-codes.md` matches the enum."

The first is what stops two modules inventing `not_found` with different
meanings; the second is what stops the client's copy table drifting from the
server's registry.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.errors import DESCRIPTIONS, ErrorCode, render_error_codes

REGISTRY = "apps/api/app/core/errors.py"
SEARCH_ROOT = "apps/api/app"


def test_every_code_is_snake_case():
    """§12 - "`code` is a stable snake_case string"."""
    for code in ErrorCode:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", code.value), code


def test_every_code_has_a_description():
    missing = sorted(code.value for code in ErrorCode if code not in DESCRIPTIONS)
    assert missing == [], f"codes with no description: {missing}"


def test_no_code_literal_outside_the_registry(repo: Path):
    """AC-FOUND-12.4."""
    values = {code.value for code in ErrorCode}
    offenders: list[str] = []
    base = repo / SEARCH_ROOT
    for path in sorted(base.rglob("*.py")):
        relative = path.relative_to(repo).as_posix()
        if relative == REGISTRY:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for literal in re.findall(r"""["']([a-z][a-z0-9_]*)["']""", line):
                if literal in values:
                    offenders.append(f"{relative}:{number}: {literal!r}")
    assert offenders == [], (
        "use the ErrorCode member instead of the string (AC-FOUND-12.4):\n" + "\n".join(offenders)
    )


def test_error_codes_doc_matches_the_enum(repo: Path):
    """AC-FOUND-12.5."""
    committed = repo / "docs" / "error-codes.md"
    assert committed.is_file(), "run `make error-codes` to publish docs/error-codes.md"
    assert committed.read_text(encoding="utf-8") == render_error_codes(), (
        "docs/error-codes.md is stale; regenerate with `make error-codes`"
    )


def test_the_doc_lists_every_code(repo: Path):
    text = (repo / "docs" / "error-codes.md").read_text(encoding="utf-8")
    for code in ErrorCode:
        assert f"`{code.value}`" in text, f"{code.value} is absent from docs/error-codes.md"


def test_the_registry_covers_the_codes_the_spec_names(repo: Path):
    """Every code the specification quotes must exist here.

    The specification writes them as `` `code_name` `` inside a sentence about a
    status, so they are extracted from the acceptance criteria rather than
    listed again by hand.
    """
    spec_dir = repo / "docs" / "spec"
    status = r"(?:40[0-9]|41[0-9]|42[0-9]|50[0-9])"
    patterns = (
        # "returns `403 email_not_verified`" - status and code in one span.
        re.compile(rf"`{status}\s+([a-z][a-z0-9_]{{3,}})`"),
        # "rejected 400 `invalid_cursor`" - status outside, code in its own span.
        re.compile(rf"\b{status}\s+`([a-z][a-z0-9_]{{3,}})`"),
    )
    quoted: set[str] = set()
    for path in sorted(spec_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            quoted |= set(pattern.findall(text))

    assert len(quoted) >= 15, (
        f"only {len(quoted)} codes extracted from the specification; the "
        "extraction has stopped matching and this check has gone vacuous"
    )

    known = {code.value for code in ErrorCode}
    missing = sorted(quoted - known)
    assert missing == [], (
        f"the specification names these codes but the registry lacks them: {missing}"
    )
