"""T-FOUND-07.2 / T-FOUND-07.3 - the cursor as a credential.

`AC-FOUND-07.2`: "A cursor tampered with in any byte is rejected with 400
`invalid_cursor`."
`AC-FOUND-07.3`: "A cursor issued for user A, replayed by user B, returns B's
own first page - never A's data."

`01-foundations.md` §7: "Cursor is an opaque base64url of `{sort_key_values,
id}`, signed with `SECRET_KEY` so a client cannot forge a position into another
user's data."

The two criteria answer differently on purpose, and the difference is the whole
design:

* A **tampered** cursor is a forgery attempt, and 400 is the honest answer.
* A **genuine** cursor belonging to someone else is not necessarily an attack -
  a shared link, a copied URL, a session that changed under a client - and
  answering 400 would confirm the cursor was real, which is one bit more than a
  stranger should learn. Returning the reader's own first page tells them
  nothing and costs them nothing.

Neither is load-bearing for authorisation: the repository scopes every query by
`user_id` regardless (`AC-FOUND-05.2`). The cursor is a position, not a
capability, and this file exists to keep it that way.
"""

from __future__ import annotations

import base64
import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.shared.pagination import (
    NEWEST_FIRST,
    Cursor,
    CursorError,
    PaginationRequest,
    SortKey,
    SortSpec,
)

SECRET = "a-secret-long-enough-for-the-settings-validator-to-accept"
OTHER_SECRET = "a-different-secret-of-a-perfectly-respectable-length"

ALICE = "01J000000000000000000ALICE"
BOB = "01J00000000000000000000BOB"

BY_SCORE = SortSpec((SortKey("score.total", -1),))


def issued_to(user_id: str, sort: SortSpec = NEWEST_FIRST) -> str:
    return Cursor(
        values=tuple([None] * (len(sort.all_keys) - 1)) + ("01J0000000000000000000ROW",),
        id="01J0000000000000000000ROW",
        user_id=user_id,
        sort=sort.signature(),
    ).encode(SECRET)


# -- AC-FOUND-07.2: tampering -----------------------------------------------


def test_a_cursor_round_trips():
    """The baseline the rest of the file is a negation of."""
    raw = issued_to(ALICE)
    assert Cursor.decode(raw, SECRET).user_id == ALICE


def test_a_cursor_is_opaque():
    """§7: "an opaque base64url". Not encryption - the point is that no client
    can depend on the shape, so it can change without breaking one."""
    raw = issued_to(ALICE)
    assert ALICE not in raw
    assert "{" not in raw and "=" not in raw


@settings(max_examples=200, deadline=None)
@given(position=st.integers(min_value=0), replacement=st.sampled_from("ABCXYZ0189_-"))
def test_a_cursor_tampered_in_any_byte_is_rejected(position: int, replacement: str):
    """AC-FOUND-07.2, over every byte of a real cursor.

    Hypothesis rather than a handful of examples: the interesting failure is a
    byte whose change happens *not* to alter the decoded payload - a base64
    character in the padding region, say - and picking those by hand is exactly
    what nobody does.
    """
    raw = issued_to(ALICE)
    index = position % len(raw)
    if raw[index] == replacement:
        replacement = "Q" if replacement != "Q" else "R"
    tampered = raw[:index] + replacement + raw[index + 1 :]

    with pytest.raises(CursorError):
        Cursor.decode(tampered, SECRET)


