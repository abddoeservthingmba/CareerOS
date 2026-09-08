"""T-AI-07.6 - no fixture contains a real phone number or email address.

`AC-AI-07.6`: "No golden fixture contains a real phone number or email address
(scrub check)."

§7 states the obligation the fixtures carry: résumés used as fixtures "are the
developer's own or explicitly licensed, are scrubbed of contact details, and are
documented as such". This is the mechanical half of that.

**Why this is a gate and not a code review item.** A golden fixture is a real
document. Someone's real document. It goes into git, and git is forever - a
committed phone number is not removed by deleting the line, it is removed by
rewriting history across every clone. And the moment a fixture is
attractive-looking test data it gets copied: into a bug report, into a
screenshot, into a CI log that a third party stores. The only reliable time to
catch it is before the commit that adds it.

**Allowlisted by reserved namespace, not by looking harmless.** `@example.com`
and `555-01xx` are reserved by RFC 2606 and the NANP for exactly this purpose;
they cannot ring anyone or reach anyone. `@gmail.com` is not, however plausible
the local part looks, and neither is a number that happens to be a friend's.
So the rule is "in a reserved range", never "does not look real" - which is a
judgement, and judgements are what let one through.

The scan covers every fixture directory, not only `tests/ai/golden/`. The
criterion names golden fixtures because those are the résumés, but an email
recorded into a connector fixture or an email-template snapshot is the same
disclosure, and a check that stopped at one directory would be a check someone
routes around by choosing a different directory.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

#: Everything committed as test data. Extended as directories arrive rather
#: than enumerated once, because a new fixture root is exactly where an
#: unscrubbed document lands.
FIXTURE_ROOTS = (
    "apps/api/tests/ai/golden",
    "apps/api/tests/fixtures",
    "apps/api/tests/data",
    "packages/fixtures",
)

#: Text-ish files. A PDF or an image is not scanned - and that is stated in
#: `test_no_fixture_is_an_unscannable_binary` rather than left implicit, because
#: "the scan passed" would otherwise mean "the scan skipped it".
SCANNED_SUFFIXES = frozenset({".json", ".txt", ".md", ".yaml", ".yml", ".csv", ".html", ".jsonl"})

#: RFC 2606 and RFC 6761. Reserved forever, resolvable by nobody.
RESERVED_DOMAINS = (
    "example.com",
    "example.net",
    "example.org",
    "example.edu",
    "localhost",
    ".test",
    ".example",
    ".invalid",
    ".localhost",
)

EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

#: A run of digits and phone separators, filtered afterwards by digit count.
#:
#: Deliberately not a per-country format. Grouping varies by country and by
#: whoever typed it - `+44 7912 345678`, `+91 98765 43210` and
#: `(020) 7123 4567` group differently, and a pattern written around one of
#: them silently passes the others. A résumé arrives from anywhere.
PHONE = re.compile(r"(?<![\w.])\+?\d[\d\s.()\-]{7,17}\d(?![\w.])")

#: Reserved for fiction. NANP 555-0100..555-0199, and Ofcom's drama ranges.
RESERVED_PHONE_PATTERNS = (
    re.compile(r"555[\s.\-]?01\d{2}"),
    re.compile(r"\+?1?[\s.\-]?\(?\d{3}\)?[\s.\-]?555[\s.\-]?01\d{2}"),
    re.compile(r"\+?44[\s.\-]?7700[\s.\-]?900\d{3}"),
    re.compile(r"07700[\s.\-]?900\d{3}"),
    re.compile(r"\+?44[\s.\-]?20[\s.\-]?7946[\s.\-]?0\d{3}"),
    re.compile(r"01632[\s.\-]?960\d{3}"),
)

#: Digit runs that are shaped like a phone number and are not one. Kept short
#: and specific: a long allowlist here is how a real number eventually passes.
NOT_A_PHONE = (
    re.compile(r"^\d{4}-\d{2}-\d{2}"),  # an ISO date, with or without a time
    re.compile(r"^\d{2}:\d{2}"),  # a time
    re.compile(r"^\d+\.\d+$"),  # a decimal
)


def scanned_files(repo: Path) -> list[Path]:
    found: list[Path] = []
    for root in FIXTURE_ROOTS:
        base = repo / root
        if not base.is_dir():
            continue
        found += [
            path
            for path in sorted(base.rglob("*"))
            if path.is_file() and path.suffix.casefold() in SCANNED_SUFFIXES
        ]
    return found


def is_reserved_email(address: str) -> bool:
    _, _, domain = address.rpartition("@")
    domain = domain.casefold().rstrip(".")
    return any(
        domain == reserved or domain.endswith(reserved) for reserved in RESERVED_DOMAINS if reserved
    )


def is_reserved_phone(candidate: str) -> bool:
    return any(pattern.search(candidate) for pattern in RESERVED_PHONE_PATTERNS)


def looks_like_a_phone(candidate: str) -> bool:
    if any(pattern.match(candidate.strip()) for pattern in NOT_A_PHONE):
        return False
    digits = re.sub(r"\D", "", candidate)
    return 9 <= len(digits) <= 15


def offenders(text: str, path: str) -> list[str]:
    found: list[str] = []
    for number, line in enumerate(text.split("\n"), start=1):
        for address in EMAIL.findall(line):
            if not is_reserved_email(address):
                found.append(
                    f"{path}:{number}: email {address!r} is not at a reserved domain "
                    f"({', '.join(RESERVED_DOMAINS[:4])}, ...)"
                )
        for candidate in PHONE.findall(line):
            if looks_like_a_phone(candidate) and not is_reserved_phone(candidate):
                found.append(
                    f"{path}:{number}: {candidate!r} is phone-shaped and not in a "
                    "reserved range (555-01xx, +44 7700 900xxx)"
                )
    return found


# -- the criterion ------------------------------------------------------------


def test_no_fixture_contains_an_unscrubbed_contact_detail(repo: Path):
    """AC-AI-07.6.

    The whole scan in one assertion, reporting every hit rather than the first.
    Whoever reads this failure has one document to fix and wants the full list.
    """
    found: list[str] = []
    for path in scanned_files(repo):
        found += offenders(
            path.read_text(encoding="utf-8", errors="replace"), path.relative_to(repo).as_posix()
        )

    assert found == [], (
        "a committed fixture contains what looks like a real contact detail. "
        "git is forever: removing the line does not remove it from history. "
        "Replace it with a reserved value (RFC 2606 `@example.com`, NANP "
        "`555-0100`, Ofcom `+44 7700 900123`):\n  " + "\n  ".join(found)
    )


def test_the_golden_root_is_scanned(repo: Path):
    """`AC-AI-07.6` names golden fixtures specifically, so the directory that
    holds them must be in the scan whether or not it exists yet."""
    assert "apps/api/tests/ai/golden" in FIXTURE_ROOTS


def test_every_fixture_directory_is_covered(repo: Path):
    """The scan is only as good as its roots.

    A `fixtures/` or `golden/` directory outside `FIXTURE_ROOTS` is data nobody
    is checking, and adding one is easy to do without noticing this file
    exists. So the roots are discovered and compared rather than trusted.
    """
    discovered = {
        path.relative_to(repo).as_posix()
        for pattern in ("fixtures", "golden")
        for path in repo.rglob(pattern)
        if path.is_dir()
        and ".venv" not in path.parts
        and "node_modules" not in path.parts
        and "__pycache__" not in path.parts
    }
    uncovered = sorted(
        directory
        for directory in discovered
        if not any(
            directory.startswith(root) or root.startswith(directory) for root in FIXTURE_ROOTS
        )
    )

    assert uncovered == [], (
        f"fixture directory {uncovered} is not in FIXTURE_ROOTS, so nothing checks "
        "it for contact details. Add it."
    )


# -- the detector has to actually detect --------------------------------------
# A scrub check that passes over everything is the worst possible outcome here:
# it reports a clean repository while a real number sits in it. So the detector
# is exercised on values with known answers, both directions.


@pytest.mark.parametrize(
    "address",
    [
        "alex.morgan@gmail.com",
        "a.morgan@acme-consulting.co.uk",
        "recruiter@company.io",
        "j.smith@university.edu.au",
    ],
)
def test_a_real_looking_email_is_caught(address: str):
    """Each of these is the shape that arrives on a résumé."""
    assert offenders(f"Contact: {address}", "f.txt")


@pytest.mark.parametrize(
    "address",
    [
        "alex@example.com",
        "candidate@example.org",
        "no-reply@localhost",
        "someone@fixtures.test",
        "user@my.invalid",
    ],
)
def test_a_reserved_email_is_allowed(address: str):
    """RFC 2606 and 6761 exist for this. A check that flagged them would make
    writing a legitimate fixture impossible, which is how a check gets
    disabled."""
    assert offenders(f"Contact: {address}", "f.txt") == []


@pytest.mark.parametrize(
    "number",
    [
        "+44 7912 345678",
        "(020) 7123 4567",
        "+1 415 926 3300",
        "0161 496 0123",
        "+91 98765 43210",
    ],
)
def test_a_real_looking_phone_number_is_caught(number: str):
    assert offenders(f"Tel: {number}", "f.txt")


@pytest.mark.parametrize(
    "number",
    ["555-0123", "(415) 555-0187", "+44 7700 900123", "+44 20 7946 0958", "01632 960123"],
)
def test_a_reserved_phone_number_is_allowed(number: str):
    """The ranges broadcasters and standards bodies set aside for fiction. They
    cannot ring anyone, which is the only property that matters."""
    assert offenders(f"Tel: {number}", "f.txt") == []


@pytest.mark.parametrize(
    "text",
    [
        '"created_at": "2026-09-08T14:32:00Z"',
        '"_id": "01JBQ8Z3F7KX2M4N6P8R0S2T4V"',
        '"salary_min_minor": 4500000',
        '"score": 0.9231',
        '"version": 1',
        '"duration_ms": 1204',
    ],
)
def test_ordinary_fixture_data_is_not_mistaken_for_a_phone_number(text: str):
    """False positives matter as much as false negatives here.

    A scrub check that flags every ULID and timestamp gets an allowlist, then a
    broader allowlist, then gets deleted - and a real number passes through the
    hole that was left.
    """
    assert offenders(text, "f.txt") == []


def test_no_fixture_is_an_unscannable_binary(repo: Path):
    """A PDF résumé is not scannable by this check, so it must not be committed
    as a fixture at all.

    Stated as its own assertion because "the scan passed" would otherwise be
    indistinguishable from "the scan could not read it" - and a PDF is the most
    likely form for a real résumé to arrive in.
    """
    unscannable = [
        path.relative_to(repo).as_posix()
        for root in FIXTURE_ROOTS
        if (repo / root).is_dir()
        for path in sorted((repo / root).rglob("*"))
        if path.is_file() and path.suffix.casefold() not in SCANNED_SUFFIXES
    ]

    assert unscannable == [], (
        f"{unscannable} cannot be scanned for contact details. Commit résumé "
        "fixtures as extracted text, not as the original document: HR-8 keeps "
        "file bytes out of the AI path, and this check keeps them out of git."
    )
