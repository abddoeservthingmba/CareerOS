"""T-AUTH-01.6 - the stored hash carries §1's parameters.

`AC-AUTH-01.6`: "A stored hash begins with `$argon2id$` and encodes
`m=65536,t=3,p=1`."

Asserted on the *encoded string* rather than on the hasher's attributes, and
that is the point of the criterion. The parameters have to be recoverable from
the database row, because §1 wants them "stored with the hash so they can be
raised later and old hashes rehashed on next successful login". A hasher
configured correctly that wrote a hash without its parameters would satisfy
every other test here and make that upgrade impossible.
"""

from __future__ import annotations

from app.core import passwords

PASSWORD = "correcthorsebatterystaple"


def test_hash_is_argon2id_not_argon2i_or_argon2d() -> None:
    """`AC-AUTH-01.6`'s prefix.

    The variant matters: Argon2i is side-channel-hardened but weaker against
    time-memory trade-offs, Argon2d the reverse. `id` is the hybrid and the one
    §1 names.
    """
    assert passwords.hash_password(PASSWORD).startswith("$argon2id$")


def test_hash_encodes_the_parameters_the_spec_names() -> None:
    """`AC-AUTH-01.6` - `m=65536,t=3,p=1`, as a substring of the hash."""
    assert "m=65536,t=3,p=1" in passwords.hash_password(PASSWORD)


def test_the_parameters_are_the_ones_the_spec_names() -> None:
    """§1's numbers, so a change is a deliberate edit to this list."""
    assert passwords.MEMORY_COST_KIB == 65536
    assert passwords.TIME_COST == 3
    assert passwords.PARALLELISM == 1
    assert passwords.SALT_BYTES == 16


def test_two_hashes_of_one_password_differ() -> None:
    """The salt is per-hash, not per-deployment.

    Identical hashes for identical passwords would make the `users` collection a
    map of which accounts share a password - useful to an attacker with a dump
    and no need to crack anything.
    """
    assert passwords.hash_password(PASSWORD) != passwords.hash_password(PASSWORD)


def test_the_password_is_verifiable() -> None:
    """The obvious one, which is worth stating: the hash round-trips."""
    stored = passwords.hash_password(PASSWORD)

    assert passwords.verify_password(stored, PASSWORD) is True
    assert passwords.verify_password(stored, PASSWORD + "x") is False


def test_a_wrong_password_returns_false_rather_than_raising() -> None:
    """§1's enumeration rule needs a boolean, not an exception.

    `argon2-cffi` raises `VerifyMismatchError` for a mismatch. If that escaped,
    the caller would need a `try` around every check and the shape of the
    failure would start differing between "wrong password" and "no such
    account" - which is precisely the oracle §1 closes.
    """
    stored = passwords.hash_password(PASSWORD)

    assert passwords.verify_password(stored, "wrong") is False


def test_a_malformed_stored_hash_fails_closed() -> None:
    """Garbage in the column is a `False`, not a 500.

    A row whose `password_hash` was truncated or hand-edited must not let anyone
    in, and must not crash the login route either - a 500 on a specific account
    is itself an enumeration signal.
    """
    assert passwords.verify_password("not-a-hash", PASSWORD) is False
    assert passwords.verify_password("", PASSWORD) is False


def test_a_current_hash_does_not_need_rehashing() -> None:
    """`needs_rehash` is `False` for a hash this module just made.

    The inverse - a freshly written hash reported as stale - would rehash on
    every single login, which is the expensive kind of silent bug.
    """
    assert passwords.needs_rehash(passwords.hash_password(PASSWORD)) is False


def test_a_weaker_hash_needs_rehashing() -> None:
    """§1's upgrade path works: a hash made with lower cost is flagged.

    Built by hand with weaker parameters rather than by changing the module's
    constants, so this asserts the detection rather than asserting that a
    variable can be reassigned.
    """
    from argon2 import PasswordHasher

    weaker = PasswordHasher(
        time_cost=1,
        memory_cost=8,
        parallelism=1,
        salt_len=passwords.SALT_BYTES,
    ).hash(PASSWORD)

    assert passwords.needs_rehash(weaker) is True


def test_a_malformed_hash_is_not_reported_as_upgradeable() -> None:
    """`needs_rehash` on garbage is `False`.

    Saying `True` would ask the caller to rehash a value it could not verify
    first, which is how an unverifiable row becomes a valid credential.
    """
    assert passwords.needs_rehash("not-a-hash") is False
