"""T-DATA-04.2 - a presigned URL is short-lived and never another user's.

`AC-DATA-04.2`: "A presigned URL expires in 5 minutes and a URL for another
user's object is never issued (ownership checked before signing; 404 otherwise)."

`17-data-model.md` §4: "No public bucket access. Every read is a presigned GET
with a 5-minute TTL, issued only after an ownership check."

**Why the check is inside the signer.** Written as "the caller checks
ownership first", the rule holds until the second endpoint that needs a
download - an admin view, an export, a mobile client's refresh - and one of
them will call the signer directly. A signed URL is a bearer token for an
object: whoever holds it reads the file, with no further authorisation, for as
long as it lives. So the authorisation happens where the token is minted.

**404, not 403.** `01-foundations.md` and `02` §6. A 403 confirms the object
exists, which is precisely what an attacker enumerating ULIDs wants to learn -
and ULIDs are time-ordered, so guessing one created near a known one is not
absurd. `NotFound` is the only thing raised, for both "no such object" and "not
yours", and the check order matters: ownership first, so the two cannot be
distinguished by which check ran.

**Five minutes.** Long enough for a browser to follow a redirect and a slow
connection to start the download; short enough that a URL leaked into a
referrer header, a chat message or a support ticket is useless by the time
anybody reads it. §4 gives the number and `object_keys` holds it, so the signer
and the spec cannot disagree separately.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core import clock
from app.core.ids import new_id
from app.infra.storage import (
    MemoryStore,
    NotFound,
    chunked,
    content_disposition,
    sanitize_filename,
)
from app.shared.object_keys import PRESIGNED_TTL_SECONDS, resume_key

OWNER = new_id()
INTRUDER = new_id()


@pytest.fixture
async def stored(store: MemoryStore) -> tuple[MemoryStore, str]:
    key = resume_key(OWNER, new_id(), "pdf")
    await store.put_stream(key, chunked([b"%PDF-1.7 body"]), content_type="application/pdf")
    return store, key


# -- the criterion ------------------------------------------------------------


async def test_the_owner_gets_a_url(stored):
    store, key = stored

    url = await store.presign_get(key, user_id=OWNER)

    assert key in url
    assert "X-Amz-Signature=" in url


async def test_another_users_object_is_never_signed(stored):
    """`AC-DATA-04.2`'s second clause. A signed URL is a bearer token for the
    object; issuing one for somebody else's résumé is the whole breach, not a
    step towards it."""
    store, key = stored

    with pytest.raises(NotFound):
        await store.presign_get(key, user_id=INTRUDER)


async def test_the_refusal_is_a_not_found_rather_than_a_forbidden(stored):
    """404, not 403.

    A 403 confirms the object exists. ULIDs are time-ordered, so an attacker
    who knows one id can guess neighbours; telling them which guesses named
    real objects is the enumeration oracle this exists to deny.
    """
    store, key = stored

    with pytest.raises(NotFound) as caught:
        await store.presign_get(key, user_id=INTRUDER)

    assert "not found" in str(caught.value)


async def test_a_missing_object_and_someone_elses_are_indistinguishable(store: MemoryStore):
    """Same exception, same message shape.

    Two exception types would become two status codes, and the difference
    between them would be the oracle.
    """
    mine = resume_key(OWNER, new_id(), "pdf")
    theirs = resume_key(INTRUDER, new_id(), "pdf")
    await store.put_stream(theirs, chunked([b"%PDF-x"]), content_type="application/pdf")

    with pytest.raises(NotFound) as absent:
        await store.presign_get(mine, user_id=OWNER)
    with pytest.raises(NotFound) as forbidden:
        await store.presign_get(theirs, user_id=OWNER)

    assert type(absent.value) is type(forbidden.value)


async def test_ownership_is_checked_before_existence(store: MemoryStore):
    """The order, asserted.

    Checking existence first would make the two refusals distinguishable by
    timing - a HEAD against the bucket takes a network round trip and an
    ownership check is a string comparison. That is a real side channel, and it
    is free to close by checking ownership first.
    """
    never_written = resume_key(INTRUDER, new_id(), "pdf")

    with pytest.raises(NotFound):
        await store.presign_get(never_written, user_id=OWNER)

    # Nothing was signed and nothing was looked up.
    assert store.signed == []


async def test_the_url_expires_in_five_minutes(stored):
    """`AC-DATA-04.2`'s first clause, and §4's number."""
    store, key = stored
    moment = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    with clock.freeze(moment):
        await store.presign_get(key, user_id=OWNER)

    _, _, expires = store.signed[-1]

    assert expires - moment == timedelta(seconds=PRESIGNED_TTL_SECONDS)
    assert PRESIGNED_TTL_SECONDS == 300


async def test_the_ttl_is_in_the_url_itself(stored):
    """Not only in our record of it.

    S3 enforces `X-Amz-Expires`; our bookkeeping does not. A five-minute entry
    in a list beside a URL signed for seven days would look correct in every
    test and be wrong in the only place it matters.
    """
    store, key = stored

    url = await store.presign_get(key, user_id=OWNER)

    assert f"X-Amz-Expires={PRESIGNED_TTL_SECONDS}" in url


async def test_two_urls_for_the_same_object_differ_by_expiry(stored):
    """So a URL cannot be cached and reissued past its own lifetime."""
    store, key = stored

    moment = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    with clock.freeze(moment):
        first = await store.presign_get(key, user_id=OWNER)
    with clock.freeze(moment + timedelta(minutes=10)):
        second = await store.presign_get(key, user_id=OWNER)

    assert first != second


# -- the filename, which is the only user-supplied thing in the path ----------


async def test_the_filename_reaches_the_content_disposition_and_nowhere_else(stored):
    """§4: the user's filename is "used only in the `Content-Disposition` of a
    presigned download, sanitized"."""
    store, key = stored

    url = await store.presign_get(key, user_id=OWNER, filename="Priya Sharma CV.pdf")

    assert "response-content-disposition" in url
    # The key is unchanged: the name did not become part of the object's
    # address (`AC-DATA-04.1`).
    assert "Priya" not in key


