"""T-AI-02.4 - changing the embedding model is a migration, not a config flip.

`AC-AI-02.4`: "Starting with a changed embedding model and no migration flag
exits non-zero with a message naming both models; with the flag, it starts and
`ai.reembed_all` is enqueued."

`05-ai-layer.md` §2 states the reason: switching requires re-embedding every
profile and job. Without the guard the product would start comparing vectors
from two different models, which produces plausible numbers and wrong matches -
the worst kind of failure this codebase can have.
"""

from __future__ import annotations

import pytest

from app.ai.fake import FAKE_EMBEDDING_MODEL
from app.ai.registry import EmbeddingMigrationRequired, build, migration_requested

from ..unit.test_config_failfast import COMPLETE_ENV
from ..unit.test_config_failfast import build as settings_for


def settings(migration: str = ""):
    return settings_for(
        {
            **COMPLETE_ENV,
            "AI_PROVIDER_DEFAULT": "fake",
            "AI_EMBEDDING_PROVIDER": "fake",
            "AI_EMBEDDING_MIGRATION": migration,
        }
    )


def test_a_changed_model_without_the_flag_refuses_to_start():
    """AC-AI-02.4, first half - and the message names both models."""
    with pytest.raises(EmbeddingMigrationRequired) as caught:
        build(settings(), stored_embedding_model="text-embedding-004")

    message = str(caught.value)
    assert "text-embedding-004" in message
    assert FAKE_EMBEDDING_MODEL in message
    assert "AI_EMBEDDING_MIGRATION" in message


def test_the_same_model_starts_normally():
    registry = build(settings(), stored_embedding_model=FAKE_EMBEDDING_MODEL)
    assert registry.embedding_model == FAKE_EMBEDDING_MODEL


def test_a_first_boot_with_nothing_stored_starts():
    """No stored model means nothing has been embedded yet."""
    assert build(settings(), stored_embedding_model=None) is not None


def test_the_flag_permits_the_change():
    """AC-AI-02.4, second half - "with the flag, it starts"."""
    registry = build(settings("allow"), stored_embedding_model="text-embedding-004")
    assert registry.embedding_model == FAKE_EMBEDDING_MODEL


def test_the_flag_signals_that_reembedding_must_be_enqueued():
    """The other half of "and `ai.reembed_all` is enqueued".

    The task itself is `FOUND-10`'s queue, so what is asserted here is the
    decision: starting with the flag *and* a differing stored model means a
    re-embed is required. The enqueue is wired in the app factory and asserted
    by `tests/integration/test_worker_restart.py` once ARQ exists.
    """
    assert migration_requested(settings("allow"), FAKE_EMBEDDING_MODEL, "text-embedding-004")
    # Not required when nothing changed, even with the flag set.
    assert not migration_requested(settings("allow"), FAKE_EMBEDDING_MODEL, FAKE_EMBEDDING_MODEL)
    # Not required on a first boot.
    assert not migration_requested(settings("allow"), FAKE_EMBEDDING_MODEL, None)


def test_the_flag_is_not_a_way_to_ignore_the_problem():
    """Without the flag the guard holds however many times it is hit."""
    for _ in range(3):
        with pytest.raises(EmbeddingMigrationRequired):
            build(settings(), stored_embedding_model="something-else")
