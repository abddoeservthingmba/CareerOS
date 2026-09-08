"""The tracker module's public API.

`01-foundations.md` §5: "`__all__` is the contract." A module's `__init__.py`
exports only its service class, its DTOs from `schemas.py`, its published event
types, and its exceptions - never a Beanie document, never a repository.
"""

from app.modules.tracker.service import TrackerService

__all__ = ["TrackerService"]
