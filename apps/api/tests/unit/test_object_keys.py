"""T-DATA-04.1 - no object key carries anything a person supplied.

`AC-DATA-04.1`: "No object key in any environment matches a pattern containing a
character outside `[A-Za-z0-9/_.-]` or contains a user-supplied substring."

`17-data-model.md` §4: "Keys contain **only ULIDs and fixed literals**. The
user's filename is stored in Mongo as `documents[].name` and used only in the
`Content-Disposition` of a presigned download, sanitized."

This is the half that can be asserted without a bucket, and it is the half that
matters most, because a key is decided before anything is written. The live
audit is `tests/integration/test_key_audit.py`, which lists the bucket.

**What a user-supplied filename does to a key**, since the criterion states the
rule without the reasons and the rule is the sort that gets relaxed:

* `../` traverses out of `u/{user_id}/`, so the object lands where the deletion
  sweep will never look - and stays after the account is deleted, which is the
  one outcome `AUTH-07` exists to prevent;
* a filename is PII often enough to matter (`Priya Sharma CV Nov 2026.pdf`), and
  an object key reaches access logs, error messages, and the URL a user pastes
  into a support ticket;
* a `%`, a newline or a non-ASCII character makes the key's own signature
  ambiguous, so a presigned URL either fails or signs something other than what
  was meant.

The trailing slash on `user_prefix` gets its own test for a reason worth reading
in full: ULIDs are lexicographically ordered by time, so two ids created in the
same millisecond share a long prefix. A sweep of `u/01ABC` without the slash
would delete objects belonging to `u/01ABCD...` - and that collision gets *more*
likely under load, not less.
"""

from __future__ import annotations

import pytest

from app.shared import object_keys as keys
from app.shared.object_keys import Area, KeyRejected

USER = "01JBQ8Z3F7KX2M4N6P8R0S2T4V"
RESUME = "01JBQ8Z3F7KX2M4N6P8R0S2T4W"
APPLICATION = "01JBQ8Z3F7KX2M4N6P8R0S2T4X"
DOCUMENT = "01JBQ8Z3F7KX2M4N6P8R0S2T4Y"

#: §4's layout, transcribed. Every builder is checked against the literal
#: pattern rather than against another call to itself.
LAYOUT = {
    "resume": f"u/{USER}/resumes/{RESUME}.pdf",
    "resume_text": f"u/{USER}/resumes/{RESUME}.txt",
    "application_document": f"u/{USER}/applications/{APPLICATION}/{DOCUMENT}.pdf",
    "export": f"u/{USER}/exports/{RESUME}.zip",
    "backup": "backups/2026-09-08/dump.archive.gz",
}


# -- the layout ---------------------------------------------------------------


def test_the_resume_key_matches_the_spec():
    assert keys.resume_key(USER, RESUME, "pdf") == LAYOUT["resume"]


def test_the_extracted_text_key_matches_the_spec():
    """§2.4: the text lives in the object store, not in Mongo - a 5 MB résumé's
    text can approach Mongo's 16 MB ceiling once paired with the extraction."""
    assert keys.resume_text_key(USER, RESUME) == LAYOUT["resume_text"]


def test_the_application_document_key_matches_the_spec():
    assert (
        keys.application_document_key(USER, APPLICATION, DOCUMENT, "pdf")
        == LAYOUT["application_document"]
    )


def test_the_export_key_matches_the_spec():
    assert keys.export_key(USER, RESUME) == LAYOUT["export"]


def test_the_backup_key_is_not_under_the_user_prefix():
    """§4: "ops only, not under `u/`".

    Deliberate, and the reason is the deletion sweep: a backup under
    `u/{user_id}/` would be deleted by that user's account deletion, which is
    the opposite of what a backup is for.
    """
    assert keys.backup_key("2026-09-08") == LAYOUT["backup"]
    assert not keys.backup_key("2026-09-08").startswith("u/")


@pytest.mark.parametrize("name", sorted(LAYOUT))
def test_every_key_the_layout_declares_is_valid(name: str):
    """The builders and the validator agree.

    Two implementations of one rule is how they come to disagree; asserting
    they do not is cheaper than merging them, because the builder has to
    construct and the validator has to parse.
    """
    assert keys.is_valid(LAYOUT[name]), keys.rejection_reason(LAYOUT[name])


# -- the character class ------------------------------------------------------


