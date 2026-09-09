"""Password policy and hashing - `AUTH-01`.

`02-auth-and-account.md` §1: "Create an account from an email and a password
that is not already known to be compromised."

Three decisions, all of them the requirement's rather than mine.

**Length, and no composition rules.** §1: "minimum 10 characters, maximum 128
... No composition rules - length and a breach check outperform character-class
requirements." The maximum is not a security limit, it is a denial-of-service
one: Argon2 hashes whatever it is given, and a 10 MB password is 10 MB of work
per request.

**The bounds are module constants, not configuration.** This is the one place
`CLAUDE.md`'s "limits are configuration" rule is deliberately not applied, and
the reason is the direction of the mistake. A tunable rate limit that is set too
low refuses honest traffic and someone notices within minutes; a tunable
password minimum that is set too low is invisible and permanent. §1 fixes these
two numbers, `AC-AUTH-01.1` asserts them exactly, and nothing in
`15-infra-and-ops.md` §5 lists them as environment. A deployment does not get to
weaken this.

**Argon2id with the parameters written down.** §1 names them: `time_cost=3`,
`memory_cost=65536`, `parallelism=1`, a 16-byte salt. `argon2-cffi` encodes them
into the hash string, which is what makes `needs_rehash` possible - §1: "so they
can be raised later and old hashes rehashed on next successful login."

The breach check is *not* here. It is an outbound HTTP call and lives in
`infra/breaches.py`, because `no-http-in-domain` forbids a service from making
one and this module is called by the service.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.errors import AppError, ErrorCode

#: §1. Ten is the floor a breach check makes meaningful; below it, most
#: passwords are in a wordlist regardless of what the check says.
MIN_LENGTH = 10

#: §1. A cap so a large body cannot turn one request into unbounded hashing
#: work. Argon2 has no truncation bug to work around - the note in §1 about
#: bcrypt is there to explain why the cap is *not* 72.
MAX_LENGTH = 128

#: §1's parameters, and `AC-AUTH-01.6` asserts the encoded form
#: `m=65536,t=3,p=1` appears in a stored hash.
TIME_COST = 3
MEMORY_COST_KIB = 65536
PARALLELISM = 1
SALT_BYTES = 16

#: One hasher, built once. Constructing a `PasswordHasher` is cheap but doing it
#: per call invites the parameters being passed inconsistently, which is exactly
#: the drift `needs_rehash` exists to detect.
_HASHER = PasswordHasher(
    time_cost=TIME_COST,
    memory_cost=MEMORY_COST_KIB,
    parallelism=PARALLELISM,
    salt_len=SALT_BYTES,
)


class PasswordTooShort(AppError):
    """`AC-AUTH-01.1` - 422, and it says which way it is wrong.

    Naming the direction is safe here and useful: the length policy is public
    (it is on the registration form), so "too short" reveals nothing an attacker
    does not already know, and "invalid password" would send a user to reset a
    password they had not yet set.
    """

    code = ErrorCode.PASSWORD_TOO_SHORT
    http_status = 422


class PasswordTooLong(AppError):
    """`AC-AUTH-01.1` - 422 at 129 characters."""

    code = ErrorCode.PASSWORD_TOO_LONG
    http_status = 422


def check_length(password: str) -> None:
    """Raise unless the password is within §1's bounds.

    Measured in characters rather than bytes, which is what §1 says and what a
    user counts. A 128-character string of astral-plane emoji is more than 128
    bytes and is still accepted; the DoS bound that matters is the request body
    limit, not this.
    """
    if len(password) < MIN_LENGTH:
        raise PasswordTooShort()
    if len(password) > MAX_LENGTH:
        raise PasswordTooLong()


def hash_password(password: str) -> str:
    """An Argon2id hash with §1's parameters encoded into it.

    Length is *not* checked here. Hashing and policy are separate on purpose:
    `AUTH-04`'s password reset and `AUTH-05`'s change both need the same policy
    applied before they get this far, and a hash function that also validated
    would make the policy invisible at those call sites.
    """
    return _HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Whether the password matches. Never raises for a wrong password.

    `VerifyMismatchError` is the ordinary "no" and becomes `False`; the broader
    `VerificationError` and `InvalidHashError` are also `False`, because a
    malformed stored hash must fail closed rather than 500. §1's enumeration
    rule means the caller answers identically either way, so a distinction here
    would have nowhere to go.
    """
    try:
        return _HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Whether this hash was made with weaker parameters than current.

    §1: parameters "can be raised later and old hashes rehashed on next
    successful login". The rehash itself belongs to the login path (`AUTH-02`),
    which is the only place the plaintext exists again.
    """
    try:
        return bool(_HASHER.check_needs_rehash(password_hash))
    except InvalidHashError:
        # Unparseable: it cannot be upgraded in place, and saying "yes" here
        # would ask the caller to rehash something it cannot verify first.
        return False


__all__ = [
    "MAX_LENGTH",
    "MEMORY_COST_KIB",
    "MIN_LENGTH",
    "PARALLELISM",
    "SALT_BYTES",
    "TIME_COST",
    "PasswordTooLong",
    "PasswordTooShort",
    "check_length",
    "hash_password",
    "needs_rehash",
    "verify_password",
]
