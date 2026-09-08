"""Declared indexes versus live indexes - `DATA-03`.

`AC-DATA-03.1`: "Every index above is declared in code and present at
`/readyz`."
`AC-DATA-03.3`: "No index exists in the live database that is not declared in
code (drift in the other direction is also a failure)."
`AC-DATA-01.3`: "`/readyz` returns 503 listing any declared index that is absent
from the live database."

**Why both directions are failures.** A missing index is the obvious one: the
query still returns the right rows, just by scanning, so nothing breaks until
the collection is large - at which point adding the index needs a maintenance
window. `AC-OPS-01.3` states it plainly: "a container that is up but missing an
index is not ready".

An *extra* index is the less obvious one and it is the reason this module
compares in both directions. Every index costs write throughput and memory, and
Atlas M0 has 512 MB total (`DATA-06`). An index created by hand during an
incident - which is precisely when someone will create one - is invisible
afterwards: it does not appear in any diff, nobody remembers it, and it is
consuming the headroom the declared set was budgeted against. §1 says it
outright: "No index is created by hand in Atlas."

**Comparison is by key pattern, not by name.** Names are ours to choose and a
rename is not a change; the key pattern is what the planner uses. Comparing
names would report drift for a renamed index and miss a genuinely different one
declared under an old name. TTL and uniqueness *are* compared, because an index
that has lost its `expireAfterSeconds` is a retention rule that stopped running
and an index that has lost `unique` is an invariant that stopped being enforced
- and neither shows up in a key-pattern comparison.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from beanie import Document
from pymongo.asynchronous.database import AsyncDatabase

from app.core.documents import declared_indexes

#: Mongo creates this one itself, on every collection. It is never declared and
#: must never be reported as drift.
IMPLICIT_INDEX = "_id_"

#: Options that change what an index *means* rather than what it is called.
#: Compared alongside the key pattern; anything else Mongo reports (`v`, `ns`,
#: `background`) is noise that differs by server version.
MEANINGFUL_OPTIONS = ("unique", "sparse", "expireAfterSeconds", "partialFilterExpression")


@dataclass(frozen=True, slots=True)
class IndexSpec:
    """One index, reduced to what has to match.

    The key pattern is a tuple of `(field, direction)` pairs so it is hashable
    and order-sensitive: `(user_id, score)` and `(score, user_id)` are different
    indexes serving different queries, and a set of frozensets would call them
    equal.
    """

    keys: tuple[tuple[str, Any], ...]
    unique: bool = False
    sparse: bool = False
    expire_after_seconds: int | None = None
    partial_filter: str | None = None
    name: str = ""

    @property
    def signature(self) -> tuple[Any, ...]:
        """What must match. Deliberately excludes `name`."""
        return (
            self.keys,
            self.unique,
            self.sparse,
            self.expire_after_seconds,
            self.partial_filter,
        )

    def __str__(self) -> str:
        rendered = ", ".join(f"{field}:{direction}" for field, direction in self.keys)
        extras = []
        if self.unique:
            extras.append("unique")
        if self.sparse:
            extras.append("sparse")
        if self.expire_after_seconds is not None:
            extras.append(f"ttl={self.expire_after_seconds}s")
        if self.partial_filter:
            extras.append(f"partial={self.partial_filter}")
        suffix = f" [{', '.join(extras)}]" if extras else ""
        return f"({rendered}){suffix}"


@dataclass(frozen=True, slots=True)
class Drift:
    """What one collection's declared and live index sets disagree about."""

    collection: str
    missing: tuple[IndexSpec, ...] = field(default_factory=tuple)
    undeclared: tuple[IndexSpec, ...] = field(default_factory=tuple)

    @property
    def clean(self) -> bool:
        return not self.missing and not self.undeclared

    def describe(self) -> list[str]:
        out = [f"{self.collection}: declared but absent: {spec}" for spec in self.missing]
        out += [
            f"{self.collection}: present but not declared: {spec} - §1 says no "
            "index is created by hand in Atlas; every index costs write "
            "throughput and memory, and M0 has 512 MB"
            for spec in self.undeclared
        ]
        return out


def from_declaration(index: Any) -> IndexSpec | None:
    """One `Settings.indexes` entry as an `IndexSpec`.

    Beanie accepts three shapes and this codebase uses two of them: a
    `pymongo.IndexModel` (required for TTL, unique, sparse and partial, which
    only that form can express) and a list of pairs. A checker that understood
    one would silently ignore the others, and "no drift" would mean "nothing was
    compared".
    """
    document = getattr(index, "document", None)
    if document is not None:
        keys = _canonical(tuple(document.get("key", {}).items()))
        return IndexSpec(
            keys=keys,
            unique=bool(document.get("unique", False)),
            sparse=bool(document.get("sparse", False)),
            expire_after_seconds=document.get("expireAfterSeconds"),
            partial_filter=_render_filter(document.get("partialFilterExpression")),
            name=str(document.get("name", "")),
        )
    if isinstance(index, str):
        return IndexSpec(keys=((index, 1),))
    if isinstance(index, list | tuple):
        keys = tuple(
            (pair[0], pair[1]) if isinstance(pair, list | tuple) else (pair, 1) for pair in index
        )
        return IndexSpec(keys=keys)
    return None


