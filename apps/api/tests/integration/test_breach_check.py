"""T-AUTH-01.2/.3 - k-anonymity on the wire, and an outage that allows.

`02-auth-and-account.md` §1's breach check. Two criteria:

* `AC-AUTH-01.2` A known-breached password is rejected `422 password_breached`,
  "and the request to the breach service contains only a 5-character hash prefix
  (**asserted on the outbound request**)".
* `AC-AUTH-01.3` With the breach service returning 503, registration succeeds
  and `breach_check_unavailable` is incremented.

`respx` intercepts the transport rather than replacing the client, and the
parenthesis in `AC-AUTH-01.2` is why. A stubbed client asserts what we told it
to send; an intercepted transport asserts what would actually have left the
process. The criterion is specifically that the password and its full hash do
not - so the test has to see the bytes, not our intention.
"""

from __future__ import annotations

import hashlib

import httpx
import pytest
import respx

from app.core import metrics
from app.infra.breaches import PwnedPasswords, prefix_and_suffix

BASE_URL = "https://api.pwnedpasswords.com"

#: A password whose SHA-1 prefix and suffix are computed rather than pasted, so
#: the fixture cannot drift from the hash the client actually sends.
BREACHED = "password123"
CLEAN = "an-unlikely-passphrase-for-a-test-42"


def _range_body(suffix: str, count: int) -> str:
    """A response in the API's shape, plus padding entries.

    The padding is not decoration: the service adds zero-count rows when asked,
    and a parser that treated them as matches would refuse every password whose
    prefix happened to be padded.
    """
    return "\n".join(
        [
            "0000000000000000000000000000000000A:0",
            f"{suffix}:{count}",
            "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF:0",
        ]
    )


@pytest.fixture
def counter_before() -> float:
    """The metric's value now, so assertions are on the delta.

    The registry is process-wide and other tests increment this, so an absolute
    assertion would pass or fail depending on test order.
    """
    return float(metrics.breach_check_unavailable._value.get())


async def test_only_a_five_character_prefix_leaves_the_process() -> None:
    """`AC-AUTH-01.2`'s parenthesis - asserted on the outbound request.

    The password must not appear anywhere in the request, and neither must the
    35-character remainder of its hash. Checking the whole URL, headers and body
    rather than just the path, because a leak into a query parameter or a header
    is the same leak.
    """
    prefix, suffix = prefix_and_suffix(BREACHED)
    full_hash = hashlib.sha1(BREACHED.encode()).hexdigest().upper()  # noqa: S324

    async with respx.mock(base_url=BASE_URL) as mock:
        route = mock.get(f"/range/{prefix}").mock(
            return_value=httpx.Response(200, text=_range_body(suffix, 12345))
        )
        async with httpx.AsyncClient() as client:
            await PwnedPasswords(client, base_url=BASE_URL).check(BREACHED)

    assert route.called
    request = route.calls.last.request
    wire = str(request.url) + str(dict(request.headers)) + request.content.decode()

    assert prefix in str(request.url), "the prefix is what the API is indexed by"
    assert len(prefix) == 5
    assert BREACHED not in wire, "the password itself must never be sent"
    assert suffix not in wire, "the hash remainder must never be sent"
    assert full_hash not in wire, "the full hash must never be sent"


async def test_a_breached_password_is_reported_with_its_count() -> None:
    """`AC-AUTH-01.2` - the verdict, which the service turns into a 422.

    The count is carried because §1 says the rejection comes "with a count": a
    user told their password appears in 12,345 breaches acts on it differently
    from one told it is "invalid".
    """
    prefix, suffix = prefix_and_suffix(BREACHED)

    async with respx.mock(base_url=BASE_URL) as mock:
        mock.get(f"/range/{prefix}").mock(
            return_value=httpx.Response(200, text=_range_body(suffix, 12345))
        )
        async with httpx.AsyncClient() as client:
            verdict = await PwnedPasswords(client, base_url=BASE_URL).check(BREACHED)

    assert verdict.breached is True
    assert verdict.count == 12345
    assert verdict.checked is True


async def test_a_clean_password_is_not_breached() -> None:
    """A prefix whose response does not contain our suffix."""
    prefix, _ = prefix_and_suffix(CLEAN)

    async with respx.mock(base_url=BASE_URL) as mock:
        mock.get(f"/range/{prefix}").mock(
            return_value=httpx.Response(200, text="ABCDEF0000000000000000000000000000A:5")
        )
        async with httpx.AsyncClient() as client:
            verdict = await PwnedPasswords(client, base_url=BASE_URL).check(CLEAN)

    assert verdict.breached is False
    assert verdict.count == 0
    assert verdict.checked is True


