"""The auth module's public surface - `01-foundations.md` §5.

`AC-FOUND-05.1`: a scaffolded module passes its own test without edits. This
asserts the anatomy rather than behaviour, so it stays meaningful as the module
fills in rather than being deleted on the first real commit.

**It used to assert `__all__ == ["AuthService"]`.** That is a pin, not an
anatomy check: it broke the moment `AUTH-01` exported the DTOs and events §5
says belong there, which is the opposite of "stays meaningful as the module
fills in". What §5 actually states is a *rule about categories* - a module
exports "its service class, its DTOs from `schemas.py`, its published event
types, and its exceptions - never a Beanie document, never a repository" - so
that is what is asserted here, and it will hold for every requirement this
module gains.
"""

from __future__ import annotations

import app.modules.auth as module
from app.modules.auth import events as events_module
from app.modules.auth import models as models_module
from app.modules.auth import repository as repository_module
from app.modules.auth import schemas as schemas_module
from app.modules.auth import service as service_module


def _public_names(source: object) -> set[str]:
    return {name for name in vars(source) if not name.startswith("_")}


def test_the_service_is_exported():
    """The one name every module must expose."""
    assert "AuthService" in module.__all__
    assert hasattr(module, "AuthService")


def test_every_export_resolves():
    """An `__all__` naming something absent is a broken import for a caller."""
    for name in module.__all__:
        assert hasattr(module, name), f"__all__ names {name}, which is not importable"


def test_the_export_list_is_sorted_and_unique():
    """Housekeeping, and it makes a duplicate export visible in review."""
    assert module.__all__ == sorted(set(module.__all__))


def test_no_document_or_repository_is_exported():
    """§5 - "Never a Beanie document, never a repository".

    Checked against what those two files actually define rather than against a
    naming convention: `User` and `EmailToken` end in neither `Document` nor
    `Repository`, so a suffix check would let the most important leak through.
    """
    persistence = _public_names(models_module) | _public_names(repository_module)
    leaked = sorted(set(module.__all__) & persistence)

    assert leaked == [], f"auth exports persistence names: {leaked}"


def test_every_export_comes_from_a_permitted_file():
    """§5's categories, positively.

    The service, its DTOs, its published events and its exceptions - and
    nothing from anywhere else. This is what notices an export added from
    `models.py` even if that name is also defined somewhere permitted.
    """
    permitted = (
        _public_names(service_module) | _public_names(schemas_module) | _public_names(events_module)
    )
    stray = sorted(set(module.__all__) - permitted)

    assert stray == [], f"auth exports names from no permitted file: {stray}"


def test_the_published_events_are_exported():
    """A subscriber has to be able to name the event it handles.

    `01-foundations.md` §9's table is the registry; this is the import path a
    consumer would use. Both auth events are exported even though neither has a
    consumer in R1, because the alternative is discovering the omission from
    inside the first module that needs one.
    """
    assert "UserRegistered" in module.__all__
    assert "UserDeletionRequested" in module.__all__
