"""T-FOUND-02.4 - the product name is configuration, not a literal.

`AC-FOUND-02.4`: "No user-visible string literal equals the product name
anywhere in `apps/`; all such strings interpolate `PRODUCT_NAME`."

`README.md` §5: "'JobPilot' is still a placeholder (v1.0 D1). Nothing in the
code may hard-code it as a user-visible string ... Package names, the Mongo
database name, and the JWT issuer may use `jobpilot` as an internal identifier."

So the check is deliberately case-sensitive on the *display* spelling. The
lowercase `jobpilot` is an internal identifier and is allowed; `JobPilot` in a
user-visible string is what D1 would have to chase down at rename time.
"""

from __future__ import annotations

from pathlib import Path

PRODUCT_NAME = "JobPilot"

SEARCH_ROOTS = ("apps/api/app", "apps/web/src", "apps/mobile/lib")
SUFFIXES = (".py", ".ts", ".tsx", ".dart")

# Where the display spelling may legitimately appear.
ALLOWED_FILES = (
    # The example environment is where the placeholder is *set*.
    ".env.example",
)


def test_no_user_visible_product_name_literal(repo: Path):
    offenders: list[str] = []
    for root in SEARCH_ROOTS:
        base = repo / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix not in SUFFIXES or not path.is_file():
                continue
            relative = path.relative_to(repo).as_posix()
            if relative.endswith(ALLOWED_FILES):
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
                if PRODUCT_NAME not in line:
                    continue
                stripped = line.strip()
                # A comment or docstring citing the specification is not a
                # user-visible string.
                if stripped.startswith(("#", "//", "*", '"""', "'''")):
                    continue
                offenders.append(f"{relative}:{number}: {stripped}")
    assert offenders == [], "interpolate settings.PRODUCT_NAME instead (README §5):\n" + "\n".join(
        offenders
    )


def test_the_internal_identifier_is_still_permitted(repo: Path):
    """The rule is about the display spelling, not the package name."""
    example = (repo / ".env.example").read_text(encoding="utf-8")
    assert "MONGODB_DB=jobpilot" in example, (
        "the lowercase internal identifier is allowed and is what the database name uses"
    )


def test_product_name_is_a_required_setting():
    """The mechanism the criterion depends on: there is no default to fall back
    to, so a missing name fails the boot rather than shipping a placeholder."""
    from app.core.config import Settings

    assert Settings.model_fields["PRODUCT_NAME"].is_required()
