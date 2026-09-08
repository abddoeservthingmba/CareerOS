"""T-AI-05.2 - two ways the boot refuses.

`AC-AI-05.2`: "Boot fails with a clear message when `gemini` is selected and
`GEMINI_API_KEY` is unset, and when `GOOGLE_APPLICATION_CREDENTIALS` is present
in the environment."

The two guards refuse for different reasons, and the second one is the
interesting one.

**No key.** The alternative is a container that starts healthy, passes its
readiness probe, and fails at the first user's resume upload. `FOUND-02`'s rule
- "never a default that silently disables a feature" - and the same choice
`FOUND-16`'s `build_sender` makes for email.

**An ambient credential present.** §5.2 is precise about this: boot fails "if
`GOOGLE_APPLICATION_CREDENTIALS` is set in the process environment **at all**
(its presence means an ambient Google credential exists that the AI path must
not be able to find, so it is treated as a misconfiguration and refused with an
explanatory message)."

Refusing on *presence* rather than on *use* looks paranoid until you read §5.1's
risk 2. Nobody attaches a user's OAuth token to an inference call on purpose. It
happens because a Google credential is sitting in the environment and someone
solving a different problem at speed reaches for the thing that is there. "No
code currently reads it" is a property of today's code, not of the system. The
variable being set is the loaded gun; this is the refusal to keep one on the
table.
"""

from __future__ import annotations

import pytest

from app.ai.base import ProviderNotConfigured
from app.ai.gemini import (
    AMBIENT_CREDENTIAL_VARS,
    DEFAULT_BASE_URL,
    AmbientCredentialPresent,
    assert_configuration,
)

KEY = "a-test-key-that-is-not-real"


def check(**overrides: object) -> None:
    settings: dict[str, object] = {
        "selected_providers": ["gemini"],
        "api_key": KEY,
        "base_url": DEFAULT_BASE_URL,
        "environ": {},
        "app_env": "local",
    }
    settings.update(overrides)
    assert_configuration(**settings)  # type: ignore[arg-type]


# -- guard one: the key ------------------------------------------------------


def test_gemini_selected_with_no_key_refuses_the_boot():
    """AC-AI-05.2, first half."""
    with pytest.raises(ProviderNotConfigured) as caught:
        check(api_key="")

    assert "GEMINI_API_KEY" in str(caught.value)


def test_the_message_says_why_refusing_is_better_than_starting():
    """A refusal that only says "unset" invites someone to make it a warning.
    The message has to carry the reason it is fatal."""
    with pytest.raises(ProviderNotConfigured) as caught:
        check(api_key="")

    message = str(caught.value)
    assert "Refusing to boot" in message
    assert "first resume upload" in message


def test_a_key_that_is_only_whitespace_is_no_key():
    """The shape a half-edited `.env` produces."""
    with pytest.raises(ProviderNotConfigured):
        check(api_key="   ".strip())


def test_no_key_is_fine_when_gemini_is_not_selected():
    """The control, and it matters more than usual now: ADR-011 makes `ollama`
    the local-development provider, so a developer with no Gemini key at all is
    the normal case rather than a broken one."""
    check(selected_providers=["ollama", "fake"], api_key="")


def test_a_key_is_still_required_when_gemini_serves_one_feature_of_many():
    """`AI-02` allows a per-feature provider. A single feature routed to Gemini
    is enough to need the key, and a check that looked only at
    `AI_PROVIDER_DEFAULT` would miss it."""
    with pytest.raises(ProviderNotConfigured):
        check(selected_providers=["ollama", "gemini"], api_key="")


# -- guard two: the ambient credential ---------------------------------------


def test_an_ambient_google_credential_refuses_the_boot():
    """AC-AI-05.2, second half."""
    with pytest.raises(AmbientCredentialPresent) as caught:
        check(environ={"GOOGLE_APPLICATION_CREDENTIALS": "/etc/sa.json"})

    assert "GOOGLE_APPLICATION_CREDENTIALS" in str(caught.value)


