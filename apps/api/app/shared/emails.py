"""Email address normalization - `AUTH-01`, `DATA-02` §2.1.

`17-data-model.md` §2.1: "`email_normalized` is lowercased and, for
Gmail-family domains, dot-stripped - it is the uniqueness key. `email`
preserves what the user typed."

Two addresses, two purposes. The stored `email` is what appears in a `To:`
header and what the user recognises, so their capitalisation survives.
`email_normalized` is what the unique index enforces, so
`A.User@Gmail.com` and `auser@gmail.com` cannot become two accounts for one
person.

**Only dots, and only for Gmail.** `AC-AUTH-01.5` is exact about the boundary:
`a.b@gmail.com` and `ab@gmail.com` collide, `a.b@example.com` and
`ab@example.com` do not. Dot-insensitivity is a Gmail policy, not an email one -
applying it everywhere would merge two genuinely different mailboxes at any
provider that treats dots as significant, and the person locked out of
registering would have no way to explain why.

`+tags` are deliberately **not** stripped. Gmail does route `user+x@gmail.com`
to `user@gmail.com`, so stripping would close one more duplicate-account route -
but §2.1 says "dot-stripped" and nothing else, and plus-addressing is also how
people legitimately separate mail they intend to keep separate. If that trade
should change it is a spec decision, not one to make here.

This lives in `shared/` rather than in `auth/` because it is a primitive over a
stored field: `DATA-02` owns the shape of `users`, and `AUTH-03`'s Google
sign-in has to arrive at the same normalized value as `AUTH-01`'s registration
or one person gets two accounts by signing in a different way.
"""

from __future__ import annotations

#: Domains Google routes to one mailbox regardless of dots.
#:
#: `googlemail.com` is the same service under a different name - it is what
#: Gmail used in Germany and the UK, and it still delivers. Omitting it would
#: leave `a.b@googlemail.com` and `ab@googlemail.com` as two accounts.
GMAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})


def normalize(email: str) -> str:
    """The uniqueness key for `email`.

    Lowercased and whitespace-trimmed always; dots removed from the local part
    only when the domain is Gmail-family.

    Input that is not an address shape - no `@`, or more than one - is returned
    lowercased and otherwise untouched. Validation is the schema's job
    (`RegisterRequest` uses pydantic's `EmailStr`), and a normalizer that raised
    would make every caller handle an error the validator has already refused.
    """
    cleaned = email.strip().lower()
    local, separator, domain = cleaned.rpartition("@")
    if not separator or not local:
        return cleaned
    if domain in GMAIL_DOMAINS:
        local = local.replace(".", "")
    return f"{local}@{domain}"


__all__ = ["GMAIL_DOMAINS", "normalize"]
