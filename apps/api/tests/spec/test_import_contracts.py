"""T-FOUND-05.3 / T-FOUND-05.5 - the import contracts are active and passing.

`AC-FOUND-04.1`: "`lint-imports` exits 0 with all seven cross-cutting contracts
active, one `module-independence-<name>` contract per module, and
**zero** `ignore_imports` entries. An exemption requires a new ADR."

`AC-FOUND-05.3`/`.5` name `no-http-in-domain` and `pure-logic` specifically:
a service never imports `fastapi`, and each pure-logic file has no imports from
`infra`, `models` or `repository`.

This is HR-12's enforcement point - "enforced by `import-linter` in CI, not by
review".
"""

from __future__ import annotations

import configparser
import shutil
import subprocess
import sys
from pathlib import Path

CONFIG = "apps/api/.importlinter"

# The eight `01-foundations.md` §4 names. Two enumerate every module and appear
# once the first module exists, so the expected set grows rather than being
# asserted complete before there is anything to bind.
ALWAYS_ACTIVE = {
    "layers",
    "no-concrete-ai",
    "ai-is-leaf",
    "connectors-are-leaf",
    "no-oauth-in-ai",
    "infra-is-dumb",
}
#: `no-http-in-domain` enumerates every module inside one contract and appears
#: as soon as the first module exists.
PER_MODULE = {"no-http-in-domain"}

#: ADR-014: one `module-independence-<name>` contract per module, in place of a
#: single `independence` contract over the nine packages. `independence` forbids
#: every import between the listed modules at any depth, including the one §5
#: calls "allowed and preferred" - "a read through another module's public
#: service method". There is no mode of it that permits a package root and
#: forbids its internals, so the contract said something the specification did
#: not.
INDEPENDENCE_PREFIX = "module-independence-"

CROSS_CUTTING = ALWAYS_ACTIVE | PER_MODULE


def lint_imports_command() -> list[str]:
    """The `lint-imports` entry point, resolved inside whatever venv is running.

    `python -m importlinter.cli` is a Click *group* and exits 0 without doing
    anything, which would make every fixture below pass for the wrong reason.
    The console script is the only invocation that runs the check.
    """
    script = shutil.which("lint-imports")
    if script:
        return [script]
    candidate = Path(sys.executable).parent / "lint-imports"
    return [str(candidate)]


