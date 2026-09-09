"""T-AUTH-09.4 - a forged forwarding header does not move the blame.

`AC-AUTH-09.4`: "A request carrying a forged `X-Forwarded-For` from a
non-Cloudflare source is limited by its socket IP."

§9's rule is that `CF-Connecting-IP` is believed "only when the request arrives
from a Cloudflare address; otherwise from the socket. A spoofable
`X-Forwarded-For` is never trusted."

`ratelimit.client_ip` generalises that one step - the trusted set is
`TRUSTED_PROXY_CIDRS` rather than a hardcoded vendor - because on a managed
container host every request arrives from the platform's proxy and the socket
address is identical for every user, which turns the per-IP dimension into a
single bucket that locks out everyone. The criterion's actual requirement is
unchanged and is the first test below: **trust nothing by default**.
"""

from __future__ import annotations

from app.core.ratelimit import client_ip, parse_cidrs

ATTACKER = "203.0.113.50"
CLAIMED = "10.9.9.9"


def test_forged_forwarded_for_from_an_untrusted_peer_is_ignored() -> None:
    """`AC-AUTH-09.4`, and the default posture.

    No trusted CIDRs configured, which is the shipped default. The header is a
    lie and the socket address is the only fact.
    """
    resolved = client_ip(
        peer=ATTACKER,
        forwarded_for=f"{CLAIMED}, 172.16.0.1",
        cf_connecting_ip=CLAIMED,
        trusted_cidrs=(),
    )
    assert resolved == ATTACKER


def test_cf_connecting_ip_from_an_untrusted_peer_is_ignored() -> None:
    """The same rule, for the Cloudflare header specifically.

    `CF-Connecting-IP` is not privileged by its name. Anyone can set it; what
    makes it credible is arriving from Cloudflare.
    """
    resolved = client_ip(
        peer=ATTACKER,
        forwarded_for=None,
        cf_connecting_ip="198.51.100.1",
        trusted_cidrs=(),
    )
    assert resolved == ATTACKER


def test_cf_connecting_ip_is_believed_from_a_trusted_peer() -> None:
    """Behind Cloudflare, the edge's header is the client."""
    resolved = client_ip(
        peer="172.16.0.5",
        forwarded_for=None,
        cf_connecting_ip="198.51.100.1",
        trusted_cidrs=parse_cidrs("172.16.0.0/12"),
    )
    assert resolved == "198.51.100.1"


def test_forwarded_for_is_walked_from_the_right() -> None:
    """A client-supplied prefix cannot forge an address.

    A proxy *appends*, so the leftmost entries are whatever the client sent.
    Here the client claimed `1.1.1.1` and the trusted proxy appended the address
    it actually saw. Walking from the right and stopping at the first untrusted
    hop yields that one; walking from the left would yield the client's lie.
    """
    resolved = client_ip(
        peer="172.16.0.5",
        forwarded_for="1.1.1.1, 198.51.100.7, 172.16.0.5",
        cf_connecting_ip=None,
        trusted_cidrs=parse_cidrs("172.16.0.0/12"),
    )
    assert resolved == "198.51.100.7"


def test_a_malformed_hop_ends_the_walk() -> None:
    """Garbage is not a free pass.

    Without this, a client sends `X-Forwarded-For: not-an-ip` and the walk keeps
    going past it, which is a way to reach an address the client chose.
    """
    resolved = client_ip(
        peer="172.16.0.5",
        forwarded_for="198.51.100.7, not-an-ip, 172.16.0.5",
        cf_connecting_ip=None,
        trusted_cidrs=parse_cidrs("172.16.0.0/12"),
    )
    # The walk stops at the malformed entry and falls back to the peer, rather
    # than reaching `198.51.100.7` on the far side of it.
    assert resolved == "172.16.0.5"


def test_all_hops_trusted_falls_back_to_the_peer() -> None:
    """Nothing untrusted in the chain: the peer is the most specific address."""
    resolved = client_ip(
        peer="172.16.0.5",
        forwarded_for="172.16.0.9, 172.16.0.5",
        cf_connecting_ip=None,
        trusted_cidrs=parse_cidrs("172.16.0.0/12"),
    )
    assert resolved == "172.16.0.5"


def test_missing_peer_is_a_shared_bucket_not_an_exemption() -> None:
    """An ASGI scope with no client still gets limited.

    The safe direction: `"unknown"` is one shared bucket, so a transport with no
    address is throttled together rather than let through unmetered.
    """
    assert client_ip(peer=None, forwarded_for=None, cf_connecting_ip=None, trusted_cidrs=()) == (
        "unknown"
    )


def test_unparseable_cidrs_are_dropped_rather_than_fatal() -> None:
    """A typo in one CIDR must not take the API down at boot.

    And the fallback is safe: an entry that does not parse is a proxy that is
    not trusted, which means the socket address.
    """
    networks = parse_cidrs("172.16.0.0/12, nonsense, 10.0.0.0/8")

    assert len(networks) == 2
    assert (
        client_ip(
            peer=ATTACKER,
            forwarded_for=CLAIMED,
            cf_connecting_ip=None,
            trusted_cidrs=networks,
        )
        == ATTACKER
    )
