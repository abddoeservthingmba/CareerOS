"""The repository base - `DATA-01`.

`17-data-model.md` §1, the two rules a repository exists to make automatic:

* `AC-DATA-01.4`: "Every repository read method on a user-owned collection
  either takes `user_id` or is decorated `@admin_scope`."
* `AC-DATA-01.5`: "Every repository read filters `deleted_at: None` unless
  `include_deleted=True` is passed."

Both are the kind of rule that holds for six months and then does not. Putting
them in a base class means a new repository gets them by default and has to opt
out visibly - `@admin_scope` is a word someone has to type, and
`tests/spec/test_repo_user_scoping.py` reads it back.

`01-foundations.md` §5: "A repository method never contains a business rule.
'Active jobs for a user' is a repository method; 'should this user see this job'
is a service rule."
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from beanie import Document

from app.core.documents import UserOwnedDoc

ADMIN_SCOPE_ATTR = "__admin_scope__"


def admin_scope[F: Callable[..., Any]](method: F) -> F:
    """Mark a read that deliberately crosses users.

    `17-data-model.md` §1: such a query "may exist only under `/admin`", and
    `12-admin.md` §6 requires every individual-user read through admin to be
    audited. The marker is what lets `AC-DATA-01.4` tell a deliberate
    cross-tenant read from a forgotten `user_id`.
    """
    setattr(method, ADMIN_SCOPE_ATTR, True)
    return method


def is_admin_scoped(method: object) -> bool:
    return bool(getattr(method, ADMIN_SCOPE_ATTR, False))


class BaseRepository[D: Document]:
    """Queries for one collection. Hides every Mongo detail, index choices included."""

    document: type[D]

    def __init__(self, document: type[D] | None = None) -> None:
        if document is not None:
            self.document = document

    # -- filter construction -------------------------------------------------

    def scope(
        self,
        *,
        user_id: str | None = None,
        include_deleted: bool = False,
        **criteria: Any,
    ) -> dict[str, Any]:
        """Build a filter with the two defaults applied.

        `user_id` is required for a user-owned collection unless the caller is
        `@admin_scope`d, and `deleted_at: None` is added unless the caller asks
        for deleted rows explicitly.
        """
        query: dict[str, Any] = dict(criteria)
        owned = issubclass(self.document, UserOwnedDoc)

        if owned:
            if user_id is None:
                raise MissingUserScope(self.document.__name__)
            query["user_id"] = user_id
            if not include_deleted:
                query["deleted_at"] = None
        return query

    def admin_scope_filter(
        self, *, include_deleted: bool = False, **criteria: Any
    ) -> dict[str, Any]:
        """The same, for a deliberate cross-user read under `/admin`."""
        query: dict[str, Any] = dict(criteria)
        if issubclass(self.document, UserOwnedDoc) and not include_deleted:
            query["deleted_at"] = None
        return query

    # -- reads ---------------------------------------------------------------

    async def get(
        self, document_id: str, *, user_id: str | None = None, include_deleted: bool = False
    ) -> D | None:
        """One document, or `None`.

        Ownership failures are the caller's to turn into a 404 rather than a
        403 (`02-auth-and-account.md` §6); this returns `None` either way, so
        "not yours" and "does not exist" are the same answer here too.
        """
        query = self.scope(user_id=user_id, include_deleted=include_deleted, _id=document_id)
        return await self.document.find_one(query)

    async def find(
        self,
        *,
        user_id: str | None = None,
        include_deleted: bool = False,
        limit: int | None = None,
        sort: Any = None,
        **criteria: Any,
    ) -> list[D]:
        query = self.scope(user_id=user_id, include_deleted=include_deleted, **criteria)
        cursor = self.document.find(query)
        if sort is not None:
            cursor = cursor.sort(sort)
        if limit is not None:
            cursor = cursor.limit(limit)
        return await cursor.to_list()

    async def count(
        self, *, user_id: str | None = None, include_deleted: bool = False, **criteria: Any
    ) -> int:
        query = self.scope(user_id=user_id, include_deleted=include_deleted, **criteria)
        return await self.document.find(query).count()

    # -- writes --------------------------------------------------------------

    async def insert(self, document: D) -> D:
        return await document.insert()

    async def soft_delete(self, document_id: str, *, user_id: str) -> bool:
        """`17-data-model.md` §1 - deletion is `deleted_at`, not a removal."""
        found = await self.get(document_id, user_id=user_id)
        if found is None:
            return False
        if not isinstance(found, UserOwnedDoc):
            raise TypeError(f"{self.document.__name__} is not user-owned")
        found.mark_deleted()
        await found.save()
        return True


class MissingUserScope(ValueError):
    """A read on a user-owned collection was built without a `user_id`.

    `AC-DATA-01.4`. If the read is deliberately cross-user, decorate it
    `@admin_scope` and use `admin_scope_filter`, which is a visible act rather
    than an omission.
    """

    def __init__(self, document: str) -> None:
        super().__init__(
            f"{document} is user-owned: pass user_id, or mark the method "
            "@admin_scope and use admin_scope_filter (AC-DATA-01.4)"
        )


def read_methods(repository: type[BaseRepository[Any]]) -> Mapping[str, Callable[..., Any]]:
    """The public read methods a scoping check should inspect."""
    return {
        name: getattr(repository, name)
        for name in dir(repository)
        if not name.startswith("_")
        and callable(getattr(repository, name, None))
        and name in {"get", "find", "count"} | _extra_reads(repository)
    }


def _extra_reads(repository: type[BaseRepository[Any]]) -> set[str]:
    return {
        name
        for name, value in vars(repository).items()
        if not name.startswith("_")
        and callable(value)
        and (name.startswith(("get_", "find_", "list_", "count_")) or is_admin_scoped(value))
    }


__all__ = [
    "ADMIN_SCOPE_ATTR",
    "BaseRepository",
    "MissingUserScope",
    "admin_scope",
    "is_admin_scoped",
    "read_methods",
]
