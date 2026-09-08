"""T-AI-05.7 - a base URL is a host we send résumés to.

`AC-AI-05.7`: "A configured base URL outside the allowlist fails at startup
(blocks an accidental proxy that could exfiltrate prompts)."

The parenthetical is the whole justification and it is easy to under-read. A
configurable base URL is a **configurable exfiltration target**. Whatever sits
at that address sees, in plain text: someone's employment history, the wording
of their resume, and every job they are considering. There is no encryption
between us and it, because we are the ones addressing it.

The realistic route in is not an attack. It is a corporate egress proxy added to
`.env` to make a firewall happy, a debugging proxy left set after an afternoon
of packet-watching, or a copy-pasted staging value. None of those look
suspicious in a diff, and all of them are silent — the calls succeed.

**Validated by host, not by prefix.** A prefix check accepts
`https://generativelanguage.googleapis.com.attacker.example`, which is a
different site wearing a reassuring name. That is a two-character diff from
correct and it is the specific trick this exists to stop.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.ai.gemini import (
    ALLOWED_HOSTS,
    DEFAULT_BASE_URL,
    BaseUrlNotAllowed,
    GeminiProvider,
    check_base_url,
)

MODELS: dict[str, Any] = {
    "model_fast": "gemini-3.5-flash-lite",
    "model_quality": "gemini-3.8-flash",
    "embedding_model": "gemini-embedding-001",
}


# -- what is allowed ---------------------------------------------------------


def test_the_developer_api_is_allowed():
    assert check_base_url(DEFAULT_BASE_URL) == DEFAULT_BASE_URL


def test_a_trailing_slash_is_tolerated():
    """The shape a `.env` value takes when someone copies it from a browser."""
    assert check_base_url("https://generativelanguage.googleapis.com/") == DEFAULT_BASE_URL


def test_a_local_address_is_allowed_for_the_replay_tests():
    """§5.2: "The base URL is configurable for testing". A local recorder is
    what makes a request-shape test possible without a key."""
    assert check_base_url("http://127.0.0.1:8080") == "http://127.0.0.1:8080"
    assert check_base_url("http://localhost:8080") == "http://localhost:8080"


def test_the_allowlist_is_short_and_says_what_is_on_it():
    """Three entries: the provider, and two spellings of this machine. An
    allowlist that grew would be a decision, and it should look like one."""
    assert (
        frozenset({"generativelanguage.googleapis.com", "127.0.0.1", "localhost"}) == ALLOWED_HOSTS
    )


# -- what is refused ---------------------------------------------------------


def test_a_lookalike_host_is_refused():
    """The reason validation is by host rather than by prefix.

    `generativelanguage.googleapis.com.attacker.example` starts with the right
    string and is a completely different server. A `startswith` check passes it.
    """
    with pytest.raises(BaseUrlNotAllowed) as caught:
        check_base_url("https://generativelanguage.googleapis.com.attacker.example")

    assert "attacker.example" in str(caught.value)


@pytest.mark.parametrize(
    "url",
    [
        "https://gemini-proxy.internal.example",
        "https://api.openai.com",
        "https://generativelanguage.googleapis.com.evil.test/v1beta",
        "https://user:pass@generativelanguage.googleapis.com.evil.test",
        "https://198.51.100.7",
    ],
)
def test_a_remote_host_off_the_allowlist_is_refused(url: str):
    """Each of these is a plausible line in a `.env`, and each one sees every
    resume that passes through it."""
    with pytest.raises(BaseUrlNotAllowed):
        check_base_url(url)


def test_the_userinfo_trick_does_not_smuggle_a_host():
    """`https://generativelanguage.googleapis.com@evil.test` has a *hostname* of
    `evil.test`; everything before the `@` is userinfo. Parsing rather than
    string-matching is what makes this a refusal instead of a pass."""
    with pytest.raises(BaseUrlNotAllowed):
        check_base_url("https://generativelanguage.googleapis.com@evil.test")


def test_plaintext_http_to_a_remote_host_is_refused():
    """Even to a host that would otherwise be allowed, if one ever were. Resume
    text over cleartext HTTP is readable by every hop in between."""
    with pytest.raises(BaseUrlNotAllowed, match="plaintext"):
        check_base_url("http://generativelanguage.googleapis.com")


@pytest.mark.parametrize(
    "url",
    ["", "generativelanguage.googleapis.com", "ftp://x.test", "file:///etc/passwd", "//evil.test"],
)
def test_something_that_is_not_an_http_url_is_refused(url: str):
    """A missing scheme is the commonest malformed value, and `//evil.test`
    parses as a protocol-relative URL that a naive check would let through."""
    with pytest.raises(BaseUrlNotAllowed):
        check_base_url(url)


def test_the_message_says_what_is_at_stake():
    """A refusal reading "invalid base URL" invites someone to add their host to
    the allowlist without thinking. The message has to say what that host would
    then be able to read."""
    with pytest.raises(BaseUrlNotAllowed) as caught:
        check_base_url("https://gemini-proxy.internal.example")

    message = str(caught.value)
    assert "exfiltration" in message
    assert "resume" in message
    assert "generativelanguage.googleapis.com" in message, "it should name what is allowed"


# -- the adapter refuses at construction -------------------------------------


def test_the_adapter_cannot_be_built_with_a_bad_base_url():
    """Checked in `__init__` as well as at startup.

    Startup validation is the primary control, but an adapter constructed
    directly - by a test, by a script, by a future feature - must not be able to
    skip it. There is no path to an unvalidated base URL.
    """
    with pytest.raises(BaseUrlNotAllowed):
        GeminiProvider("k", base_url="https://evil.test", **MODELS)


def test_the_adapter_defaults_to_the_developer_api():
    """A deployment that sets nothing is already correct."""
    provider = GeminiProvider("k", **MODELS)

    assert provider._base_url == DEFAULT_BASE_URL  # noqa: SLF001


def test_the_ollama_adapter_has_its_own_stricter_rule():
    """ADR-011's adapter allows only local hosts, and for a different reason:
    Ollama has no authentication at all, so a remote one is an unauthenticated
    inference endpoint as well as a plaintext channel."""
    from app.ai.ollama import RemoteOllamaRefused
    from app.ai.ollama import check_base_url as ollama_check

    assert ollama_check("http://127.0.0.1:11434") == "http://127.0.0.1:11434"
    with pytest.raises(RemoteOllamaRefused, match="no authentication"):
        ollama_check("http://10.0.0.5:11434")
    with pytest.raises(RemoteOllamaRefused):
        ollama_check("https://generativelanguage.googleapis.com")
