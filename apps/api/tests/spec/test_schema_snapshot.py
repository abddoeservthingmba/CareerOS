"""T-DATA-02.1 - the collections match `17-data-model.md` §2, field for field.

`AC-DATA-02.1`: "Every collection above exists with the exact field names given;
a schema-snapshot test fails on drift."

**The golden file is generated from the specification, not written by hand.**
That is the whole design of this check. A hand-maintained snapshot drifts the
same way the code does: the person who renames a field updates the snapshot in
the same commit, the test goes green, and the specification is now wrong with no
signal anywhere. Here, §2's JSON blocks are *parsed* and compared against the
Beanie documents' own fields, so a rename fails until either the spec or the
code changes - and whichever one is wrong is the one the failure names.

**Why field *names* and not types.** §2 gives example values, not a type
grammar: `"size_bytes": 184320` says the field exists and is a number, not that
it is a positive `int`. Inferring types from examples would produce a check that
was confidently wrong about nullability, which is the property that actually
matters at a boundary. The types are enforced by pydantic at every write, and by
mypy at every call site; what no other check covers is whether the *set of
fields* still matches what the specification promises, and that is what this
asserts.

The comparison is deliberately two-directional. A field in the code and not in
the spec is an undocumented column; a field in the spec and not in the code is a
promise nothing keeps. Both fail, and each says which side to fix.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from beanie import Document

from app.documents import ABSENT_UNTIL_R2, OWNERS, all_documents, collection_name

SPEC = Path("docs") / "spec" / "17-data-model.md"

#: The fields `BaseDoc` / `UserOwnedDoc` contribute. §2's JSON blocks omit them
#: because §1 already declares them for every collection, so they are added to
#: the expected set rather than reported as undocumented.
#: `revision_id` is Beanie's own: it is declared on every `Document` for
#: optimistic locking, whether or not a document opts in. Not ours to document
#: in §2, and not ours to remove.
CONVENTION_FIELDS = frozenset(
    {"_id", "created_at", "updated_at", "user_id", "deleted_at", "revision_id"}
)

#: Fields present in the code and deliberately not in §2's example JSON, each
#: with the reason it exists. Kept short: a long list here is a specification
#: that has stopped describing the data model.
#:
#: Every entry is a field §2 *names in prose* but omits from its example block.
#: That is a documentation gap in the specification, not licence to add fields -
#: which is why each one cites the sentence that requires it.
JUSTIFIED_EXTRA: dict[str, dict[str, str]] = {
    "jobs": {
        # §2.6's `status` enum includes `merged_into`, which is meaningless
        # without naming the survivor. §7's registry lists the member.
        "merged_into": "jobs.status has a merged_into member; the row must name the survivor",
    },
    "user_job_actions": {
        # §2.7: "`reason` from a fixed enum plus optional free text".
        "reason_text": "§2.7 requires optional free text alongside the enum reason",
    },
    "answer_bank": {
        # §7's registry defines `answer_bank.answer_type` with seven members.
        "answer_type": "§7's registry defines answer_bank.answer_type",
    },
}

#: `_id` inside a nested object is not a document id. `applications.interviews`
#: items carry an `id` because reminders point at a specific round (§2.10).
NESTED_ID_OK = frozenset({"interviews"})

JSON_BLOCK = re.compile(r"```json\n(.*?)```", re.DOTALL)
#: `// collection-name` above a block, or `### 2.N `collection``.
BLOCK_LABEL = re.compile(r"^\s*//\s*([a-z_]+)")
HEADING = re.compile(r"^###\s+2\.[0-9.]+\s+(.*)$", re.MULTILINE)
BACKTICKED = re.compile(r"`([a-z_]+)`")


#: `{...}` and `[...]` in §2 mean "the shape is declared elsewhere" - `identity`
#: points at `03-profile.md` §2, `filters` at `JOB-06`. They are prose inside a
#: JSON block, so they are normalised to empty containers: this check is about
#: the *top-level* field set, and a nested shape someone else owns is not this
#: test's business.
PLACEHOLDER = re.compile(r"\{\s*\.\.\.\s*\}|\[\s*\.\.\.\s*\]")


def _strip_comments(block: str) -> str:
    """§2's blocks are annotated JSON, not JSON.

    They carry `// comments`, `/* ... */` notes, `{...}` placeholders and
    trailing commas, because they are written for a person. Parsing them
    leniently is the price of the specification being readable; the alternative
    is a machine-readable schema file nobody reads, which is how a data model
    stops describing the data.

    **The scan is string-aware, and that is not fussiness.** A regex stripping
    `//` to end of line also eats the middle of every URL in the file -
    `"url": "https://..."` becomes `"url": "https:` - so the four blocks
    containing a URL failed to parse, and the check reported "§2 has no JSON
    block for jobs" rather than a field mismatch. A parser that silently finds
    nothing is the worst failure available to a test like this: it would have
    passed had the expected set been allowed to default to empty.
    """
    out: list[str] = []
    index = 0
    in_string = False
    length = len(block)
    while index < length:
        char = block[index]
        if in_string:
            out.append(char)
            if char == "\\" and index + 1 < length:
                out.append(block[index + 1])
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if block.startswith("//", index):
            end = block.find("\n", index)
            index = length if end == -1 else end
            continue
        if block.startswith("/*", index):
            end = block.find("*/", index)
            index = length if end == -1 else end + 2
            continue
        out.append(char)
        index += 1

    text = PLACEHOLDER.sub("{}", "".join(out))
    # Trailing commas, including the one left behind by a removed comment.
    return re.sub(r",(\s*[}\]])", r"\1", text)


def spec_blocks(repo: Path) -> dict[str, set[str]]:
    """Collection -> the field names §2's JSON block declares for it.

    Blocks are attributed to a collection by the `// name` comment on their
    first line, falling back to the backticked name in the enclosing `### 2.N`
    heading. §2 uses both forms.
    """
    text = (repo / SPEC).read_text(encoding="utf-8")
    section = text.split("## 2. Collections", 1)[1].split("\n## 3. Indexes", 1)[0]

    found: dict[str, set[str]] = {}
    position = 0
    for match in JSON_BLOCK.finditer(section):
        block = match.group(1)
        label = _label_for(section, block, match.start(), position)
        position = match.end()
        if label is None:
            continue
        for name, fields in _parse_block(block).items():
            found.setdefault(name or label, set()).update(fields)
    return found


def _label_for(section: str, block: str, start: int, previous: int) -> str | None:
    """Which collection a block belongs to."""
    inline = BLOCK_LABEL.match(block)
    if inline:
        return inline.group(1)
    headings = HEADING.findall(section[:start])
    if not headings:
        return None
    names = BACKTICKED.findall(headings[-1])
    return names[0] if names else None


def _parse_block(block: str) -> dict[str, set[str]]:
    """One annotated block -> `{collection_or_empty: field names}`.

    A block may hold several small collections separated by `// name` comments
    (§2.5.1, §2.7, §2.11, §2.12 each do this), so the block is split on those
    comments first.
    """
    chunks: dict[str, str] = {}
    current = ""
    buffer: list[str] = []
    for line in block.split("\n"):
        labelled = BLOCK_LABEL.match(line)
        if labelled and (buffer or labelled.group(1) != current):
            if buffer:
                chunks[current] = "\n".join(buffer)
                buffer = []
            current = labelled.group(1)
            continue
        buffer.append(line)
    if buffer:
        chunks[current] = "\n".join(buffer)

    out: dict[str, set[str]] = {}
    for name, chunk in chunks.items():
        try:
            parsed = json.loads(_strip_comments(chunk))
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            out.setdefault(name, set()).update(parsed)
    return out


def code_fields(document: type[Document]) -> set[str]:
    """The top-level field names a document persists, by its stored alias."""
    return {
        (field.alias or name) for name, field in document.model_fields.items()
    } | CONVENTION_FIELDS


# -- the criterion ------------------------------------------------------------


def test_every_r1_collection_in_the_spec_has_a_document(repo: Path):
    """`AC-DATA-02.1`, first clause: "Every collection above exists".

    Asserted against §2's table rather than a copied count, so the arithmetic
    in §2's parenthetical ("nineteen are R1") cannot make this test wrong. The
    table has a `Track` column; it is the authority.
    """
    declared = _r1_table_rows(repo)
    built = set(collection_name(document) for document in all_documents())

    missing = sorted(declared - built)
    assert missing == [], (
        f"§2 declares R1 collection(s) {missing} with no Beanie document. Every "
        "R1 collection exists by the R1 gate."
    )


def test_no_collection_exists_that_the_spec_does_not_declare(repo: Path):
    """The other direction. An undeclared collection is data nothing owns, no
    retention rule covers (`DATA-05`) and no deletion sweep finds (`AUTH-07`)."""
    declared = set(_table_rows(repo))
    built = set(collection_name(document) for document in all_documents())

    undeclared = sorted(built - declared)
    assert undeclared == [], (
        f"{undeclared} exist in code but are not in §2's table. Add the row to "
        "the specification in the same commit (`CLAUDE.md`: never invent a "
        "requirement)."
    )


def test_the_r2_collections_are_absent_not_half_built(repo: Path):
    """`01-foundations.md` §15: four states, no fifth.

    §2's table marks three collections R2 and `CLAUDE.md` builds R1 only. They
    are `absent`, and this asserts that - an empty document class for one of
    them would be the fifth state.
    """
    built = set(collection_name(document) for document in all_documents())

    for collection in ABSENT_UNTIL_R2:
        assert collection not in built, (
            f"{collection} is an R2 collection (§2's table) but a document "
            "exists for it. R1 builds the R1 track."
        )
    assert set(ABSENT_UNTIL_R2) == set(_table_rows(repo)) - _r1_table_rows(repo)


@pytest.mark.parametrize(
    "document", all_documents(), ids=[collection_name(d) for d in all_documents()]
)
def test_the_documents_fields_match_the_spec_block(repo: Path, document: type[Document]):
    """`AC-DATA-02.1`'s "exact field names given", per collection.

    Two-directional. The failure message names which side to change, because
    the answer is genuinely one or the other and guessing wrong means either an
    undocumented column or a deleted feature.
    """
    collection = collection_name(document)
    expected = spec_blocks(repo).get(collection)
    if expected is None:
        pytest.fail(
            f"§2 has no JSON block for {collection}. Every collection's shape is "
            "declared there; a collection with only prose is the state §2.5.1 "
            "records as consistency finding F9."
        )

    actual = code_fields(document)
    justified = set(JUSTIFIED_EXTRA.get(collection, {}))

    undocumented = sorted(actual - expected - CONVENTION_FIELDS - justified)
    unimplemented = sorted(expected - actual)

    assert undocumented == [], (
        f"{collection} persists {undocumented}, which §2 does not declare. Add "
        "the field to §2's JSON block in the same commit, or remove it."
    )
    assert unimplemented == [], (
        f"§2 declares {collection}.{unimplemented} and the document does not "
        "have it. A field in the specification and not in the code is a promise "
        "nothing keeps."
    )


# -- the conventions, over every document -------------------------------------


@pytest.mark.parametrize(
    "document", all_documents(), ids=[collection_name(d) for d in all_documents()]
)
def test_every_document_declares_its_collection_name(document: type[Document]):
    """Without `Settings.name`, Beanie uses the class name - a collection §2
    never declared, created silently on first write."""
    assert collection_name(document)


@pytest.mark.parametrize(
    "document", all_documents(), ids=[collection_name(d) for d in all_documents()]
)
def test_every_document_has_a_string_id(document: type[Document]):
    """`AC-DATA-01.1` / `AC-FOUND-03.3` - a ULID string, never an ObjectId.

    Asserted per document rather than once on `BaseDoc`, because `Document`
    contributes its own `id: PydanticObjectId` and wins the MRO - so a subclass
    that redeclares `id` wrongly, or a future base that forgets to redeclare it,
    stores an ObjectId while every type annotation still says `str`.
    """
    field = document.model_fields["id"]
    assert field.annotation is str, (
        f"{document.__name__}.id is {field.annotation}, not str; Mongo would "
        "store an ObjectId and 17-data-model.md §1's 'No ObjectId anywhere' "
        "would be false at rest"
    )


@pytest.mark.parametrize(
    "document", all_documents(), ids=[collection_name(d) for d in all_documents()]
)
def test_no_document_nests_a_document(document: type[Document]):
    """§1: nothing is embedded past one level where the nested item can grow
    unbounded, and a nested `Document` is a document with no collection - it
    cannot be queried, indexed or deleted on its own."""
    for name, field in document.model_fields.items():
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, Document):
            pytest.fail(f"{document.__name__}.{name} embeds the document {annotation.__name__}")


def test_no_two_documents_claim_the_same_collection():
    """Two documents writing one collection is two schemas for one set of rows,
    and §2's "ownership is exclusive" would have no meaning."""
    names = [collection_name(document) for document in all_documents()]

    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert duplicates == [], f"{duplicates} are claimed by more than one document"


