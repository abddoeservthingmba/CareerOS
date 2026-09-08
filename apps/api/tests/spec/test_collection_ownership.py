"""T-DATA-02.2 - one module writes each collection.

`AC-DATA-02.2`: "Only the owning module's repository writes to each collection,
verified by a static check on Beanie document imports."

§2's constraint: "Ownership is exclusive: only the owning module's repository
writes to a collection. Another module reads it through the owner's public
service, never directly."

**Why the check is on imports.** A write is `await doc.save()`, `insert_many`,
`update_one`, `find_one_and_update` and a dozen other spellings, several of
which can be reached through a variable. Enumerating them is a losing game. But
every one of them needs the document class, and getting the document class needs
an import of `app.modules.<owner>.models` - a single, unambiguous, statically
visible act. So the import is the thing checked, and it is checked by AST rather
than by regex, because `# noqa`-style evasion and multi-line imports both defeat
text matching.

**What this buys.** The modular monolith is only modular if a change to
`profiles` has one place to look. The moment `matching` writes to `profiles` -
even something innocuous, even a cached field - the profile module's invariants
are enforced in two files, and the second one will be forgotten. `lint-imports`
contract 2 already forbids `app.modules.a -> app.modules.b`; this is the
narrower statement that also covers the two collections owned outside
`modules/` (`ai_usage`, `failed_tasks`), which contract 2 says nothing about.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.documents import OWNERS, all_documents, collection_name, owner_of

APP = Path("apps") / "api" / "app"

#: The modules of the two collections §2 owns outside `modules/`.
INFRASTRUCTURE_MODELS = {
    "app.ai.usage": "ai",
    "app.core.tasks": "core",
}

#: Who may import a models module besides its owner, and why. Each is a
#: composition point, not a write path.
ALLOWED_IMPORTERS = {
    # The registry exists to name every document; that is its whole job.
    "app/documents.py",
    # `app.core.tasks` defines `FailedTask` and also the task decorator, so
    # every module's `tasks.py` imports it. It is not a write path to another
    # module's collection.
}


def python_files(repo: Path) -> list[Path]:
    return sorted((repo / APP).rglob("*.py"))


def imported_models(path: Path) -> set[str]:
    """Every `app.modules.<name>.models` / infrastructure models module a file
    imports, by AST.

    Covers `import a.b.models`, `from a.b import models` and
    `from a.b.models import X` - three spellings a regex would need three
    patterns for, and a fourth would appear.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found |= {f"{node.module}.{alias.name}" for alias in node.names}
    return {name for name in found if _is_models_module(name)}


def _is_models_module(dotted: str) -> bool:
    if dotted in INFRASTRUCTURE_MODELS:
        return True
    parts = dotted.split(".")
    return len(parts) >= 4 and parts[0] == "app" and parts[1] == "modules" and parts[3] == "models"


def owner_of_models_module(dotted: str) -> str:
    if dotted in INFRASTRUCTURE_MODELS:
        return INFRASTRUCTURE_MODELS[dotted]
    return dotted.split(".")[2]


def importing_module(relative: str) -> str | None:
    """Which module a file belongs to, or `None` for anything outside
    `modules/`."""
    parts = relative.split("/")
    if len(parts) >= 5 and parts[2] == "app" and parts[3] == "modules":
        return parts[4]
    return None


# -- the criterion ------------------------------------------------------------


def test_no_module_imports_another_modules_documents(repo: Path):
    """`AC-DATA-02.2`.

    The failure message says what to do instead, because the fix is never "add
    an exception": it is to call the owner's service, which is what §2's
    "through the owner's public service" means.
    """
    offenders: list[str] = []
    for path in python_files(repo):
        relative = path.relative_to(repo).as_posix()
        if relative.endswith(tuple(ALLOWED_IMPORTERS)) or relative in ALLOWED_IMPORTERS:
            continue
        importer = importing_module(relative)
        for dotted in imported_models(path):
            owner = owner_of_models_module(dotted)
            if importer is None or importer == owner:
                continue
            offenders.append(f"{relative} imports {dotted} (owned by {owner})")

    assert offenders == [], (
        "a module reached into another module's documents:\n  "
        + "\n  ".join(offenders)
        + "\nCall the owning module's service instead (§2: 'another module reads "
        "it through the owner's public service, never directly'). An exception "
        "here would move an invariant into two files, and the second one gets "
        "forgotten."
    )