def test_the_character_class_is_the_one_the_criterion_names():
    """`AC-DATA-04.1` gives it literally, so it is transcribed literally."""
    assert keys.ALLOWED_CHARACTERS.pattern == r"^[A-Za-z0-9/_.-]+$"


@pytest.mark.parametrize(
    "filename",
    [
        "Priya Sharma CV.pdf",
        "résumé.pdf",
        "cv(final).pdf",
        "cv%20final.pdf",
        "cv\nname.pdf",
        "cv;rm -rf.pdf",
        "北京.pdf",
    ],
)
def test_a_user_filename_can_never_become_a_key(filename: str):
    """The criterion's second clause: "or contains a user-supplied substring".

    Not one of these is refused by the character class alone - `cv-final.pdf`
    would pass it - so the refusal is on *shape*: a key's leaf is a ULID, and a
    filename is not.
    """
    with pytest.raises(KeyRejected):
        keys.resume_key(USER, filename, "pdf")


@pytest.mark.parametrize(
    "attempt",
    [
        "../../etc/passwd",
        "..",
        "01JBQ8Z3F7KX2M4N6P8R0S2T4W/../../other",
        "/absolute",
    ],
)
def test_traversal_is_refused(attempt: str):
    """The one that actually loses data.

    An object outside `u/{user_id}/` is invisible to the deletion sweep, so it
    survives the account deletion that was supposed to remove it - and nothing
    reports that, because the sweep verifies by re-listing the prefix it swept.
    """
    with pytest.raises(KeyRejected):
        keys.resume_key(USER, attempt, "pdf")


def test_a_traversing_key_is_invalid_even_though_its_characters_are_allowed():
    """`.` and `-` are both in the character class, so `..` passes it.

    Worth its own test: a validator written as "does it match the character
    class" would accept `u/{uid}/resumes/../../x.pdf`, and the criterion's
    character clause would be satisfied while its purpose was not.
    """
    traversing = f"u/{USER}/resumes/../../x.pdf"

    assert keys.ALLOWED_CHARACTERS.match(traversing)
    assert not keys.is_valid(traversing)
    assert "traverses" in (keys.rejection_reason(traversing) or "")


# -- ids ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id",
    [
        "",
        "01JBQ8Z3F7KX2M4N6P8R0S2T4",  # 25 characters
        "01JBQ8Z3F7KX2M4N6P8R0S2T4VV",  # 27
        "01jbq8z3f7kx2m4n6p8r0s2t4v",  # lowercase
        "01IBQ8Z3F7KX2M4N6P8R0S2T4V",  # `I` is not in Crockford base32
        "0123456789012345678901234O",  # nor is `O`
        "----------------------------",
    ],
)
def test_a_non_ulid_id_is_refused(bad_id: str):
    """Matched against the ULID alphabet, not merely length-checked.

    `I`, `L`, `O` and `U` are excluded from Crockford base32 precisely because
    they are confusable, so a 26-character string containing one is not a ULID -
    it is something that was typed.
    """
    with pytest.raises(KeyRejected):
        keys.resume_key(USER, bad_id, "pdf")


def test_a_non_ulid_user_id_is_refused():
    """The prefix is the deletion unit, so a malformed user id is the worst
    place for one: every object under it would be unreachable by the sweep."""
    with pytest.raises(KeyRejected, match="user_id"):
        keys.user_prefix("not-a-ulid")


def test_the_failure_says_which_id_was_wrong():
    """Three ULIDs in one key. "not a ULID" without saying which leaves the
    reader to guess, and the guess is wrong two times in three."""
    with pytest.raises(KeyRejected, match="document_id"):
        keys.application_document_key(USER, APPLICATION, "nope", "pdf")


# -- extensions ---------------------------------------------------------------


@pytest.mark.parametrize("extension", ["pdf", "PDF", ".pdf", "docx", "txt"])
def test_an_allowed_extension_is_normalised(extension: str):
    """Case and a leading dot are both shapes a caller supplies; neither is a
    different extension."""
    key = keys.resume_key(USER, RESUME, extension)

    assert key.endswith(f".{extension.lower().lstrip('.')}")


@pytest.mark.parametrize("extension", ["exe", "sh", "php", "svg", "", "pdf.exe"])
def test_a_disallowed_extension_is_refused(extension: str):
    """The extension is part of the key, so it comes from us and never from the
    upload. `AC-DATA-04.4` decides what a file *is*; this decides what may be
    written down about it."""
    with pytest.raises(KeyRejected):
        keys.resume_key(USER, RESUME, extension)