def test_every_owner_in_the_spec_table_owns_something(repo: Path):
    """§2's `Owner` column, checked against the registry. An owner named in the
    table with no documents means a collection was filed under the wrong
    module."""
    text = (repo / SPEC).read_text(encoding="utf-8")
    section = text.split("## 2. Collections", 1)[1].split("### 2.1", 1)[0]

    owners: set[str] = set()
    for line in section.split("\n"):
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) >= 4 and cells[1].startswith("`") and cells[3] in ("R1", "R2"):
            # "apply (append-only, shared)" -> "apply"
            owners.add(cells[2].split(" ")[0])

    assert owners <= set(OWNERS), f"§2 names owner(s) {sorted(owners - set(OWNERS))}"


# -- reading §2's table -------------------------------------------------------


def _table_rows(repo: Path) -> set[str]:
    """Every collection in §2's table, whatever its track."""
    return {name for name, _ in _rows(repo)}


def _r1_table_rows(repo: Path) -> set[str]:
    return {name for name, track in _rows(repo) if track == "R1"}


def _rows(repo: Path) -> list[tuple[str, str]]:
    text = (repo / SPEC).read_text(encoding="utf-8")
    section = text.split("## 2. Collections", 1)[1].split("### 2.1", 1)[0]

    out: list[tuple[str, str]] = []
    for line in section.split("\n"):
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 6 or cells[4] not in ("R1", "R2"):
            continue
        name = cells[1].strip("`")
        if re.fullmatch(r"[a-z_]+", name):
            out.append((name, cells[4]))
    return out


