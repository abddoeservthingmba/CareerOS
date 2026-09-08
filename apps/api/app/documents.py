"""Every Beanie document in the product - `DATA-02`.

`17-data-model.md` §2 declares the collections and names an owner module for
each. This is the one place that enumerates them, because three things need the
same list and none of them can build it:

* `init_beanie` needs every document class, or a query against an unregistered
  collection fails at the first request rather than at boot.
* `app.main` and `app.worker` both need it, and they are peers - neither may
  import the other (ADR-002), so the list cannot live in either.
* `AC-DATA-02.1`'s schema snapshot and `AC-DATA-02.2`'s ownership check compare
  against it, and a check that discovered documents by walking the filesystem
  would pass over a document that was never registered - which is exactly the
  document that breaks in production.

**Why here and not in `app/infra/` or `app/modules/__init__.py`.** Contract 7
(`infra-is-dumb`) forbids `app.infra -> app.modules`, correctly: the Mongo
client should not know what a résumé is. And an `app/modules/__init__.py` that
imported all nine modules would mean any module importing a sibling's public
surface transitively imports every module, which is both a cycle waiting to
happen and the end of contract 2. So `app.documents` is its own layer, above
`app.modules` and below the entrypoints - which also means no module can import
it back.

**Ownership is exclusive** (§2's constraint): "only the owning module's
repository writes to a collection. Another module reads it through the owner's
public service, never directly." This file records that mapping; the static
check in `tests/spec/test_collection_ownership.py` enforces it.
"""

from __future__ import annotations

from beanie import Document

from app.ai.usage import AiUsage
from app.core.tasks import FailedTask
from app.modules.admin import models as admin_models
from app.modules.apply import models as apply_models
from app.modules.auth import models as auth_models
from app.modules.jobs import models as jobs_models
from app.modules.matching import models as matching_models
from app.modules.notifications import models as notifications_models
from app.modules.profile import models as profile_models
from app.modules.resume import models as resume_models
from app.modules.tracker import models as tracker_models

#: Owner name -> the documents that owner writes. The owner names are §2's
#: `Owner` column exactly, including the two that are not `modules/` packages:
#: `ai` owns `ai_usage` (`app/ai/usage.py`) and `core` owns `failed_tasks`
#: (`app/core/tasks.py`). §2 calls those "the two infrastructure collections" -
#: they have no user-facing feature, so giving either one a module would create
#: eight empty files to hold one document.
OWNERS: dict[str, tuple[type[Document], ...]] = {
    "auth": auth_models.DOCUMENTS,
    "resume": resume_models.DOCUMENTS,
    "profile": profile_models.DOCUMENTS,
    "jobs": jobs_models.DOCUMENTS,
    "matching": matching_models.DOCUMENTS,
    "apply": apply_models.DOCUMENTS,
    "tracker": tracker_models.DOCUMENTS,
    "notifications": notifications_models.DOCUMENTS,
    "admin": admin_models.DOCUMENTS,
    "ai": (AiUsage,),
    "core": (FailedTask,),
}

#: `01-foundations.md` §15's `absent` state, stated rather than left implicit.
#:
#: Three collections in §2's table are marked R2, and `CLAUDE.md` builds the R1
#: track only. They are named here so "where is `devices`?" has an answer in
#: the code as well as in the specification, and so the schema-snapshot test
#: can assert that the R1 set is exactly the R1 rows of §2's table - not merely
#: "some subset of them", which would pass if a collection were dropped by
#: accident.
ABSENT_UNTIL_R2 = ("devices", "profile_audit", "saved_searches")


def all_documents() -> tuple[type[Document], ...]:
    """Every document, in a stable order, for `init_beanie`.

    Ordered by owner then by declaration so the argument to `init_beanie` is
    reproducible - which matters only for legible diffs and error messages, but
    those are the things that matter at four in the morning.
    """
    return tuple(document for documents in OWNERS.values() for document in documents)


def collection_names() -> tuple[str, ...]:
    """The collection each document writes to, sorted."""
    return tuple(sorted(collection_name(document) for document in all_documents()))


def collection_name(document: type[Document]) -> str:
    """The Mongo collection a document class writes to.

    Read from `Settings.name` rather than derived from the class name, because
    §2 names the collections and several do not match their class
    (`AnswerBankEntry` -> `answer_bank`, `AuditEntry` -> `audit_log`). A
    document with no `Settings.name` would silently get Beanie's default, which
    is the class name - a collection §2 never declared.
    """
    settings = getattr(document, "Settings", None)
    name = getattr(settings, "name", None)
    if not name:
        raise ValueError(
            f"{document.__name__} declares no Settings.name, so Beanie would use "
            f"'{document.__name__}' as its collection - a name 17-data-model.md "
            "§2 does not declare"
        )
    return str(name)


def owner_of(collection: str) -> str:
    """Which module owns a collection. Raises for an unknown one."""
    for owner, documents in OWNERS.items():
        if any(collection_name(document) == collection for document in documents):
            return owner
    raise KeyError(f"no module owns {collection!r}")


__all__ = [
    "ABSENT_UNTIL_R2",
    "OWNERS",
    "all_documents",
    "collection_name",
    "collection_names",
    "owner_of",
]
