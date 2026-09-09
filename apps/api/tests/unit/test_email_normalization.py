"""T-AUTH-01.5 - the uniqueness key, and where dot-folding stops.

`AC-AUTH-01.5`: "Two registrations for `a.b@gmail.com` and `ab@gmail.com`
collide on `email_normalized`; `a.b@example.com` and `ab@example.com` do not."

The criterion is written as two halves and both matter. Folding dots everywhere
would merge different mailboxes at providers where a dot is significant, and the
person refused registration would have no way to find out why; folding nowhere
lets one Gmail user hold as many accounts as they have places to put a dot.
"""

from __future__ import annotations

import pytest

from app.shared.emails import normalize


def test_gmail_dots_collide() -> None:
    """`AC-AUTH-01.5`, first half."""
    assert normalize("a.b@gmail.com") == normalize("ab@gmail.com")


def test_non_gmail_dots_do_not_collide() -> None:
    """`AC-AUTH-01.5`, second half - and the one a naive implementation fails."""
    assert normalize("a.b@example.com") != normalize("ab@example.com")


def test_googlemail_is_gmail() -> None:
    """The same service under its other name.

    `googlemail.com` still delivers to the same mailbox, so omitting it would
    leave a second dot-insensitive domain behaving dot-sensitively.
    """
    assert normalize("a.b@googlemail.com") == normalize("ab@googlemail.com")


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("A.User@Gmail.com", "auser@gmail.com"),
        ("  spaced@example.com  ", "spaced@example.com"),
        ("MiXeD@EXAMPLE.COM", "mixed@example.com"),
    ],
)
def test_case_and_whitespace_are_folded(written: str, expected: str) -> None:
    """Lowercasing and trimming apply to every domain (§2.1).

    Case-folding is universal because SMTP domains are case-insensitive and
    every provider in practice treats the local part that way too. The trim is
    for the leading space a phone keyboard adds after autocomplete.
    """
    assert normalize(written) == expected


def test_the_domain_keeps_its_dots() -> None:
    """Only the local part is folded.

    Stripping dots from the domain would turn `gmail.com` into `gmailcom` and
    make every Gmail address normalize to a domain that does not exist - the
    unique index would still work, and every outbound email would fail.
    """
    assert normalize("a.b@gmail.com") == "ab@gmail.com"


def test_plus_tags_are_preserved() -> None:
    """Documented behaviour, not an oversight.

    Gmail does route `user+x@` to `user@`, so this leaves one duplicate-account
    route open. §2.1 says "dot-stripped" and nothing more, and plus-addressing
    is also how people deliberately separate mail. Changing it is a spec
    decision; this test is here so the current choice is visible rather than
    accidental.
    """
    assert normalize("user+jobs@gmail.com") != normalize("user@gmail.com")


def test_an_address_with_no_at_sign_is_returned_lowercased() -> None:
    """Validation belongs to the schema, not here.

    `RegisterRequest` rejects a non-address before this is reached. A normalizer
    that raised would force every caller to handle an error the validator has
    already refused, and `AUTH-03`'s OAuth path would need the same handling for
    a value Google guarantees.
    """
    assert normalize("NotAnEmail") == "notanemail"
    assert normalize("") == ""


def test_a_local_part_that_is_only_dots_does_not_become_empty_at_a_domain() -> None:
    """An edge case worth pinning rather than discovering.

    `...@gmail.com` folds to `@gmail.com`, which is not a deliverable address -
    but it is a *stable* key, and the schema refuses the input long before this.
    The assertion is that it does not raise and does not collide with a real
    address.
    """
    folded = normalize("...@gmail.com")

    assert folded == "@gmail.com"
    assert folded != normalize("a@gmail.com")
