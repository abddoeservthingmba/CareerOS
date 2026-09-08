"""Use cases for the apply module - the ONLY place business rules live.

A service method never touches `fastapi`, never builds a Mongo filter, and never
calls an HTTP client directly; it calls an `infra` or `ai` interface.
"""

from __future__ import annotations


class ApplyService:
    """Business rules for apply."""