# -- the prefix, and the trailing slash ---------------------------------------


def test_the_user_prefix_ends_with_a_slash():
    """Not cosmetic, and the reason is specific.

    ULIDs are lexicographically ordered by time, so two ids created in the same
    millisecond share a long prefix. Sweeping `u/01ABC` without the slash would
    delete objects belonging to `u/01ABCD...`, and that collision becomes *more*
    likely under load rather than less.
    """
    assert keys.user_prefix(USER) == f"u/{USER}/"
    assert keys.user_prefix(USER).endswith("/")


def test_every_user_key_is_under_that_users_prefix():
    """`AUTH-07`'s deletion is a prefix sweep, so this is the property that
    makes deletion complete by construction rather than as complete as the
    database's own record of what was uploaded."""
    prefix = keys.user_prefix(USER)

    for name, key in LAYOUT.items():
        if name == "backup":
            continue
        assert key.startswith(prefix), f"{name} is not under {prefix}"


def test_one_users_prefix_does_not_cover_another():
    other = "01JBQ8Z3F7KX2M4N6P8R0S2T50"

    assert not keys.resume_key(other, RESUME, "pdf").startswith(keys.user_prefix(USER))


# -- reading a key back -------------------------------------------------------


def test_the_owner_is_read_from_the_key():
    """`AC-DATA-04.2`'s ownership check parses the key rather than trusting a
    caller's claim about whose object it is - a signer that trusted the claim
    would be an ownership check in name only."""
    assert keys.owner_of(keys.resume_key(USER, RESUME, "pdf")) == USER


def test_a_backup_key_has_no_owner():
    """So a presigned-URL path that keyed on the owner cannot accidentally sign
    an ops object for whoever asked."""
    assert keys.owner_of(keys.backup_key("2026-09-08")) is None


def test_an_invalid_key_has_no_owner():
    """Rather than the second path segment, whatever it happens to be."""
    assert keys.owner_of("u/../resumes/x.pdf") is None
    assert keys.owner_of("nonsense") is None


# -- the validator's own coverage ---------------------------------------------


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("", "character"),
        ("u/", "does not begin"),
        (f"u/{USER}/", "does not begin"),
        (f"u/{USER}/resumes", "does not begin"),
        (f"u/{USER}/secrets/{RESUME}.pdf", "names area"),
        (f"u/{USER}/resumes/{RESUME}", "no extension"),
        (f"u/{USER}/resumes/cv.pdf", "not a ULID"),
        (f"u/{USER}/resumes/{RESUME}.exe", "not allowed"),
        (f"u/{USER}/applications/{APPLICATION}.pdf", "application document is"),
        (f"u/{USER}/applications/nope/{DOCUMENT}.pdf", "application id is not"),
        (f"x/{USER}/resumes/{RESUME}.pdf", "is not under"),
        ("backups/nope/dump.archive.gz", "backups/"),
        ("backups/2026-09-08/other.gz", "backups/"),
    ],
)
def test_the_validator_says_why(key: str, expected: str):
    """Each rejection has a distinct reason.

    The audit in `test_key_audit.py` reports these per object against a live
    bucket, where "invalid" on its own would leave somebody to work out what is
    wrong with each of several thousand keys.
    """
    reason = keys.rejection_reason(key)

    assert reason is not None, f"{key!r} should be rejected"
    assert expected in reason, f"{key!r}: {reason!r} does not mention {expected!r}"


def test_a_valid_key_has_no_reason():
    """The other direction: `rejection_reason` returning a string for a good key
    would make the audit report every object in the bucket."""
    assert keys.rejection_reason(LAYOUT["resume"]) is None


def test_the_ttl_and_lifecycle_numbers_are_the_ones_the_spec_names():
    """§4: presigned GETs expire in 5 minutes; noncurrent versions expire after
    30 days. Constants rather than literals, so the adapter and the bucket's
    lifecycle rule cannot disagree with the specification separately."""
    assert keys.PRESIGNED_TTL_SECONDS == 300
    assert keys.NONCURRENT_VERSION_DAYS == 30


def test_the_areas_are_the_three_the_layout_names():
    """A fourth area would be a fourth line in §4's layout block. An enum
    rather than a string parameter, because this is the one position where a
    caller could pass something arbitrary and still produce a valid-looking
    key."""
    assert {member.value for member in Area} == {"resumes", "applications", "exports"}
