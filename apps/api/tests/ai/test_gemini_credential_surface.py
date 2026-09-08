"""T-AI-05.4 - the adapter has nowhere to put a credential it should not have.

`AC-AI-05.4`: "The Gemini adapter's constructor accepts only a key string; a
test asserts it has no attribute or parameter capable of holding a token, a
credentials object, or a service-account path, and that no method reads
`os.environ`."

This is the same move as `LLMRequest` having no `file` field under HR-8, and it
is worth naming because it is the reason the test is introspective rather than
behavioural. **A rule enforced by there being nowhere to put the thing survives
a refactor; a rule enforced by review survives until the reviewer is busy.**

The specific failure §5.1 names as risk 2:

> Google OAuth is used in this product for *sign-in* (`AUTH-02`). Sign-in and
> inference both say "Google". A future change that reached for an available
> Google credential in the AI path — a user's OAuth token, application default
> credentials, a service account with broad scopes — would be a serious privacy
> failure: it would attach a user's identity to inference calls and could
> implicate their consumer account.

Nobody would write that on purpose. It happens because a Google credential is
*right there* — in the process environment, in an ambient metadata service, in a
sign-in flow two modules away — and an adapter that can accept one will
eventually be handed one by somebody solving a different problem at speed.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import re
from typing import Any

import pytest

from app.ai.gemini import GeminiProvider

MODELS: dict[str, Any] = {
    "model_fast": "gemini-3.5-flash-lite",
    "model_quality": "gemini-3.8-flash",
    "embedding_model": "gemini-embedding-001",
}
KEY = "a-test-key-that-is-not-real"

#: Words that name a credential this adapter must not be able to accept. Matched
#: against parameter and attribute names, so a field called `oauth_token` or
#: `service_account_json` fails whatever its type says.
FORBIDDEN_WORDS = (
    "token",
    "credential",
    "service_account",
    "serviceaccount",
    "oauth",
    "adc",
    "bearer",
    "assertion",
    "id_token",
    "access_token",
    "refresh",
    "principal",
    "impersonat",
)


def source() -> str:
    return pathlib.Path(inspect.getfile(GeminiProvider)).read_text(encoding="utf-8")


# -- the constructor ---------------------------------------------------------


def test_the_only_credential_parameter_is_a_key_string():
    """AC-AI-05.4, first clause."""
    signature = inspect.signature(GeminiProvider.__init__)
    parameters = signature.parameters

    assert "api_key" in parameters
    assert parameters["api_key"].annotation == "str"


def test_no_constructor_parameter_can_hold_a_credential():
    """Every parameter name, against the forbidden list.

    By name rather than by type, because the type is the easy half. A parameter
    annotated `Any` and called `creds` is exactly what a hurried change adds.
    """
    offenders = [
        name
        for name in inspect.signature(GeminiProvider.__init__).parameters
        if any(word in name.lower() for word in FORBIDDEN_WORDS)
    ]

    assert offenders == [], f"these parameters could hold a credential: {offenders}"


def test_no_constructor_parameter_is_a_path():
    """A service-account file is passed as a path, and a `Path` parameter is how
    it would arrive without ever being called a credential."""
    for name, parameter in inspect.signature(GeminiProvider.__init__).parameters.items():
        annotation = str(parameter.annotation)
        assert "Path" not in annotation, f"{name} takes a {annotation}"


def test_the_key_is_required():
    """A default of `""` would let an unconfigured adapter be constructed and
    fail at the first user's resume instead of at boot."""
    from app.ai.base import ProviderNotConfigured

    with pytest.raises(ProviderNotConfigured):
        GeminiProvider("", **MODELS)


# -- the instance ------------------------------------------------------------


def test_no_public_attribute_holds_a_credential():
    """AC-AI-05.4's "no attribute ... capable of holding" a credential."""
    instance = GeminiProvider(KEY, **MODELS)
    offenders = [
        name
        for name in dir(instance)
        if not name.startswith("__") and any(word in name.lower() for word in FORBIDDEN_WORDS)
    ]

    assert offenders == [], f"these attributes could hold a credential: {offenders}"


