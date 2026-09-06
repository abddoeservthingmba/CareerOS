"""Cursor pagination - `FOUND-07`.

`01-foundations.md` §7: "Deep lists that stay constant-time and never skip or
repeat an item when the underlying data changes mid-scroll."

Offset pagination does both of those things wrong. `skip(400).limit(20)` makes
Mongo walk 400 documents it will throw away, so page 20 costs twenty times page
1; and if a document before your position is deleted while you are reading, every
later page shifts by one and you never see the item that slid across the
boundary. On a matches feed that is a job the user was shown a count for and then
never saw.

Keyset pagination fixes both: the cursor carries the sort values of the last row,
the next query asks for "everything after this point", and the index does the
work. Cost is the same for page 1 and page 400, and an insert or delete elsewhere
in the collection cannot move your position.

Three properties this module exists to guarantee.

**The cursor is opaque and signed.** It is base64url of a JSON payload plus an
HMAC over it, keyed with `SECRET_KEY`. Opaque so clients cannot build one and
depend on its shape; signed so a client cannot forge a position into another
user's data (`AC-FOUND-07.2`). The key is passed in rather than read here:
`shared` is the innermost layer and may not import `core` (§4's `layers`
contract), which is the same reason `shared/ulid.py` takes its instant.

**The sort is a total order.** Always tie-broken by `_id`. Without the
tie-break, two documents with the same `created_at` have no defined order
between them, and a keyset filter over a non-total order either repeats the tie
group or skips it - the exact failure `AC-FOUND-07.1` tests for.

**Nulls have a declared position, checked against reality.** BSON's type
ordering puts null and missing *before* every number and string, so an ascending
sort is nulls-first and a descending sort is nulls-last, and no `sort()`
argument changes that. A `SortKey` therefore declares where it expects nulls and
this module refuses the ones Mongo will not honour, rather than generating a
filter that disagrees with the index and silently drops rows.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, Self

#: §7: "`limit` default 25, max 100."
DEFAULT_LIMIT = 25
MAX_LIMIT = 100

#: Bumped when the payload shape changes, so a cursor issued by an older
#: deployment is rejected rather than misread during a rolling restart.
CURSOR_VERSION = 1

#: Truncated to keep the cursor short. 128 bits is far past forgery reach for a
#: value that is only meaningful for one scroll.
SIGNATURE_BYTES = 16

Direction = Literal[1, -1]
NullPosition = Literal["first", "last"]


class CursorError(ValueError):
    """The cursor is not one we issued.

    A plain `ValueError` rather than an `AppError`, because `shared` may not
    import `core`. `core.errors.InvalidCursor` wraps it, and `main.py` renders
    that as 400 `invalid_cursor` in the one place that renders problems.
    """


# -- the sort ---------------------------------------------------------------


@dataclass(frozen=True)
class SortKey:
    """One field of a sort, and where its nulls land.

    `nulls` is not a preference. BSON orders MinKey < Null < numbers < strings,
    so an ascending sort puts null and missing first and a descending sort puts
    them last, whatever the caller would like. Declaring it wrong raises here
    rather than producing a keyset filter that disagrees with the index - which
    does not fail, it just quietly drops rows.
    """

    field: str
    direction: Direction = 1
    nullable: bool = False
    nulls: NullPosition | None = None

    def __post_init__(self) -> None:
        if self.direction not in (1, -1):
            raise ValueError(f"{self.field}: direction is 1 or -1, not {self.direction!r}")
        natural: NullPosition = "first" if self.direction == 1 else "last"
        if self.nullable:
            if self.nulls is None:
                raise ValueError(
                    f"{self.field} is nullable, so its null position must be stated "
                    f"(§7: 'a sort on a nullable field must have a defined null "
                    f"position'). Mongo will put them {natural}."
                )
            if self.nulls != natural:
                raise ValueError(
                    f"{self.field} declares nulls {self.nulls}, but a "
                    f"{'ascending' if self.direction == 1 else 'descending'} BSON "
                    f"sort puts them {natural} and no sort argument changes that. "
                    "Sort on a computed non-null field if the other order is needed."
                )
        elif self.nulls is not None:
            raise ValueError(f"{self.field}: nulls position is meaningless unless nullable")

    @property
    def nulls_first(self) -> bool:
        return self.direction == 1


@dataclass(frozen=True)
class SortSpec:
    """A total order. `_id` is appended, never omitted.

    Appended rather than required of the caller: an endpoint author who forgets
    it gets a list that repeats or skips its tie groups under concurrent writes,
    and that failure shows up in production under load rather than in review.
    """

    keys: tuple[SortKey, ...] = ()
    id_direction: Direction = -1

    def __post_init__(self) -> None:
        names = [key.field for key in self.keys]
        if "_id" in names:
            raise ValueError("_id is the tie-break and is appended; do not list it")
        if len(set(names)) != len(names):
            raise ValueError(f"a field is sorted twice: {names}")

    @property
    def all_keys(self) -> tuple[SortKey, ...]:
        return (*self.keys, SortKey("_id", self.id_direction))

    def mongo_sort(self) -> list[tuple[str, int]]:
        return [(key.field, key.direction) for key in self.all_keys]

    def signature(self) -> str:
        """Identifies the order this cursor was cut against.

        A cursor carried over to an endpoint sorted differently would resume at
        a position that means nothing in the new order - not an error, just a
        page from the middle of nowhere. Binding the sort makes it an error.
        """
        return ",".join(f"{key.field}:{key.direction}" for key in self.all_keys)


#: The default for anything with no other order: newest first, `_id` descending.
#: ULIDs sort by time, so this is chronological without a second field.
NEWEST_FIRST = SortSpec()


# -- the cursor -------------------------------------------------------------


@dataclass(frozen=True)
class Cursor:
    """A position in one user's list, under one sort order.

    `user_id` is inside the signed payload, not to authorise anything - the
    query is scoped by the repository either way - but so that a cursor replayed
    by someone else can be recognised and ignored (`AC-FOUND-07.3`).
    """

    values: tuple[Any, ...]
    id: str
    user_id: str | None
    sort: str

    def encode(self, key: str) -> str:
        payload = json.dumps(
            {
                "v": CURSOR_VERSION,
                "k": list(self.values),
                "i": self.id,
                "u": self.user_id,
                "s": self.sort,
            },
            separators=(",", ":"),
            sort_keys=True,
            default=_encode_value,
        ).encode("utf-8")
        # Appended at a fixed width rather than after a separator byte: an HMAC
        # is 16 arbitrary bytes and one of them is eventually `.`, which a
        # separator-based split would then cut at the wrong place. That failed
        # roughly one cursor in sixteen - often enough to be found, rare enough
        # to have been found in production.
        return _b64(payload + _sign(payload, key))

    @classmethod
    def decode(cls, raw: str, key: str) -> Self:
        """Return the position, or raise `CursorError`.

        Every failure path raises the same error with no detail about which
        check failed: "signature wrong" and "payload malformed" told apart is a
        forgery oracle, and the client can do nothing differently either way.
        """
        try:
            blob = _unb64(raw)
            payload, signature = blob[:-SIGNATURE_BYTES], blob[-SIGNATURE_BYTES:]
            if not payload or len(signature) != SIGNATURE_BYTES:
                raise CursorError("cursor is not one we issued")
            if not hmac.compare_digest(signature, _sign(payload, key)):
                raise CursorError("cursor is not one we issued")
            body = json.loads(payload)
            if body["v"] != CURSOR_VERSION:
                raise CursorError("cursor is not one we issued")
            return cls(tuple(body["k"]), body["i"], body["u"], body["s"])
        except CursorError:
            raise
        except (
            ValueError,
            KeyError,
            TypeError,
            UnicodeDecodeError,
            binascii.Error,
        ) as exc:
            raise CursorError("cursor is not one we issued") from exc


def _sign(payload: bytes, key: str) -> bytes:
    return hmac.new(key.encode("utf-8"), payload, hashlib.sha256).digest()[:SIGNATURE_BYTES]


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(raw: str) -> bytes:
    padded = raw + "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _encode_value(value: object) -> str:
    """Datetimes and anything else JSON will not take.

    ISO 8601 keeps a datetime's ordering under string comparison, and the value
    is decoded back into the filter by `_decode_value`.
    """
    from datetime import datetime

    if isinstance(value, datetime):
        return f"@dt:{value.isoformat()}"
    raise TypeError(f"a sort key of type {type(value).__name__} cannot enter a cursor")


def _decode_value(value: object) -> object:
    from datetime import datetime

    if isinstance(value, str) and value.startswith("@dt:"):
        return datetime.fromisoformat(value[4:])
    return value


# -- the filter -------------------------------------------------------------


def keyset_filter(sort: SortSpec, cursor: Cursor) -> dict[str, Any]:
    """ "Everything strictly after this position", as a Mongo filter.

    For keys `(a asc, b desc, _id asc)` at position `(x, y, z)` this is the
    lexicographic expansion::

        a > x  OR  (a == x AND b < y)  OR  (a == x AND b == y AND _id > z)

    One clause per prefix, which is why the number of `$or` branches is the
    number of sort keys and not something that grows with the data. Each branch
    is a prefix of the index, so each one is a range scan (`AC-FOUND-07.4`).
    """
    keys = sort.all_keys
    if len(cursor.values) != len(keys):
        raise CursorError("cursor is not one we issued")

    branches: list[dict[str, Any]] = []
    for index, key in enumerate(keys):
        after = _after(key, _decode_value(cursor.values[index]))
        if after is None:
            # Nothing follows this position by this key - a null in a
            # descending sort, where nulls are already the last group. The
            # tie-break branch below still applies, so dropping this one is
            # what keeps the traversal moving instead of re-serving the whole
            # null group forever.
            continue
        clause: dict[str, Any] = {}
        for earlier, earlier_key in zip(keys[:index], cursor.values[:index], strict=True):
            clause[earlier.field] = _decode_value(earlier_key)
        clause.update(after)
        branches.append(clause)

    if not branches:  # pragma: no cover - `_id` is never null, so never reached
        raise CursorError("cursor is not one we issued")
    return branches[0] if len(branches) == 1 else {"$or": branches}


def _after(key: SortKey, value: object) -> dict[str, Any] | None:
    """The "strictly after `value` in this key's order" condition, or `None`.

    `None` means "no row follows this one by this key alone" - which is a real
    answer, not an error, and the difference matters: returning a clause that
    matches the whole null group instead would re-serve it on every page and the
    traversal would never end.

    Null is also not a value you can compare with `$gt`: `{"a": {"$gt": null}}`
    matches nothing at all in Mongo, so an expansion that treated null as an
    ordinary value would stop dead at the first one and lose the rest of the
    list.
    """
    operator = "$gt" if key.direction == 1 else "$lt"

    if value is None:
        if key.nulls_first:
            # Ascending: nulls are the first group, so everything non-null
            # follows. The remaining nulls are reached by the `_id` tie-break.
            return {key.field: {"$ne": None}}
        # Descending: nulls are the last group. Nothing follows by this key;
        # the rest of the group is reached by the tie-break branch.
        return None

    condition: dict[str, Any] = {key.field: {operator: value}}
    if key.nullable and not key.nulls_first:
        # Descending with nulls last: after a non-null value comes the rest of
        # the non-nulls, then the nulls. `$lt` excludes null, so add it back.
        return {"$or": [condition, {key.field: None}]}
    return condition


# -- the page ---------------------------------------------------------------


@dataclass(frozen=True)
class Page[T]:
    """§7's response shape.

    No `total`. It costs a second query, and on a user-facing list nobody reads
    it - the count that matters is "is there more", which `has_more` answers for
    free. `/admin` may have one (§7).
    """

    items: list[T]
    next_cursor: str | None
    has_more: bool
    #: `AC-FOUND-07.5` - a request over the maximum is served, not refused, and
    #: the response says the limit moved so a client is not left believing it
    #: received 1000 items.
    clamped: bool = False
    limit: int = DEFAULT_LIMIT

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "items": self.items,
            "next_cursor": self.next_cursor,
            "has_more": self.has_more,
        }
        if self.clamped:
            body["clamped"] = True
        return body


def clamp_limit(limit: int | None) -> tuple[int, bool]:
    """§7: "A request over the max is clamped, not rejected, and the response
    says so."

    Rejecting would break a client that guessed too high on a screen the user is
    looking at; silently clamping would leave it believing it has everything.
    """
    if limit is None:
        return DEFAULT_LIMIT, False
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if limit > MAX_LIMIT:
        return MAX_LIMIT, True
    return limit, False


class Findable(Protocol):
    """What `paginate` needs of a query.

    Duck-typed rather than a Beanie import: `shared` is the innermost layer, and
    a protocol here is what lets the pagination logic be tested against a list
    without a database and used against `Document` without an adapter.
    """

    def find(self, *args: Any, **kwargs: Any) -> Any: ...


@dataclass
class PaginationRequest:
    """What an endpoint received, before it means anything.

    Separated from `paginate` so a router can parse and validate query
    parameters without touching the database - which is also what makes the
    clamping rule testable without one (`T-FOUND-07.5`).
    """

    cursor: str | None = None
    limit: int | None = None
    user_id: str | None = None
    secret: str = field(default="", repr=False)

    def resolve(self, sort: SortSpec) -> tuple[Cursor | None, int, bool]:
        """`(position, limit, clamped)`.

        A cursor signed for another user resolves to `None` - the first page -
        rather than an error (`AC-FOUND-07.3`). An error would confirm that the
        cursor was genuine, which is one bit more than a stranger should learn;
        and there is nothing the client could do with the answer anyway.
        """
        size, clamped = clamp_limit(self.limit)
        if not self.cursor:
            return None, size, clamped

        position = Cursor.decode(self.cursor, self.secret)
        if position.sort != sort.signature():
            # Not a forgery - a cursor from a differently sorted list. Resuming
            # would land at a position that means nothing in this order.
            raise CursorError("cursor is not one we issued")
        if position.user_id != self.user_id:
            return None, size, clamped
        return position, size, clamped


async def paginate[T](
    query: Findable,
    sort: SortSpec,
    request: PaginationRequest,
) -> Page[T]:
    """One page, and the cursor that follows it.

    `limit + 1` documents are fetched and the last is discarded: that is how
    `has_more` is answered without a `count`, which would be a second full scan
    of the same range on every page of every list.
    """
    position, size, clamped = request.resolve(sort)

    criteria = keyset_filter(sort, position) if position is not None else {}
    found = query.find(criteria) if criteria else query.find()
    rows: list[T] = await found.sort(sort.mongo_sort()).limit(size + 1).to_list()

    has_more = len(rows) > size
    items = rows[:size]
    next_cursor = (
        cursor_for(items[-1], sort, request.user_id).encode(request.secret)
        if has_more and items
        else None
    )
    return Page(
        items=items,
        next_cursor=next_cursor,
        has_more=has_more,
        clamped=clamped,
        limit=size,
    )


def cursor_for(row: Any, sort: SortSpec, user_id: str | None) -> Cursor:
    """The position of `row`, for the next request to resume from."""
    values = tuple(_read(row, key.field) for key in sort.all_keys)
    return Cursor(values, str(_read(row, "_id")), user_id, sort.signature())


def _read(row: Any, path: str) -> Any:
    """`a.b.c` against a document or a mapping.

    Dotted, because a sort key may address a nested field - `score.total` is the
    one the matches feed uses - and Mongo's own sort takes the same notation.
    """
    if path == "_id":
        # Beanie exposes the `_id` alias as `id`; a raw mapping uses `_id`.
        if isinstance(row, dict):
            return row.get("_id", row.get("id"))
        return getattr(row, "id", None)
    current: Any = row
    for part in path.split("."):
        current = current.get(part) if isinstance(current, dict) else getattr(current, part, None)
        if current is None:
            return None
    return current


__all__ = [
    "CURSOR_VERSION",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "NEWEST_FIRST",
    "Cursor",
    "CursorError",
    "Findable",
    "Page",
    "PaginationRequest",
    "SortKey",
    "SortSpec",
    "clamp_limit",
    "cursor_for",
    "keyset_filter",
    "paginate",
]
