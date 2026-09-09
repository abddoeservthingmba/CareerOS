"""The auth module's public API.

`01-foundations.md` §5: "`__all__` is the contract." A module's `__init__.py`
exports only its service class, its DTOs from `schemas.py`, its published event
types, and its exceptions - never a Beanie document, never a repository.

`EmailAlreadyRegistered` is deliberately absent: it is defined in
`repository.py`, and `AC-FOUND-04.2` forbids exporting a persistence name. It
is also not a fact a caller needs - §1's registration is enumeration-safe, so
"this address is taken" never reaches a response.
"""

from app.modules.auth.events import UserDeletionRequested, UserRegistered
from app.modules.auth.schemas import RegisterRequest, RegisterResponse
from app.modules.auth.service import AuthService, ConsentVersionStale, PasswordBreached

__all__ = [
    "AuthService",
    "ConsentVersionStale",
    "PasswordBreached",
    "RegisterRequest",
    "RegisterResponse",
    "UserDeletionRequested",
    "UserRegistered",
]
