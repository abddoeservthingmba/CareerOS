"""Object keys - `DATA-04`.

`17-data-model.md` §4: "Every stored file addressable from a user prefix so that
deletion is a prefix sweep, and no object key contains anything a person
supplied."

Two properties, and they are not the same property:

**Every key sits under `u/{user_id}/`.** That is what makes `AUTH-07`'s deletion
a prefix sweep rather than a join. A key organised by kind - `resumes/{id}` -
would mean deleting a user requires knowing every object they own, which means
a database read, which means a deletion that is only as complete as the
database's own record of what was uploaded. A prefix sweep is complete by
construction and verifiable by re-listing.

**A key contains only ULIDs and fixed literals.** `AC-DATA-04.1`: "No object key
in any environment matches a pattern containing a character outside
`[A-Za-z0-9/_.-]` or contains a user-supplied substring." The user's filename
lives in Mongo as `documents[].name` and appears only in the
`Content-Disposition` of a presigned download, sanitized.

Three things a user-supplied filename does to an object key, none of which is
theoretical:

* `../` traverses out of the prefix, so the object lands somewhere the deletion
  sweep will never look - and stays after the account is deleted;
* a name is PII often enough to matter (`Priya Sharma CV Nov 2026.pdf`) and an
  object key ends up in access logs, in error messages, and in the URL a user
  copies into a support ticket;
* a `%`, a newline or a non-ASCII character makes the key's own signature
  ambiguous, so a presigned URL either fails or signs something other than what
  was meant.

This module builds keys and refuses everything else. It lives in `shared`
because both the storage adapter and the deletion sweep need it, and it imports
nothing: the rules are pure string rules, so they are checkable without a
bucket.
"""

from __future__ import annotations

import re
from enum import StrEnum

#: `AC-DATA-04.1`'s character class, exactly.
ALLOWED_CHARACTERS = re.compile(r"^[A-Za-z0-9/_.-]+$")

#: A ULID as `01-foundations.md` §3 defines it: 26 characters of Crockford
#: base32. Matched rather than merely length-checked, so a 26-character
#: filename cannot pass for an id.
ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")

#: Extensions R1 accepts. A fixed set, because the extension is part of the key
#: and therefore has to come from us rather than from the upload.
ALLOWED_EXTENSIONS = frozenset({"pdf", "docx", "txt", "zip", "gz", "archive"})

#: The user prefix. Every user-owned object is under it, and `AUTH-07` deletes
#: it wholesale.
USER_PREFIX = "u"

#: §4: "ops only, not under `u/`". Deliberately outside the user prefix - a
#: backup under `u/{user_id}/` would be deleted by that user's account deletion,
#: which is the opposite of what a backup is for.
BACKUP_PREFIX = "backups"

#: §4's lifecycle rule.
NONCURRENT_VERSION_DAYS = 30

#: §4: "Every read is a presigned GET with a 5-minute TTL".
PRESIGNED_TTL_SECONDS = 300


class KeyRejected(ValueError):
    """A key was asked for that would violate §4.

    Its own type because the two callers want different behaviour: the storage
    adapter turns it into a 400, and the audit in `test_key_audit.py` turns it
    into a listed offender.
    """


class Area(StrEnum):
    """The fixed literals §4's layout allows between the user and the object.

    An enum rather than a string parameter, because this is the one position in
    a key where a caller could pass something arbitrary and the result would
    still look like a valid key.
    """

    RESUMES = "resumes"
    APPLICATIONS = "applications"
    EXPORTS = "exports"


def _check_id(value: str, what: str) -> str:
    if not ULID.match(value):
        raise KeyRejected(
            f"{what} {value!r} is not a ULID. §4 allows only ULIDs and fixed "
            "literals in a key: anything a person supplied can traverse out of "
            "the prefix, carry their name into an access log, or make the key's "
            "own signature ambiguous."
        )
    return value


def _check_extension(value: str) -> str:
    extension = value.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise KeyRejected(
            f"extension {value!r} is not one of {sorted(ALLOWED_EXTENSIONS)}. The "
            "extension is part of the key, so it comes from us and never from "
            "the upload - a client that claims `.pdf` is checked against magic "
            "bytes (`AC-DATA-04.4`), and the key records what we decided."
        )
    return extension


def user_prefix(user_id: str) -> str:
    """`u/{user_id}/` - what `AUTH-07` deletes.

    Trailing slash included, and that is not cosmetic: `u/01ABC` is a prefix of
    `u/01ABCD...`, so a sweep without the slash would delete another user's
    objects whose id happens to start with the same characters. ULIDs are
    lexicographically ordered by time, so ids created in the same millisecond
    share a long prefix - this is a collision that gets *more* likely under
    load, not less.
    """
    return f"{USER_PREFIX}/{_check_id(user_id, 'user_id')}/"


def resume_key(user_id: str, resume_id: str, extension: str) -> str:
    """`u/{user_id}/resumes/{resume_id}.{ext}`."""
    return (
        f"{user_prefix(user_id)}{Area.RESUMES.value}/"
        f"{_check_id(resume_id, 'resume_id')}.{_check_extension(extension)}"
    )