def test_every_justified_extra_is_still_needed(repo: Path):
    """An allowance nothing uses is an allowance for whatever comes next.

    `JUSTIFIED_EXTRA` is the one place this check can be weakened without the
    weakening being obvious, so a stale entry is deleted rather than left as
    room. When one becomes unnecessary - because §2's block gained the field -
    this fails and the row goes.
    """
    blocks = spec_blocks(repo)
    stale: list[str] = []
    for collection, fields in JUSTIFIED_EXTRA.items():
        documented = blocks.get(collection, set())
        stale += [f"{collection}.{name}" for name in fields if name in documented]

    assert stale == [], (
        f"§2 now declares {stale}, so the JUSTIFIED_EXTRA entry is no longer "
        "needed. Delete it - an unused allowance is room for the next field."
    )


def test_every_justified_extra_names_a_field_that_exists():
    """The other direction: an entry for a field nobody persists is a note
    about code that has been deleted."""
    by_collection = {collection_name(d): code_fields(d) for d in all_documents()}
    missing: list[str] = []
    for collection, fields in JUSTIFIED_EXTRA.items():
        actual = by_collection.get(collection, set())
        missing += [f"{collection}.{name}" for name in fields if name not in actual]

    assert missing == [], f"JUSTIFIED_EXTRA names {missing}, which no document has"


def test_the_table_parser_finds_every_row(repo: Path):
    """The parser above is load-bearing for four assertions, so its own output
    is checked. §2's table has 23 rows; a parser that silently found three
    would make every check above vacuously pass."""
    rows = _rows(repo)

    assert len(rows) == 23, f"§2's table parsed to {len(rows)} rows: {rows}"
    assert len(_r1_table_rows(repo)) == 20
    assert _table_rows(repo) - _r1_table_rows(repo) == set(ABSENT_UNTIL_R2)
