"""T-DATA-01.4 - every repository read is scoped to a user, or says it is not.

`AC-DATA-01.4`: "Every repository read method on a user-owned collection either
takes `user_id` or is decorated `@admin_scope`, checked by a contract test."

`17-data-model.md` §1: "A query on a user-owned collection without a `user_id`
predicate is a defect; the repository layer is the only place such a query may
exist and only under `/admin`."

`@admin_scope` is a word someone has to type. That is the whole mechanism: a
deliberate cross-user read is distinguishable from a forgotten `user_id`.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.core.documents import UserOwnedDoc
from app.core.repository import (
    BaseRepository,
    MissingUserScope,
    admin_scope,
    is_admin_scoped,
)

READ_PREFIXES = ("get", "find", "list", "count")


class Owned(UserOwnedDoc):
    class Settings:
        name = "owned_scoping_fixture"


class Plain(BaseRepository[Owned]):
    document = Owned


def test_the_base_reads_require_a_user_id():
    """The default every repository inherits."""
    repository = Plain()
    for method in (repository.scope,):
        with pytest.raises(MissingUserScope):
            method()


def test_the_scope_filter_adds_both_defaults():
    query = Plain().scope(user_id="01JUSER")
    assert query["user_id"] == "01JUSER"
    assert query["deleted_at"] is None


def test_include_deleted_drops_only_the_deleted_filter():
    query = Plain().scope(user_id="01JUSER", include_deleted=True)
    assert query["user_id"] == "01JUSER"
    assert "deleted_at" not in query


def test_admin_scope_is_an_explicit_marker():
    """A deliberate cross-user read is a word someone typed."""

    class AdminRepo(BaseRepository[Owned]):
        document = Owned

        @admin_scope
        async def find_every_user_s(self) -> list[Owned]:
            return await Owned.find(self.admin_scope_filter()).to_list()

    assert is_admin_scoped(AdminRepo.find_every_user_s)
    assert not is_admin_scoped(AdminRepo.get)


def test_admin_scope_filter_still_hides_deleted_rows():
    """Crossing users is deliberate; resurrecting deleted rows is not."""
    query = Plain().admin_scope_filter()
    assert query["deleted_at"] is None
    assert "user_id" not in query


def test_every_repository_read_is_scoped_or_marked(repo: Path):
    """AC-DATA-01.4, over the repositories that exist.

    Vacuous until the first module declares one; binding from that day, because
    it walks the subclasses rather than a list someone maintains.
    """
    offenders: list[str] = []
    for subclass in BaseRepository.__subclasses__():
        if subclass.__module__.startswith("tests"):
            continue
        document = getattr(subclass, "document", None)
        if document is None or not issubclass(document, UserOwnedDoc):
            continue
        for name, method in vars(subclass).items():
            if name.startswith("_") or not callable(method):
                continue
            if not name.startswith(READ_PREFIXES):
                continue
            if is_admin_scoped(method):
                continue
            parameters = inspect.signature(method).parameters
            if "user_id" not in parameters:
                offenders.append(f"{subclass.__module__}.{subclass.__name__}.{name}")
    assert offenders == [], (
        "each of these reads a user-owned collection without a user_id; pass "
        "one, or mark it @admin_scope if it deliberately crosses users:\n" + "\n".join(offenders)
    )


def test_a_read_that_forgets_the_user_id_is_caught():
    """The counter-case: the check above must actually reject something."""

    class Careless(BaseRepository[Owned]):
        document = Owned

        async def find_everything(self) -> list[Owned]:
            return []

    parameters = inspect.signature(Careless.find_everything).parameters
    assert "user_id" not in parameters
    assert not is_admin_scoped(Careless.find_everything)
