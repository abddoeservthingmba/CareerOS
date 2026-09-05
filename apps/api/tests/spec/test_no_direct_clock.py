"""T-FOUND-03.1 - nothing reads the clock except `core/clock.py`.

`AC-FOUND-03.1`: "A repo-wide search finds no call to `datetime.now`,
`datetime.utcnow`, `time.time`, or `date.today` outside `core/clock.py`."

This is what makes `clock.freeze()` sufficient for every time-dependent test in
the product. One module reading the wall clock directly is enough to make a
frozen-clock test pass locally and fail at midnight.
"""

from __future__ import annotations

import re
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
            text = path.read_text(encoding="utf-8")
            for number, line in enumerate(text.split("\n"), start=1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                for pattern in FORBIDDEN:
                    if pattern.search(line):
                        offenders.append(f"{relative}:{number}: {stripped}")
    assert offenders == [], "call core.clock.now() instead:\n" + "\n".join(offenders)


def test_the_allowance_is_narrow(repo: Path):
    """The exemption must name one module, not a directory of product code."""
    assert ALLOWED[0] == "apps/api/app/core/clock.py"
    assert (repo / ALLOWED[0]).is_file()