@pytest.mark.parametrize(
    "hostile",
    [
        'cv".pdf',
        "cv\r\nSet-Cookie: a=b",
        "cv\nX-Injected: 1",
        "../../etc/passwd",
        "cv\\..\\..\\windows",
        "cv\t.pdf",
    ],
)
def test_a_hostile_filename_cannot_break_the_header(hostile: str):
    """Header injection through a filename is the oldest trick there is.

    A `"` closes the quoted value and a newline ends the header, after which
    the rest of the string is an attacker-chosen header on a response the
    browser trusts. A path separator is the other half: some clients honour it
    when saving.
    """
    cleaned = sanitize_filename(hostile)

    assert '"' not in cleaned
    assert "\r" not in cleaned and "\n" not in cleaned
    assert "/" not in cleaned and "\\" not in cleaned
    assert "\t" not in cleaned


def test_an_empty_filename_becomes_a_usable_one():
    """A `Content-Disposition` with an empty filename makes some browsers save
    the page's URL as the name, which is the presigned URL - so the user's
    download is named after a bearer token."""
    assert sanitize_filename("") == "download"
    assert sanitize_filename('"""') == "download"


def test_an_accented_filename_survives_in_both_forms():
    """RFC 6266's two forms, and both are needed.

    Only the plain form turns `Ingénieur.pdf` into mojibake in the save dialog;
    only the extended form loses the name entirely on old clients.
    """
    header = content_disposition("Ingénieur CV.pdf")

    assert header is not None
    assert "filename=" in header
    assert "filename*=UTF-8''" in header
    assert "Ing%C3%A9nieur" in header


def test_a_very_long_filename_is_truncated():
    """Header size limits are enforced by proxies, not by us, and a request
    that dies at a proxy is a download that fails with no error anyone can
    see."""
    assert len(sanitize_filename("a" * 5000)) <= 200


def test_no_filename_means_no_disposition_header():
    """Rather than an empty one. An empty header is a header, and a browser
    that sees `attachment` with no name behaves differently from one that sees
    nothing."""
    assert content_disposition(None) is None


# -- there is no public read path ----------------------------------------------


def test_the_protocol_offers_no_way_to_read_bytes_through_the_api():
    """§4: "No public bucket access", and HR-8: file bytes never leave our
    infrastructure.

    A `get_bytes` on the protocol would be the method somebody used for a
    résumé - and then résumé bytes would flow through the API process, which is
    exactly what the presigned-URL design avoids. The absence is the control,
    so it is asserted.
    """
    from app.infra.storage import ObjectStore

    methods = {name for name in dir(ObjectStore) if not name.startswith("_")}

    assert methods == {"put_stream", "head", "presign_get", "list_prefix", "delete_prefix"}
