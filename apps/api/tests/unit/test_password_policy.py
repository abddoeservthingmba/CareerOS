"""T-AUTH-01.1 - the length bounds, exactly.

`AC-AUTH-01.1`: "A password of 9 characters is rejected `422
password_too_short`; 10 is accepted; 129 is rejected."

Boundary values, and only boundary values. A test at 5 and 500 would pass for an
off-by-one policy, and off-by-one is the mistake a length check actually makes.
"""

from __future__ import annotations

import pytest

from app.core import passwords
from app.core.errors import ErrorCode


def test_nine_characters_is_too_short() -> None:
    """`AC-AUTH-01.1`, the lower boundary's failing side."""
    with pytest.raises(passwords.PasswordTooShort) as caught:
        passwords.check_length("a" * 9)

    assert caught.value.code is ErrorCode.PASSWORD_TOO_SHORT
    assert caught.value.http_status == 422


def test_ten_characters_is_accepted() -> None:
    """`AC-AUTH-01.1`, the lower boundary's passing side.

    §1's minimum is ten, so ten must pass. This is the assertion that fails if
    the comparison is written `<=` instead of `<`.
    """
    passwords.check_length("a" * 10)


def test_one_hundred_and_twenty_eight_is_accepted() -> None:
    """The upper boundary's passing side - §1's maximum is inclusive."""
    passwords.check_length("a" * 128)


def test_one_hundred_and_twenty_nine_is_too_long() -> None:
    """`AC-AUTH-01.1`, the upper boundary's failing side."""
    with pytest.raises(passwords.PasswordTooLong) as caught:
        passwords.check_length("a" * 129)

    assert caught.value.code is ErrorCode.PASSWORD_TOO_LONG
    assert caught.value.http_status == 422


def test_the_bounds_are_the_ones_the_spec_names() -> None:
    """§1's two numbers, asserted as values rather than only as behaviour.

    The tests above would still pass if both bounds moved together. This is the
    one that notices a deliberate weakening.
    """
    assert passwords.MIN_LENGTH == 10
    assert passwords.MAX_LENGTH == 128


def test_no_composition_rule_is_applied() -> None:
    """§1: "No composition rules - length and a breach check outperform
    character-class requirements."

    A long all-lowercase passphrase is exactly what the policy is meant to
    encourage, so it has to pass. This test exists because adding "must contain
    a digit" is the most common well-meant regression in an auth module.
    """
    passwords.check_length("correcthorsebatterystaple")


def test_length_is_counted_in_characters_not_bytes() -> None:
    """Ten characters of non-ASCII is ten characters.

    §1's bounds are characters, and `len()` on a `str` counts code points. A
    byte-length check would accept a four-character password whose UTF-8
    encoding happened to exceed ten bytes, which is the direction that matters.
    """
    nine = "日本語のパスワー"  # 8 code points
    ten = "日本語のパスワード!"  # 10 code points, 28 bytes in UTF-8

    assert len(ten) == 10
    passwords.check_length(ten)

    with pytest.raises(passwords.PasswordTooShort):
        passwords.check_length(nine)