def test_only_the_registry_composes_the_full_document_list(repo: Path):
    """One place names every document.

    A second file importing several modules' models would be a second answer to
    "what does `init_beanie` bind", and the two would drift - which surfaces as
    a query against an unregistered collection, at runtime, in whichever
    entrypoint had the shorter list.
    """
    composers: list[str] = []
    for path in python_files(repo):
        relative = path.relative_to(repo).as_posix()
        owners = {owner_of_models_module(d) for d in imported_models(path)}
        if len(owners) > 1:
            composers.append(relative)

    assert composers == ["apps/api/app/documents.py"], (
        f"{composers} each import more than one module's documents; only the registry may."
    )


# -- the registry agrees with the specification -------------------------------


def test_every_document_has_exactly_one_owner():
    """The registry's own consistency. A document listed under two owners would
    make `owner_of` return whichever came first in a dict."""
    seen: dict[str, str] = {}
    for owner, documents in OWNERS.items():
        for document in documents:
            collection = collection_name(document)
            assert collection not in seen, (
                f"{collection} is owned by both {seen.get(collection)} and {owner}"
            )
            seen[collection] = owner


@pytest.mark.parametrize(
    "document", all_documents(), ids=[collection_name(d) for d in all_documents()]
)
def test_owner_of_answers_for_every_collection(document):
    assert owner_of(collection_name(document)) in OWNERS


def test_owner_of_refuses_an_unknown_collection():
    """Rather than returning a default. A collection nobody owns is a
    collection no retention rule covers and no deletion sweep finds; answering
    "core" would hide that."""
    with pytest.raises(KeyError):
        owner_of("sessions")


def test_the_owner_named_in_the_spec_table_is_the_owner_in_the_registry(repo: Path):
    """The specification's `Owner` column, compared row by row.

    This is the assertion that makes the registry a transcription rather than an
    opinion. Filing `audit_log` under `tracker` because that is where it is used
    would pass every other check in this file.
    """
    text = (repo / "docs" / "spec" / "17-data-model.md").read_text(encoding="utf-8")
    section = text.split("## 2. Collections", 1)[1].split("### 2.1", 1)[0]

    mismatches: list[str] = []
    for line in section.split("\n"):
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 6 or cells[4] not in ("R1", "R2"):
            continue
        collection = cells[1].strip("`")
        # "apply (append-only, shared)" -> "apply"
        declared = cells[2].split(" ")[0]
        if cells[4] == "R2":
            continue
        try:
            actual = owner_of(collection)
        except KeyError:
            mismatches.append(f"{collection}: §2 says {declared}, nothing owns it")
            continue
        if actual != declared:
            mismatches.append(f"{collection}: §2 says {declared}, registry says {actual}")

    assert mismatches == [], "\n  ".join(mismatches)


def test_the_two_infrastructure_collections_are_where_the_spec_puts_them():
    """§2 gives `ai_usage` to `ai` and `failed_tasks` to `core`, neither of
    which is a `modules/` package.

    Stated as its own test because it is the one pair a reader would assume was
    a mistake in the registry. §2 calls them "the two infrastructure
    collections": they have no user-facing feature, so a module for either would
    be eight empty files around one document.
    """
    assert owner_of("ai_usage") == "ai"
    assert owner_of("failed_tasks") == "core"


def test_the_detector_would_catch_a_violation(tmp_path: Path):
    """A static check that matched nothing would pass over every violation.

    All three import spellings, because a check that caught only
    `from x.models import Y` is a check the next person writes around without
    meaning to.
    """
    for source in (
        "from app.modules.profile.models import Profile\n",
        "from app.modules.profile import models\n",
        "import app.modules.profile.models\n",
    ):
        path = tmp_path / "leak.py"
        path.write_text(source, encoding="utf-8")

        found = imported_models(path)

        assert found, f"the detector missed {source!r}"
        assert {owner_of_models_module(d) for d in found} == {"profile"}


def test_the_detector_ignores_an_unrelated_import(tmp_path: Path):
    """False positives would get the check disabled."""
    path = tmp_path / "fine.py"
    path.write_text(
        "from app.core.documents import UserOwnedDoc\nfrom app.shared.money import Money\n",
        encoding="utf-8",
    )

    assert imported_models(path) == set()
