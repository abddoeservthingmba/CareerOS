"""T-FOUND-03.1 - nothing reads the clock except `core/clock.py`.

`AC-FOUND-03.1`: "A repo-wide search finds no call to `datetime.now`,
`datetime.utcnow`, `time.time`, or `date.today` outside `core/clock.py`."

This is what makes `clock.freeze()` sufficient for every time-dependent test in
the product. One module reading the wall clock directly is enough to make a
frozen-clock test pass locally and fail at midnight.
"""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

# The calls the criterion names.
FORBIDDEN = (
    re.compile(r"\bdatetime\.now\b"),
    re.compile(r"\bdatetime\.utcnow\b"),
    re.compile(r"\btime\.time\b"),
    re.compile(r"\bdate\.today\b"),
)

# `core/clock.py` is the one place that may. The tests may too: asserting that a
# frozen clock differs from the real one requires reading the real one.
ALLOWED = (
    "apps/api/app/core/clock.py",
    "apps/api/tests/",
)

SEARCH_ROOTS = ("apps/api/app", "infra/scripts")


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """A file's lines with string literals blanked out.

    A docstring that *names* `datetime.now` - this module's own, or
    `shared/timeutils.py` explaining why it does not call it - is prose, not a
    call. Comments stay in scope: a commented-out call is dead code, which
    `AC-FOUND-15.7` forbids anyway.
    """
    source = path.read_text(encoding="utf-8")
    lines = dict(enumerate(source.split("\n"), start=1))
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.STRING:
                for number in range(token.start[0], token.end[0] + 1):
                    lines[number] = ""
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return sorted(lines.items())


def test_no_direct_clock_access(repo: Path):
    offenders: list[str] = []
    for root in SEARCH_ROOTS:
        base = repo / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            relative = path.relative_to(repo).as_posix()
            if relative.startswith(ALLOWED):
                continue
            for number, line in _code_lines(path):
                for pattern in FORBIDDEN:
                    if pattern.search(line):
                        offenders.append(f"{relative}:{number}: {line.strip()}")
    assert offenders == [], "call core.clock.now() instead:\n" + "\n".join(offenders)


def test_the_allowance_is_narrow(repo: Path):
    """The exemption must name one module, not a directory of product code."""
    assert ALLOWED[0] == "apps/api/app/core/clock.py"
    assert (repo / ALLOWED[0]).is_file()


def test_the_search_would_catch_a_violation(tmp_path: Path):
    """A check that exempts too much passes for the wrong reason."""
    offender = tmp_path / "leak.py"
    offender.write_text(
        "from datetime import datetime\n\n\ndef stamp():\n    return datetime.now()\n",
        encoding="utf-8",
    )
    found = [line for _, line in _code_lines(offender) if any(p.search(line) for p in FORBIDDEN)]
    assert found, "the patterns no longer match a real call"


def test_a_docstring_mentioning_the_call_is_not_a_call(tmp_path: Path):
    """The counter-case for the blanking above."""
    prose = tmp_path / "prose.py"
    prose.write_text('"""Nothing here calls datetime.now()."""\n', encoding="utf-8")
    found = [line for _, line in _code_lines(prose) if any(p.search(line) for p in FORBIDDEN)]
    assert found == []