def test_the_key_is_not_reachable_by_a_public_name():
    """Private-by-mangling, not by convention.

    A `self._key` would be reachable as `provider._key` from a debug endpoint,
    a `repr` helper or a Sentry frame; name mangling makes the obvious accesses
    fail. This is defence in depth behind `core/redaction.py`, not instead of
    it.
    """
    instance = GeminiProvider(KEY, **MODELS)

    for name in ("key", "api_key", "_key", "_api_key"):
        assert getattr(instance, name, None) != KEY, f"the key is readable as .{name}"


def test_the_key_does_not_appear_in_the_repr():
    """`AC-FOUND-02.2`'s rule, applied here: settings and objects end up in
    crash reports."""
    instance = GeminiProvider(KEY, **MODELS)

    assert KEY not in repr(instance)
    assert KEY not in str(instance)


def test_the_key_does_not_appear_in_the_instance_dict():
    """The route a naive serialiser takes. `vars(provider)` is what a debug
    dump, a pickle and a "just log the object" all reach for."""
    instance = GeminiProvider(KEY, **MODELS)

    assert KEY not in str(vars(instance))


# -- the environment ---------------------------------------------------------


def test_no_method_reads_the_environment():
    """AC-AI-05.4's last clause, by AST rather than by grep.

    A grep for `os.environ` misses `getenv`, `environ.get`, and
    `from os import environ`. Parsing catches all of them, and catches them in a
    docstring exactly never - which matters here, because this module's
    docstrings talk about `GOOGLE_APPLICATION_CREDENTIALS` at length.
    """
    tree = ast.parse(source())
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
            offenders.append(f"line {node.lineno}: reads os.{node.attr}")
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            names = [alias.name for alias in node.names]
            if {"environ", "getenv"} & set(names):
                offenders.append(f"line {node.lineno}: imports os.{names}")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "os":
                    offenders.append(f"line {node.lineno}: imports os")

    assert offenders == [], (
        "the Gemini adapter must have no path to the environment; an ambient "
        "Google credential lives there:\n" + "\n".join(offenders)
    )


def test_the_startup_check_takes_the_environment_as_an_argument():
    """`assert_configuration` has to look at the environment to refuse an
    ambient credential - so it is *given* the mapping rather than reading one.

    Otherwise the single function whose job is to detect an ambient credential
    would be the single code path in the module able to reach one, which is a
    neat way to defeat the whole control.
    """
    from app.ai.gemini import assert_configuration

    assert "environ" in inspect.signature(assert_configuration).parameters


def test_no_google_auth_library_is_imported():
    """`AC-AI-05.3`'s import contract, asserted here too.

    `.importlinter` cannot forbid a subpackage of an external package, so
    `google.auth` and `google.oauth2` are checked by AST - and this file is
    where a reader of the credential surface would look for the answer.
    """
    tree = ast.parse(source())
    forbidden = ("google.auth", "google.oauth2", "googleapiclient", "authlib")
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if any(node.module.startswith(name) for name in forbidden):
                offenders.append(f"line {node.lineno}: from {node.module}")
        elif isinstance(node, ast.Import):
            offenders.extend(
                f"line {node.lineno}: import {alias.name}"
                for alias in node.names
                if any(alias.name.startswith(name) for name in forbidden)
            )

    assert offenders == [], "\n".join(offenders)


# -- the key on the wire -----------------------------------------------------


def test_the_key_travels_in_a_header_not_a_query_string():
    """A URL is recorded by every proxy, load balancer and access log between
    here and the provider. §14 forbids a credential reaching a log, and a key in
    a query string reaches all of them."""
    text = source()

    assert "x-goog-api-key" in text
    assert not re.search(r"[?&]key=", text), "the key is in a query string"


def test_there_is_no_client_construction_path():
    """The transport is injected. An adapter that built its own HTTP client
    would be an adapter with a network path that startup validation never
    saw - and the obvious way to configure such a client is from the
    environment."""
    text = source()

    for constructor in ("httpx.Client", "httpx.AsyncClient", "requests.Session", "urlopen"):
        assert constructor not in text, f"{constructor} is constructed in the adapter"
