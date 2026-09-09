"""The Pwned Passwords breach check - `AUTH-01`.

`02-auth-and-account.md` §1: "Breach check via the Pwned Passwords
**k-anonymity** range API: send the first 5 hex characters of the SHA-1 hash,
never the password or its full hash. A match rejects with `password_breached`
and a count. If the service is unreachable, **allow** the registration and
record a metric - a third-party outage must not close the front door."

Three things this module is careful about.

**Only five characters leave the process.** The SHA-1 is computed here and
sliced; the request carries the prefix and nothing else. That is the whole
k-anonymity property, and `AC-AUTH-01.2` asserts it on the *outbound request*
rather than on this module's intent - which is why the test intercepts the
transport instead of stubbing the client.

**Unreachable means allow.** §1 is explicit, and the reasoning is worth keeping
in view: the alternative is that a third party's outage stops anyone signing up.
So every failure path returns `checked=False` and the caller proceeds. The
metric is what makes that visible rather than silent.

**SHA-1 is not a security choice here.** It is the API's index. The hash never
leaves in full and is never stored, so its weakness is irrelevant - what matters
is that the prefix is 5 hex characters, which is what the service expects.

This is `infra` because it is an outbound HTTP call: `no-http-in-domain` forbids
`auth.service` from importing an HTTP client, and `01-foundations.md` §4 says
infra "knows how to open a connection and nothing about what the collections
mean". The decision to *refuse* a registration is the service's; this returns a
verdict.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

import httpx

from app.core import metrics

logger = logging.getLogger("app.breaches")

#: The API indexes by the first five hex characters of an uppercase SHA-1.
PREFIX_LENGTH = 5

#: A short timeout, deliberately. This call sits in the registration path, and
#: §1 would rather allow the registration than make the user wait on a third
#: party. Anything longer turns a degraded service into a slow sign-up form.
TIMEOUT_SECONDS = 3.0


@dataclass(frozen=True)
class BreachVerdict:
    """What the check found, and whether it ran at all.

    `checked=False` is not "clean" - it is "unknown". Kept as a separate field
    rather than folded into `count == 0` because the caller has to treat the two
    differently: §1 allows the registration either way, but only one of them
    should increment a metric someone is watching.
    """

    breached: bool
    count: int
    checked: bool


UNAVAILABLE = BreachVerdict(breached=False, count=0, checked=False)


def prefix_and_suffix(password: str) -> tuple[str, str]:
    """The SHA-1 of the password, split where the API splits it.

    Returned as a pair so the caller can match the suffix locally: the response
    is a list of suffixes for the prefix, and comparing them here is what keeps
    the full hash inside this process.
    """
    digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()  # noqa: S324
    return digest[:PREFIX_LENGTH], digest[PREFIX_LENGTH:]


def parse_range(body: str, suffix: str) -> int:
    """The count for `suffix` in a range response, or 0.

    The body is `SUFFIX:COUNT` per line. Entries with a count of zero are
    **padding** - the service adds them when asked to, so a response's size does
    not reveal how many real matches a prefix has - and are skipped rather than
    treated as a match with no occurrences.

    A malformed line is skipped instead of raising. The response is a third
    party's and the failure mode to avoid is one bad line refusing a
    registration that should have been allowed.
    """
    for line in body.splitlines():
        candidate, separator, raw_count = line.strip().partition(":")
        if not separator or candidate.upper() != suffix:
            continue
        try:
            count = int(raw_count.replace(",", ""))
        except ValueError:
            continue
        if count > 0:
            return count
    return 0


class PwnedPasswords:
    """§1's range-API client.

    The `httpx` client is injected rather than constructed, for the reason
    `01-foundations.md` §2 gives - no module reads the environment - and because
    it lets `AC-AUTH-01.3`'s outage be a transport that raises rather than a
    real network failure.
    """

    def __init__(self, client: httpx.AsyncClient, *, base_url: str) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")

    async def check(self, password: str) -> BreachVerdict:
        """Whether this password appears in a known breach.

        Never raises. Every failure is `UNAVAILABLE`, because §1 requires the
        registration to proceed when the service cannot be reached, and an
        exception escaping here would close the front door that §1 explicitly
        wants left open.
        """
        prefix, suffix = prefix_and_suffix(password)
        try:
            response = await self._client.get(
                f"{self._base_url}/range/{prefix}",
                # Asks the service to pad the response with zero-count entries,
                # so its length does not leak how many real matches the prefix
                # has. `parse_range` skips them.
                headers={"Add-Padding": "true"},
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - a timeout, a 5xx and a DNS failure are one case
            # The password is not in the log line, and neither is the prefix:
            # five characters of a SHA-1 is a small set, and a log that pairs it
            # with a timestamp narrows which account it belonged to.
            logger.warning("breach check unavailable", exc_info=exc)
            metrics.breach_check_unavailable.inc()
            return UNAVAILABLE

        count = parse_range(response.text, suffix)
        return BreachVerdict(breached=count > 0, count=count, checked=True)


__all__ = [
    "PREFIX_LENGTH",
    "TIMEOUT_SECONDS",
    "UNAVAILABLE",
    "BreachVerdict",
    "PwnedPasswords",
    "parse_range",
    "prefix_and_suffix",
]