def config(repo: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(repo / CONFIG, encoding="utf-8")
    return parser


def contract_names(repo: Path) -> set[str]:
    return {
        section.split(":", 2)[2]
        for section in config(repo).sections()
        if section.startswith("importlinter:contract:")
    }


def modules_present(repo: Path) -> list[str]:
    sys.path.insert(0, str(repo / "infra" / "scripts"))
    import gen_importlinter

    return gen_importlinter.modules()


def test_the_contract_file_exists(repo: Path):
    assert (repo / CONFIG).is_file(), "01-foundations.md §4 requires a .importlinter"


def test_no_ignore_imports_entry(repo: Path):
    """AC-FOUND-04.1 - "**zero** `ignore_imports` entries"."""
    offenders = [
        line
        for line in (repo / CONFIG).read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("ignore_imports")
    ]
    assert offenders == [], (
        f"an exemption requires a new ADR (AC-FOUND-04.1); it may not be added quietly: {offenders}"
    )


def test_the_active_contracts_are_the_ones_the_spec_names(repo: Path):
    """`AC-FOUND-04.1` as ADR-014 amended it: seven cross-cutting contracts,
    plus one per module."""
    active = contract_names(repo)
    per_module = {name for name in active if name.startswith(INDEPENDENCE_PREFIX)}
    named = active - per_module

    assert named >= ALWAYS_ACTIVE, f"missing: {sorted(ALWAYS_ACTIVE - named)}"
    assert named <= CROSS_CUTTING, f"unexpected contract: {sorted(named - CROSS_CUTTING)}"

    if modules_present(repo):
        assert named == CROSS_CUTTING, (
            f"modules exist, so all seven cross-cutting contracts must be active; "
            f"missing {sorted(CROSS_CUTTING - named)}. Run gen_importlinter.py --write."
        )


def test_every_module_has_its_own_independence_contract(repo: Path):
    """ADR-014.

    One per module, and none missing - a module with no contract is a module
    that may reach into every other module's repository, and nothing would say
    so. Compared against the module list rather than a count, because the
    number changes and the correspondence does not.
    """
    from app.documents import OWNERS

    modules = {
        name
        for name in OWNERS
        if (repo / "apps" / "api" / "app" / "modules" / name / "__init__.py").is_file()
    }
    contracts = {
        name.removeprefix(INDEPENDENCE_PREFIX)
        for name in contract_names(repo)
        if name.startswith(INDEPENDENCE_PREFIX)
    }

    assert contracts == modules, (
        f"module(s) without an independence contract: {sorted(modules - contracts)}; "
        f"contract(s) for no module: {sorted(contracts - modules)}"
    )


def test_the_contract_file_is_current(repo: Path):
    """A module added without regenerating leaves it uncovered, so the committed
    file must equal what the generator produces."""
    sys.path.insert(0, str(repo / "infra" / "scripts"))
    import gen_importlinter

    assert (repo / CONFIG).read_text(encoding="utf-8") == gen_importlinter.render(), (
        ".importlinter is stale; run `py infra/scripts/gen_importlinter.py --write`"
    )


def test_every_service_is_covered_by_no_http_in_domain(repo: Path):
    """AC-FOUND-05.3 - "No `service.py` in any module imports `fastapi`,
    `starlette`, `motor`, or `pymongo`"."""
    present = modules_present(repo)
    parser = config(repo)
    section = "importlinter:contract:no-http-in-domain"

    # The contract appears with the first module, which arrives with `AUTH-01`
    # in P1. Asserting its absence rather than skipping: `AC-FOUND-15.7` forbids
    # a skipped test on an R1 path, and a skip would hide this the day a module
    # lands without the contract being regenerated.
    if not present:
        assert section not in parser.sections()
        return

    listed = {
        line.strip()
        for line in parser["importlinter:contract:no-http-in-domain"]["source_modules"].split("\n")
        if line.strip()
    }
    assert listed == {f"app.modules.{name}.service" for name in present}


def test_lint_imports_passes(repo: Path):
    """AC-FOUND-04.1 - the contracts hold against the code as it stands.

    Shared with `T-FOUND-04.1`, the `import-linter` step in `api-ci`.
    """
    result = subprocess.run(
        [*lint_imports_command(), "--config", ".importlinter"],
        cwd=repo / "apps" / "api",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, "lint-imports failed:\n" + result.stdout + result.stderr


def test_no_google_credential_import_in_ai(repo: Path):
    """AC-AI-05.3 / HR-6 - the half import-linter cannot express.

    Subpackages of external packages are not valid contract targets, and
    forbidding `google` wholesale would also forbid `google.genai`, which
    `ai/gemini.py` legitimately needs. So the credential submodules are checked
    by AST here: `ai/*` may reach Gemini's inference SDK and nothing else Google.
    """
    import ast

    forbidden = {"google.auth", "google.oauth2", "googleapiclient", "authlib"}
    base = repo / "apps" / "api" / "app" / "ai"
    offenders: list[str] = []
    for path in sorted(base.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            line = 0
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
                line = node.lineno
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
                line = node.lineno
            for name in names:
                if any(name == f or name.startswith(f + ".") for f in forbidden):
                    offenders.append(f"{path.relative_to(repo).as_posix()}:{line}: {name}")
    assert offenders == [], (
        "a user OAuth credential must never be reachable from the AI path (HR-6):\n"
        + "\n".join(offenders)
    )


def test_the_forbidden_set_stops_short_of_the_inference_sdk():
    """The counter-case. Forbidding `google` wholesale would also forbid
    `google.genai`, which `ai/gemini.py` needs for `AI-05`, so the rule has to
    name the credential packages rather than the vendor."""
    forbidden = {"google.auth", "google.oauth2", "googleapiclient", "authlib"}
    assert "google" not in forbidden
    assert "google.genai" not in forbidden
    assert not any("google.genai".startswith(f + ".") for f in forbidden)
