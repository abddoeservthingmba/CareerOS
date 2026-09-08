"""Queries for the apply module.

Hides every Mongo detail, including index choices. A repository method never
contains a business rule: "active jobs for a user" belongs here, "should this
user see this job" belongs in `service.py`.

`AuditRepository` is the only thing here in P0, because `AC-DATA-02.4` is a
statement about a repository's *surface* and a surface cannot be asserted
against a file that does not exist. The pack and answer-bank repositories arrive
with `APPLY-01`..`APPLY-07` in phase P4.
"""

from __future__ import annotations

from app.modules.apply.models import AuditEntry, AuditKind


class AuditRepository:
    """`audit_log` - append-only. `AC-DATA-02.4`.

    **This deliberately does not inherit `BaseRepository`.** That is the whole
    control, and it is the opposite of the usual advice.

    `BaseRepository` provides `insert`, `get`, `find`, `count`, `soft_delete`
    and `admin_scope_filter`, and every other collection wants all of them.
    Inheriting here would put `soft_delete` on the one collection that must not
    have a deletion path - and it would arrive silently, as a consequence of a
    base class, with nobody having decided it. `AC-DATA-02.4` says the
    repository "exposes only `append` and `find`", and the only way to make
    that true of a class is not to inherit the rest.

    What is lost by not inheriting: the automatic `deleted_at: None` filter and
    the `user_id` scoping helper. Neither applies. `AuditEntry` is a `BaseDoc`
    with no `deleted_at` (a retired audit row is a deletion with a friendlier
    name), and its `user_id` is nullable because an `admin_action` row has an
    actor without necessarily having a subject.

    Why it matters at all: an audit log is read precisely when what it says is
    contested - a pack the user says they never approved, a consent they say
    they never gave. A log the application can rewrite answers only "here is
    what the application currently says", which the rest of the database
    already answers and which is worth nothing as evidence.

    The second half of `AC-DATA-02.4` is the Atlas role, which has no `update`
    or `remove` privilege on this collection. That covers the paths this class
    cannot - a migration script, an aggregation `$merge`, a hand edit in the
    Atlas data browser. It is a manual control; see
    `docs/runbooks/atlas-roles.md`.
    """

    document = AuditEntry

    async def append(self, entry: AuditEntry) -> AuditEntry:
        """The only write. No update, no upsert, no delete.

        Not idempotent, and it must not be: two approvals of two packs are two
        events, and collapsing them on a natural key would lose the second -
        which is the one someone is asking about.
        """
        await entry.insert()
        return entry

    async def find(
        self, *, user_id: str | None = None, kind: AuditKind | None = None, limit: int = 100
    ) -> list[AuditEntry]:
        """The only read.

        `user_id` is optional rather than required because a compliance query
        over one `kind` across all users is a legitimate use (`12-admin.md` §2)
        and `audit_log` is not a user-owned collection - so `AC-DATA-01.4`'s
        scoping rule does not apply to it. Both filters are still accepted so
        the common case, one user's timeline, is an indexed query.
        """
        criteria: dict[str, object] = {}
        if user_id is not None:
            criteria["user_id"] = user_id
        if kind is not None:
            criteria["kind"] = kind
        return await AuditEntry.find(criteria).limit(limit).to_list()


__all__ = ["AuditRepository"]
