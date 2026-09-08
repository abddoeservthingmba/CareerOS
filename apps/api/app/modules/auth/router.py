"""HTTP for the auth module.

Thin: validate -> call one service method -> map to a response. A route function
is at most ~15 lines and contains no `if` on business state
(`AC-FOUND-05.2`).
"""

from __future__ import annotations