def test_the_message_explains_that_presence_is_the_problem():
    """Otherwise the obvious fix is "make the AI path ignore it", which is the
    fix that does not work: the point is that it cannot be *found*."""
    with pytest.raises(AmbientCredentialPresent) as caught:
        check(environ={"GOOGLE_APPLICATION_CREDENTIALS": "/etc/sa.json"})

    message = str(caught.value)
    assert "must not be able to find" in message
    assert "Unset it" in message
    assert "HR-6" in message


def test_it_refuses_even_when_gemini_is_not_selected():
    """Deliberate, and worth being explicit about.

    The variable is a hazard to the AI *path*, not to the Gemini adapter
    specifically. A process running Ollama with a service-account credential in
    its environment is one config change away from the failure §5.1 describes.
    """
    with pytest.raises(AmbientCredentialPresent):
        check(
            selected_providers=["ollama"],
            api_key="",
            environ={"GOOGLE_APPLICATION_CREDENTIALS": "/etc/sa.json"},
        )


def test_it_is_checked_before_the_key():
    """Order matters for the message. With no key *and* an ambient credential,
    the ambient credential is the more serious finding and the one to report -
    fixing the key first would leave the hazard in place."""
    with pytest.raises(AmbientCredentialPresent):
        check(api_key="", environ={"GOOGLE_APPLICATION_CREDENTIALS": "/etc/sa.json"})


def test_an_empty_value_is_not_a_credential():
    """`GOOGLE_APPLICATION_CREDENTIALS=` in a `.env` is a variable someone
    commented out badly, not an ambient credential. Refusing it would train
    people to work around the guard."""
    check(environ={"GOOGLE_APPLICATION_CREDENTIALS": ""})


def test_the_guarded_variables_are_the_ones_the_spec_names():
    """§5.2 names one. Listed rather than inlined so adding a second - say
    `GCLOUD_PROJECT` with an attached credential - is a visible decision."""
    assert AMBIENT_CREDENTIAL_VARS == ("GOOGLE_APPLICATION_CREDENTIALS",)


def test_an_unrelated_google_variable_is_not_refused():
    """The guard is about credentials, not about the word "Google". Refusing
    `GOOGLE_OAUTH_CLIENT_ID` would refuse every deployment that has sign-in
    configured, which is all of them."""
    check(environ={"GOOGLE_OAUTH_CLIENT_ID": "an-oauth-client-id"})


# -- both guards, and the base URL -------------------------------------------


def test_a_valid_configuration_passes():
    """The control. A check that raised unconditionally would satisfy every
    assertion above and stop the product booting at all."""
    check()


def test_the_base_url_is_validated_at_the_same_time():
    """`AC-AI-05.7`'s check runs in the same startup function, so there is one
    place a deployment is judged rather than three."""
    from app.ai.gemini import BaseUrlNotAllowed

    with pytest.raises(BaseUrlNotAllowed):
        check(base_url="https://gemini-proxy.internal.example")


def test_localhost_is_refused_in_production():
    """A local base URL in production is either a proxy nobody declared or a
    leftover from a test - and either way it sees every resume."""
    from app.ai.gemini import BaseUrlNotAllowed

    with pytest.raises(BaseUrlNotAllowed, match="production"):
        check(base_url="http://127.0.0.1:8080", app_env="prod")


def test_localhost_is_allowed_locally():
    """The record-and-replay tests need it, and a local proxy on a developer's
    own machine is not the threat the allowlist exists for."""
    check(base_url="http://127.0.0.1:8080", app_env="local")


def test_the_default_base_url_is_the_developer_api():
    """§5.2: "The adapter calls the Gemini Developer API endpoint only." The
    default is that endpoint, so a deployment that sets nothing is already
    correct."""
    assert DEFAULT_BASE_URL == "https://generativelanguage.googleapis.com"
    check(base_url=DEFAULT_BASE_URL)
