"""Events the auth module publishes - `01-foundations.md` §9.

§9: "An event is a frozen Pydantic model in the publishing module's
`events.py`, named in the past tense, carrying **IDs and primitives only** - no
documents, no nested aggregates."

Both of these have **no consumer in R1**, and are declared anyway. §9's table
gained them with `AUTH-01`: it had listed neither while
`02-auth-and-account.md` §8 named auth as their publisher and `AUTH-01`'s
Outputs required `UserRegistered`, so `EventBus.publish` rejected a name the
specification demanded and registration could not be built. The reaction graph
is meant to be readable in one file, which means a leaf is worth stating.

Neither carries an email address. A handler that needs one reads the user
document - that is §9's "ids and primitives" rule, and here it is also
`FOUND-14`'s: events are passed to every subscriber and logged on failure, and
an address in the payload is an address in the log.
"""

from __future__ import annotations

from app.core.events import Event


class UserRegistered(Event):
    """A new account exists and has not verified its address yet.

    Published for a *new* registration only. §1's enumeration rule means a
    registration attempt against an existing address answers identically to a
    fresh one - but it creates no user, so there is nothing to announce, and
    publishing here would leak the collision to any future subscriber.
    """

    name = "UserRegistered"

    user_id: str


class UserDeletionRequested(Event):
    """The user asked to be deleted. `AUTH-07` does the deleting.

    A notification, never the mechanism. The purge is a cron that scans
    `users.status` and `deletion_requested_at`, because a deletion depending on
    an in-process handler would be lost on a restart between the request and
    the sweep - and a deletion request that quietly did not happen is the worst
    failure in this module.
    """

    name = "UserDeletionRequested"

    user_id: str
    #: ISO-8601 UTC. A string rather than a `datetime` because §9 allows
    #: primitives only, and the handler that needs the instant re-reads the
    #: document anyway.
    requested_at: str


__all__ = ["UserDeletionRequested", "UserRegistered"]
