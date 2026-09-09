"""Queries for the auth module - `01-foundations.md` §5.

Every Mongo detail lives here, index choices included. A service method never
builds a filter.

`users` is not a user-owned collection - it *is* the user - so `UserRepository`
does not go through `BaseRepository.scope`'s `user_id` requirement.

Only what `AUTH-01` needs. Token *redemption* (`active_by_hash`, invalidating
outstanding tokens) belongs to `AUTH-04`'s verify and reset flows and is not
written here: `CLAUDE.md` - "no product code has been written ahead of its
phase", and a query with no caller is a query no test covers.
"""

from __future__ import annotations

from pymongo.errors import DuplicateKeyError

from app.core.repository import BaseRepository
from app.modules.auth.models import EmailToken, User


class EmailAlreadyRegistered(Exception):
    """The unique `email_normalized` index refused the insert.

    Defined here and raised here so the service never has to know what a
    `DuplicateKeyError` is - contract 8 (`no-http-in-domain`) forbids a service
    importing `pymongo`, and the reason behind the rule is that "this address is
    taken" is a domain fact while "error code 11000" is a storage detail.
    """


class UserRepository(BaseRepository[User]):
    """`users` (§2.1)."""

    document = User

    async def by_normalized_email(self, email_normalized: str) -> User | None:
        """The registration-collision and login lookup.

        Hits the unique `email_normalized` index. Deleted users are *included*
        deliberately: a soft-deleted account still holds its address until
        `AUTH-07`'s purge completes, and letting someone re-register it in the
        meantime would resurrect a pending deletion as a live account.
        """
        return await User.find_one(User.email_normalized == email_normalized)

    async def insert(self, user: User) -> User:
        """Create the account, or raise `EmailAlreadyRegistered`.

        The service checks for a collision first, for §1's enumeration
        behaviour - but this can still lose a race, because two concurrent
        registrations for one address both pass that check. The unique index is
        the real guarantee, and the translation happens here so the service
        handles a domain condition rather than a driver's error code.
        """
        try:
            return await user.insert()
        except DuplicateKeyError as exc:
            raise EmailAlreadyRegistered(user.email_normalized) from exc


class EmailTokenRepository(BaseRepository[EmailToken]):
    """`email_tokens` (§2.3)."""

    document = EmailToken

    async def insert(self, token: EmailToken) -> EmailToken:
        return await token.insert()


__all__ = ["EmailAlreadyRegistered", "EmailTokenRepository", "UserRepository"]
