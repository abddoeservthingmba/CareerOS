"""Beanie documents for the notifications module - persistence only.

`17-data-model.md` §2.11: `reminders`, `notifications`. (`devices` is R2 and
therefore absent - `01-foundations.md` §15.)

Two fields on `reminders` carry the whole design, and both look like
optimisations until you see what they prevent:

**`dedup_key` is unique, and it is the entire idempotency mechanism**
(`NOTIF-05`). §2.11: "It embeds the occurrence, so rescheduling after a status
change produces a genuinely different key rather than silently colliding." The
failure it prevents is the one users notice most: the same follow-up email
arriving four times because a retry, a cron overlap and a status change each
scheduled it. A key of `follow_up:{application_id}` alone would collide the
other way - a genuinely rescheduled reminder would be swallowed as a duplicate
and never sent.

**`payload` denormalizes the few strings the message needs.** §2.11: "so
dispatch does not join to `jobs` for 200 reminders in a batch, and so a message
about a since-deleted job still renders." The second reason is the important
one. A reminder is written days before it is sent; by then the listing may be
expired, merged or gone, and a dispatch that joined would either send a message
with holes in it or fail. Denormalizing means the message says what it said when
it was scheduled, which is also what the user expects.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.core.documents import UserOwnedDoc
from app.shared.timeutils import ensure_utc


class ReminderType(StrEnum):
    """`reminders.type` (§7's registry, §2.11).

    Each member is a different promise about timing, which is why they are not
    one `CUSTOM` type with a lead time: `INTERVIEW_1H` must not be sent at all
    if it is already late, while `FOLLOW_UP` is still useful a day out.
    """

    FOLLOW_UP = "follow_up"
    INTERVIEW_24H = "interview_24h"
    INTERVIEW_1H = "interview_1h"
    DEADLINE_48H = "deadline_48h"
    CUSTOM = "custom"


class ReminderStatus(StrEnum):
    """`reminders.status` (§2.11).

    `SENDING` is a real state and not a transient one to skip: without it, a
    dispatcher that crashes mid-batch cannot tell what it had already picked up,
    and the safe assumption in either direction is wrong - retry sends twice,
    skip sends nothing.
    """

    SCHEDULED = "scheduled"
    SENDING = "sending"
    SENT = "sent"
    CANCELLED = "cancelled"
    FAILED = "failed"


class NotificationKind(StrEnum):
    """`notifications.kind` (§2.11) - what the inbox row is about."""

    REMINDER = "reminder"
    MATCH = "match"
    RESUME = "resume"
    SYSTEM = "system"


class Channel(StrEnum):
    """A delivery channel. `PUSH` is R2 (`devices` does not exist in R1)."""

    EMAIL = "email"
    IN_APP = "in_app"
    PUSH = "push"


class CancelledReason(StrEnum):
    """Why a scheduled reminder will not be sent (§2.11).

    Recorded because "the reminder never arrived" has several innocent
    explanations and one bug, and they must be distinguishable after the fact.
    """

    STATUS_CHANGED = "status_changed"
    APPLICATION_DELETED = "application_deleted"
    USER_CANCELLED = "user_cancelled"
    SUPERSEDED = "superseded"
    QUIET_HOURS = "quiet_hours"


class Reminder(UserOwnedDoc):
    """`reminders` - scheduled reminder occurrences (§2.11).

    An *occurrence*, not a rule: one row per thing that will be sent at one
    time. A recurring rule expanded lazily would make "what is due in the next
    hour" a computation over every application instead of an indexed range
    query, and `NOTIF-05`'s idempotency would have nothing to key on.
    """

    application_id: str
    type: ReminderType = ReminderType.CUSTOM
    #: UTC, always (HR-10). The user's local time and quiet hours are applied
    #: when this is computed, never when it is read.
    due_at: datetime
    channels: list[Channel] = Field(default_factory=lambda: [Channel.EMAIL, Channel.IN_APP])
    status: ReminderStatus = ReminderStatus.SCHEDULED

    #: Unique. `<type>:<application_id>:<occurrence>` - the occurrence is what
    #: makes a genuine reschedule a different key.
    dedup_key: str

    sent_at: datetime | None = None
    attempts: int = 0
    cancelled_reason: CancelledReason | None = None

    #: The strings the message needs, copied at schedule time.
    payload: dict[str, str] = Field(default_factory=dict)

    @field_validator("due_at", "sent_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    class Settings:
        name = "reminders"
        validate_on_save = True
        indexes = [
            # Unique. `NOTIF-05`'s entire idempotency mechanism: the second
            # attempt to schedule the same occurrence is a duplicate-key error,
            # not a second email.
            IndexModel([("dedup_key", ASCENDING)], name="dedup_key", unique=True),
            # ADR-012: a system-scan index. The dispatch scan asks "what is due
            # now, for everybody" - that is the whole job, and leading with
            # `user_id` would make it O(users) per minute, growing with signups,
            # forever.
            IndexModel([("status", ASCENDING), ("due_at", ASCENDING)], name="dispatch_scan"),
        ]


class Notification(UserOwnedDoc):
    """`notifications` - the in-app inbox (§2.11).

    `read_at` rather than a `read` boolean: "when did they see this" is
    answerable and a boolean's answer is lost. The unread badge indexes on
    `read_at: null`, so the nullable timestamp is also the cheaper query.
    """

    title: str
    body: str = ""
    #: `app://applications/<id>`. A deep link, so an inbox row is actionable in
    #: both clients from one stored value.
    deep_link: str | None = None
    kind: NotificationKind = NotificationKind.SYSTEM
    read_at: datetime | None = None

    @field_validator("read_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    class Settings:
        name = "notifications"
        validate_on_save = True
        indexes = [
            IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="inbox"),
            # Partial on `read_at: null`: the unread badge is read on every page
            # load and matches a handful of rows, so the index stays small even
            # for a user with a year of history.
            IndexModel(
                [("user_id", ASCENDING), ("read_at", ASCENDING)],
                name="unread",
                partialFilterExpression={"read_at": None},
            ),
        ]


DOCUMENTS = (Reminder, Notification)
