"""T-AI-02.5 - resolution fails at startup, not at first call.

`AC-AI-02.5`: "`get_llm` for a feature with no override and no default
configured raises at startup, not at first call."

The distinction is the whole point: a provider misconfiguration should break the
deploy, not the first user who uploads a resume.
"""

from __future__ import annotations

import pytest

from app.ai.registry import RegistryError, build

from ..unit.test_config_failfast import COMPLETE_ENV
from ..unit.test_config_failfast import build as settings_for


def test_no_default_provider_raises_at_build_time():
    """AC-AI-02.5."""
    settings = settings_for(
        {**COMPLETE_ENV, "AI_PROVIDER_DEFAULT": "", "AI_EMBEDDING_PROVIDER": "fake"}
    )
    with pytest.raises(RegistryError, match="AI_PROVIDER_DEFAULT"):
        build(settings)


def test_a_whitespace_only_default_is_also_refused():
    settings = settings_for(
        {**COMPLETE_ENV, "AI_PROVIDER_DEFAULT": "   ", "AI_EMBEDDING_PROVIDER": "fake"}
    )
    with pytest.raises(RegistryError):
        build(settings)


def test_the_error_names_the_feature_and_the_provider():
    """A boot failure must say which feature and which provider, or the operator
    is reading source at 2am."""
    settings = settings_for(
        {
            **COMPLETE_ENV,
            "AI_PROVIDER_DEFAULT": "fake",
            "AI_EMBEDDING_PROVIDER": "fake",
            "AI_PROVIDER_PACK_GENERATE": "nonesuch",
        }
    )
    with pytest.raises(RegistryError) as caught:
        build(settings)
    message = str(caught.value)
    assert "pack_generate" in message
    assert "nonesuch" in message


def test_a_valid_configuration_builds():
    settings = settings_for(
        {**COMPLETE_ENV, "AI_PROVIDER_DEFAULT": "fake", "AI_EMBEDDING_PROVIDER": "fake"}
    )
    assert build(settings) is not None
