"""ARQ tasks for the notifications module.

Thin wrappers that call service methods. A task receives **IDs and small
scalars only** (`01-foundations.md` §10), and each states its idempotency key in
a docstring line beginning `Idempotency key:`.
"""

from __future__ import annotations
