"""Placeholder test for the notifications module.

`AC-FOUND-05.1`: a scaffolded module passes its own test without edits. This
asserts the anatomy rather than behaviour, so it stays meaningful as the module
fills in rather than being deleted on the first real commit.
"""

from __future__ import annotations

import app.modules.notifications as module


def test_the_public_surface_is_the_service():
    assert module.__all__ == ["NotificationsService"]
    assert hasattr(module, "NotificationsService")


def test_no_document_or_repository_is_exported():
    """§5 - "Never a Beanie document, never a repository"."""
    for name in module.__all__:
        assert not name.endswith("Repository")
        assert not name.endswith("Document")