def resume_text_key(user_id: str, resume_id: str) -> str:
    """`u/{user_id}/resumes/{resume_id}.txt` - the extracted text.

    §2.4: the text lives here rather than in Mongo, because a 5 MB résumé's text
    can approach Mongo's 16 MB document ceiling once paired with the extraction,
    and Atlas M0 is 512 MB total.
    """
    return resume_key(user_id, resume_id, "txt")


def application_document_key(
    user_id: str, application_id: str, document_id: str, extension: str
) -> str:
    """`u/{user_id}/applications/{application_id}/{document_id}.{ext}`."""
    return (
        f"{user_prefix(user_id)}{Area.APPLICATIONS.value}/"
        f"{_check_id(application_id, 'application_id')}/"
        f"{_check_id(document_id, 'document_id')}.{_check_extension(extension)}"
    )


def export_key(user_id: str, export_id: str) -> str:
    """`u/{user_id}/exports/{export_id}.zip` - R2 track (`SEC-05`)."""
    return f"{user_prefix(user_id)}{Area.EXPORTS.value}/{_check_id(export_id, 'export_id')}.zip"


def backup_key(day: str) -> str:
    """`backups/{YYYY-MM-DD}/dump.archive.gz` - ops only, not under `u/`."""
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        raise KeyRejected(f"backup day {day!r} is not YYYY-MM-DD")
    return f"{BACKUP_PREFIX}/{day}/dump.archive.gz"


# -- checking a key that already exists ---------------------------------------


def is_valid(key: str) -> bool:
    """Whether `key` is one this module could have produced.

    Used by `test_key_audit.py` to audit a live bucket. Deliberately a
    whole-shape check rather than a character check: a key of
    `u/x/resumes/y.pdf` passes the character class and is not a key this
    product creates.
    """
    return _reason(key) is None


def rejection_reason(key: str) -> str | None:
    """Why `key` is invalid, or `None`. The audit reports this per object."""
    return _reason(key)


def _reason(key: str) -> str | None:
    if not key or not ALLOWED_CHARACTERS.match(key):
        return "contains a character outside [A-Za-z0-9/_.-]"
    # Checked explicitly as well as by the character class: `.` and `-` are both
    # allowed characters, so `..` passes the class. Traversal is the failure
    # that puts an object outside the sweep, so it gets its own answer.
    if ".." in key or key.startswith("/") or "//" in key:
        return "traverses or is not a normalised path"

    parts = key.split("/")
    if parts[0] == BACKUP_PREFIX:
        return (
            None
            if len(parts) == 3
            and re.match(r"^\d{4}-\d{2}-\d{2}$", parts[1])
            and parts[2] == "dump.archive.gz"
            else "is under backups/ but is not backups/{YYYY-MM-DD}/dump.archive.gz"
        )
    if parts[0] != USER_PREFIX:
        return f"is not under {USER_PREFIX}/ or {BACKUP_PREFIX}/"
    if len(parts) < 4 or not ULID.match(parts[1]):
        return "does not begin u/{user_id}/ with a ULID user id"

    area = parts[2]
    if area not in {member.value for member in Area}:
        return f"names area {area!r}, which is not one of {sorted(m.value for m in Area)}"

    if area == Area.APPLICATIONS.value:
        if len(parts) != 5:
            return "an application document is u/{uid}/applications/{aid}/{did}.{ext}"
        if not ULID.match(parts[3]):
            return "the application id is not a ULID"
        return _check_leaf(parts[4])

    if len(parts) != 4:
        return f"a {area} object is u/{{uid}}/{area}/{{id}}.{{ext}}"
    return _check_leaf(parts[3])


def _check_leaf(leaf: str) -> str | None:
    stem, _, extension = leaf.rpartition(".")
    if not stem or not extension:
        return f"{leaf!r} has no extension"
    if not ULID.match(stem):
        return f"{stem!r} is not a ULID - a filename has reached the key"
    if extension.lower() not in ALLOWED_EXTENSIONS:
        return f"extension {extension!r} is not allowed"
    return None


def owner_of(key: str) -> str | None:
    """The `user_id` a key belongs to, or `None` for a non-user key.

    Used by the ownership check before signing (`AC-DATA-04.2`). Parsed from the
    key rather than passed alongside it: a signer that trusted a caller's claim
    about whose object it was would be an ownership check in name only.
    """
    if not is_valid(key):
        return None
    parts = key.split("/")
    return parts[1] if parts[0] == USER_PREFIX else None


__all__ = [
    "ALLOWED_CHARACTERS",
    "ALLOWED_EXTENSIONS",
    "BACKUP_PREFIX",
    "NONCURRENT_VERSION_DAYS",
    "PRESIGNED_TTL_SECONDS",
    "ULID",
    "USER_PREFIX",
    "Area",
    "KeyRejected",
    "application_document_key",
    "backup_key",
    "export_key",
    "is_valid",
    "owner_of",
    "rejection_reason",
    "resume_key",
    "resume_text_key",
    "user_prefix",
]