async def test_a_503_allows_and_increments_the_metric(counter_before: float) -> None:
    """`AC-AUTH-01.3` - a third-party outage must not close the front door.

    `checked=False`, not `breached=False`: the caller has to be able to tell
    "we looked and it was clean" from "we could not look". §1 allows the
    registration in both cases, but only this one is worth alerting on.
    """
    prefix, _ = prefix_and_suffix(CLEAN)

    async with respx.mock(base_url=BASE_URL) as mock:
        mock.get(f"/range/{prefix}").mock(return_value=httpx.Response(503))
        async with httpx.AsyncClient() as client:
            verdict = await PwnedPasswords(client, base_url=BASE_URL).check(CLEAN)

    assert verdict.checked is False
    assert verdict.breached is False
    assert metrics.breach_check_unavailable._value.get() == counter_before + 1


async def test_a_timeout_also_allows(counter_before: float) -> None:
    """The other half of "unreachable".

    A hung service is the common outage, not a clean 503, and the two have to
    behave identically. This is the test that fails if the `except` is narrowed
    to `HTTPStatusError`.
    """
    prefix, _ = prefix_and_suffix(CLEAN)

    async with respx.mock(base_url=BASE_URL) as mock:
        mock.get(f"/range/{prefix}").mock(side_effect=httpx.ConnectTimeout("too slow"))
        async with httpx.AsyncClient() as client:
            verdict = await PwnedPasswords(client, base_url=BASE_URL).check(CLEAN)

    assert verdict.checked is False
    assert metrics.breach_check_unavailable._value.get() == counter_before + 1


async def test_a_garbled_response_does_not_raise() -> None:
    """A third party's malformed body must not 500 the registration.

    Treated as "not found in this range" rather than as an outage: the service
    answered, so it is not unavailable - it just said nothing we could use.
    """
    prefix, _ = prefix_and_suffix(CLEAN)

    async with respx.mock(base_url=BASE_URL) as mock:
        mock.get(f"/range/{prefix}").mock(
            return_value=httpx.Response(200, text="not:a:number\n\nmalformed\n")
        )
        async with httpx.AsyncClient() as client:
            verdict = await PwnedPasswords(client, base_url=BASE_URL).check(CLEAN)

    assert verdict.checked is True
    assert verdict.breached is False


async def test_padding_entries_are_not_matches() -> None:
    """A zero count is padding, not a breach with no occurrences.

    The client asks for padding (`Add-Padding: true`) so the response length
    does not reveal how many real matches a prefix has. Counting those rows
    would refuse a clean password whose suffix happened to be padded.
    """
    prefix, suffix = prefix_and_suffix(CLEAN)

    async with respx.mock(base_url=BASE_URL) as mock:
        mock.get(f"/range/{prefix}").mock(return_value=httpx.Response(200, text=f"{suffix}:0"))
        async with httpx.AsyncClient() as client:
            verdict = await PwnedPasswords(client, base_url=BASE_URL).check(CLEAN)

    assert verdict.breached is False


async def test_padding_is_requested() -> None:
    """The header is sent, so response size does not leak match counts."""
    prefix, suffix = prefix_and_suffix(CLEAN)

    async with respx.mock(base_url=BASE_URL) as mock:
        route = mock.get(f"/range/{prefix}").mock(
            return_value=httpx.Response(200, text=f"{suffix}:0")
        )
        async with httpx.AsyncClient() as client:
            await PwnedPasswords(client, base_url=BASE_URL).check(CLEAN)

    assert route.calls.last.request.headers.get("Add-Padding") == "true"


async def test_the_suffix_match_is_case_insensitive() -> None:
    """The API returns uppercase; a lowercase body must still match.

    Not a documented behaviour of the service, and that is the reason to be
    tolerant: a proxy or a future change that lowercases the body would
    otherwise silently stop detecting every breached password.
    """
    prefix, suffix = prefix_and_suffix(BREACHED)

    async with respx.mock(base_url=BASE_URL) as mock:
        mock.get(f"/range/{prefix}").mock(
            return_value=httpx.Response(200, text=f"{suffix.lower()}:99")
        )
        async with httpx.AsyncClient() as client:
            verdict = await PwnedPasswords(client, base_url=BASE_URL).check(BREACHED)

    assert verdict.breached is True
    assert verdict.count == 99