def from_live(info: Mapping[str, Any]) -> IndexSpec:
    """One row of `listIndexes` as an `IndexSpec`.

    **A text index does not come back the way it went in.** Mongo replaces the
    declared fields with its own internal pair, `(_fts, text), (_ftsx, 1)`, and
    moves the real field names into `weights`. Compared naively, every text
    index reads as both a missing declaration *and* an undeclared live index -
    two false failures per text index, which is how this check gets muted. The
    field names are reconstructed from `weights` instead.
    """
    keys = tuple(info.get("key", {}).items())
    if any(field == "_fts" for field, _ in keys):
        keys = tuple((field, "text") for field in info.get("weights", {}))
    return IndexSpec(
        keys=_canonical(keys),
        unique=bool(info.get("unique", False)),
        sparse=bool(info.get("sparse", False)),
        expire_after_seconds=info.get("expireAfterSeconds"),
        partial_filter=_render_filter(info.get("partialFilterExpression")),
        name=str(info.get("name", "")),
    )


def _canonical(keys: tuple[tuple[str, Any], ...]) -> tuple[tuple[str, Any], ...]:
    """The key pattern, in a comparable order.

    Field order is load-bearing for an ordinary compound index - `(user_id,
    score)` and `(score, user_id)` serve different queries - and meaningless
    for a text index, where Mongo discards the declared order entirely and
    keeps the fields in a `weights` document. So text-index fields are sorted
    and everything else is left alone. Sorting both sides is what stops `jobs`'
    search index reporting as simultaneously missing and undeclared, which is
    two false failures for one correct index.
    """
    if any(direction == "text" for _, direction in keys):
        return tuple(sorted(keys))
    return keys


def _render_filter(expression: Any) -> str | None:
    """A partial filter as a stable string.

    Rendered rather than compared as a dict because a dict is not hashable, so
    an `IndexSpec` carrying one could not go in a set.

    **Normalised recursively**, which is the part that matters. Mongo returns
    nested documents as `SON`, so `{"job_id": {"$exists": True}}` comes back as
    `{"job_id": SON([("$exists", True)])}` - and `repr` of those two strings
    differs while the filters are identical. One level of `dict()` is not
    enough; a partial index would report as drifted forever.
    """
    if not expression:
        return None
    return repr(_normalise(expression))


def _normalise(value: Any) -> Any:
    """`SON` and nested mappings to plain dicts with sorted keys."""
    if isinstance(value, Mapping):
        return {key: _normalise(value[key]) for key in sorted(value)}
    if isinstance(value, list | tuple):
        return [_normalise(item) for item in value]
    return value


def declared_for(document: type[Document]) -> tuple[IndexSpec, ...]:
    specs = [from_declaration(index) for index in declared_indexes(document)]
    return tuple(spec for spec in specs if spec is not None)


async def live_for(database: AsyncDatabase[Any], collection: str) -> tuple[IndexSpec, ...]:
    """Every index Mongo reports, minus the implicit `_id_`.

    `list_indexes()` is itself a coroutine in PyMongo's async driver, so it has
    to be awaited before the cursor can be iterated. Chaining `.to_list()`
    directly onto it returns nothing and silently reports zero indexes - which
    would make every check here pass while comparing against an empty set.
    """
    cursor = await database[collection].list_indexes()
    rows = await cursor.to_list(length=None)
    return tuple(from_live(row) for row in rows if row.get("name") != IMPLICIT_INDEX)


async def compare(database: AsyncDatabase[Any], documents: Sequence[type[Document]]) -> list[Drift]:
    """Declared versus live, per collection. Only collections that disagree."""
    out: list[Drift] = []
    for document in documents:
        collection = str(getattr(document.Settings, "name", document.__name__))
        declared = {spec.signature: spec for spec in declared_for(document)}
        live = {spec.signature: spec for spec in await live_for(database, collection)}

        drift = Drift(
            collection=collection,
            missing=tuple(declared[key] for key in declared if key not in live),
            undeclared=tuple(live[key] for key in live if key not in declared),
        )
        if not drift.clean:
            out.append(drift)
    return out


async def verify(
    database: AsyncDatabase[Any], documents: Sequence[type[Document]]
) -> tuple[bool, list[str]]:
    """`/readyz`'s index check. `(ok, reasons)`.

    Never raises: a `/readyz` that 500s instead of 503ing tells a load balancer
    the container is broken rather than not-yet-ready, and the two get handled
    differently.
    """
    try:
        drifts = await compare(database, documents)
    except Exception as failure:  # noqa: BLE001 - reported, not raised
        return False, [f"could not read indexes: {type(failure).__name__}"]
    reasons = [line for drift in drifts for line in drift.describe()]
    return not reasons, reasons


__all__ = [
    "IMPLICIT_INDEX",
    "MEANINGFUL_OPTIONS",
    "Drift",
    "IndexSpec",
    "compare",
    "declared_for",
    "from_declaration",
    "from_live",
    "live_for",
    "verify",
]