def test_a_truncated_cursor_is_rejected():
    raw = issued_to(ALICE)
    for cut in (1, 4, len(raw) // 2, len(raw) - 1):
        with pytest.raises(CursorError):
            Cursor.decode(raw[:cut], SECRET)


def test_an_extended_cursor_is_rejected():
    with pytest.raises(CursorError):
        Cursor.decode(issued_to(ALICE) + "AAAA", SECRET)


def test_an_unsigned_payload_is_rejected():
    """The attack this is really about: build the JSON yourself and skip the
    signature entirely."""
    forged = (
        base64.urlsafe_b64encode(
            json.dumps(
                {"v": 1, "k": [None], "i": "x", "u": ALICE, "s": NEWEST_FIRST.signature()}
            ).encode()
        )
        .decode()
        .rstrip("=")
    )
    with pytest.raises(CursorError):
        Cursor.decode(forged, SECRET)


def test_a_cursor_signed_with_another_key_is_rejected():
    """A staging cursor replayed against production, or a rotated `SECRET_KEY`."""
    raw = Cursor((None, "x"), "x", ALICE, NEWEST_FIRST.signature()).encode(OTHER_SECRET)
    with pytest.raises(CursorError):
        Cursor.decode(raw, SECRET)


def test_garbage_is_rejected():
    for raw in ("", "!!!!", "not-a-cursor", "@" * 40, "AAAA"):
        with pytest.raises(CursorError):
            Cursor.decode(raw, SECRET)


def test_a_cursor_from_an_older_payload_version_is_rejected():
    """During a rolling restart both versions are in flight; misreading one is
    worse than asking the client to start the list again."""
    payload = json.dumps(
        {"v": 0, "k": [None], "i": "x", "u": ALICE, "s": NEWEST_FIRST.signature()},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    import hashlib
    import hmac

    # Signed correctly, so this fails on the version and not on the signature -
    # otherwise the test would pass without the version check existing at all.
    signature = hmac.new(SECRET.encode(), payload, hashlib.sha256).digest()[:16]
    raw = base64.urlsafe_b64encode(payload + signature).decode().rstrip("=")
    assert Cursor.decode(
        base64.urlsafe_b64encode(
            payload.replace(b'"v":0', b'"v":1')
            + hmac.new(
                SECRET.encode(), payload.replace(b'"v":0', b'"v":1'), hashlib.sha256
            ).digest()[:16]
        )
        .decode()
        .rstrip("="),
        SECRET,
    ), "the same payload at the current version must decode, or this proves nothing"

    with pytest.raises(CursorError):
        Cursor.decode(raw, SECRET)


def test_every_rejection_says_the_same_thing():
    """Telling "bad signature" from "malformed payload" apart is a forgery
    oracle, and the client can do nothing differently either way."""
    messages = set()
    for raw in ("!!!!", issued_to(ALICE)[:-2], "AAAA"):
        try:
            Cursor.decode(raw, SECRET)
        except CursorError as exc:
            messages.add(str(exc))
    assert len(messages) == 1, messages


# -- AC-FOUND-07.3: replay ---------------------------------------------------


def test_a_cursor_replayed_by_another_user_gives_that_user_their_first_page():
    """AC-FOUND-07.3."""
    stolen = issued_to(ALICE)

    position, _, _ = PaginationRequest(cursor=stolen, user_id=BOB, secret=SECRET).resolve(
        NEWEST_FIRST
    )

    assert position is None, "Bob resumed from Alice's position"


def test_the_replay_is_not_an_error():
    """A 400 would confirm the cursor was genuine. A shared link is not an
    attack, and the reader learns nothing either way."""
    stolen = issued_to(ALICE)
    request = PaginationRequest(cursor=stolen, user_id=BOB, secret=SECRET)
    position, limit, clamped = request.resolve(NEWEST_FIRST)
    assert (position, limit, clamped) == (None, 25, False)


def test_the_owner_resumes_normally():
    """The negative control: if this passed for everyone the test above would be
    vacuous."""
    position, _, _ = PaginationRequest(
        cursor=issued_to(ALICE), user_id=ALICE, secret=SECRET
    ).resolve(NEWEST_FIRST)
    assert position is not None
    assert position.user_id == ALICE


def test_an_anonymous_cursor_is_not_usable_by_a_signed_in_reader():
    """`user_id=None` is a public list. Carrying that cursor into a personal one
    would resume a personal list at a public position."""
    public = Cursor((None, "x"), "x", None, NEWEST_FIRST.signature()).encode(SECRET)
    position, _, _ = PaginationRequest(cursor=public, user_id=ALICE, secret=SECRET).resolve(
        NEWEST_FIRST
    )
    assert position is None


# -- the sort binding --------------------------------------------------------


def test_a_cursor_from_a_differently_sorted_list_is_rejected():
    """Not a forgery - a real cursor from another endpoint. Resuming would land
    at a position that means nothing in this order, which is worse than an
    error because it looks like data."""
    raw = issued_to(ALICE, BY_SCORE)
    with pytest.raises(CursorError):
        PaginationRequest(cursor=raw, user_id=ALICE, secret=SECRET).resolve(NEWEST_FIRST)


def test_the_sort_check_precedes_the_owner_check():
    """Otherwise a mismatched sort from another user would silently become a
    first page, hiding a client bug behind a security behaviour."""
    raw = issued_to(ALICE, BY_SCORE)
    with pytest.raises(CursorError):
        PaginationRequest(cursor=raw, user_id=BOB, secret=SECRET).resolve(NEWEST_FIRST)


def test_no_cursor_is_the_first_page_not_an_error():
    for empty in (None, ""):
        position, size, clamped = PaginationRequest(
            cursor=empty, user_id=ALICE, secret=SECRET
        ).resolve(NEWEST_FIRST)
        assert (position, size, clamped) == (None, 25, False)


def test_a_bad_cursor_is_rendered_as_400_invalid_cursor(settings_factory):
    """AC-FOUND-07.2's other half: "rejected with **400 `invalid_cursor`**".

    Asserted through the app, because the conversion from `shared`'s plain
    `CursorError` to the problem document happens in `main.py`'s handler - and a
    handler that was never registered would leave every tampered cursor a 500,
    with all the tests above still green.
    """
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(settings_factory())

    @app.get("/_test/list", include_in_schema=False)
    async def _list(cursor: str = "") -> dict[str, object]:
        Cursor.decode(cursor, SECRET)
        return {"items": []}

    response = TestClient(app).get("/_test/list", params={"cursor": "tampered"})

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["title"] == "invalid_cursor"
    assert body["status"] == 400


def test_the_secret_is_not_repr_able():
    """`AC-FOUND-02.3` - a secret in a `repr` reaches a log the moment anything
    logs the request object."""
    assert SECRET not in repr(PaginationRequest(secret=SECRET))
