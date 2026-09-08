"""`SkillName` - `FOUND-03`.

`01-foundations.md` §3: "`SkillName` is a canonical lowercase slug. A raw string
becomes one only via `profile.canonicalize()` (`03-profile.md` §4). Comparing
raw skill strings anywhere is a defect."

This module holds the *type* and its shape rule. The alias table, the
normalization pipeline and the fuzzy fallback are `PROF-06`, phase P2, and live
in `profile/skills.py` so that jobs and profiles canonicalize through one
implementation. Keeping the type here lets every module name a canonical skill
in a signature before that module exists.
"""

from __future__ import annotations

import re
from typing import NewType

SkillName = NewType("SkillName", str)

# A canonical slug: lowercase alphanumerics separated by single hyphens or dots.
# Dots survive because "node.js" and "asp.net" are the canonical spellings.
CANONICAL = re.compile(r"^[a-z0-9]+(?:[.+#-][a-z0-9]+)*$")


class NotCanonical(ValueError):
    """A raw skill string was used where a canonical one is required."""


def is_canonical(value: str) -> bool:
    return bool(CANONICAL.fullmatch(value))


def as_skill_name(value: str) -> SkillName:
    """Assert that `value` is already canonical and type it as such.

    Deliberately not a normalizer. Anything that needs to *turn* a raw string
    into a canonical one goes through `profile.canonicalize`, which owns the
    alias table; a second, quieter normalizer here is exactly how "ReactJS" and
    "react" end up as two skills.
    """
    if not is_canonical(value):
        raise NotCanonical(
            f"{value!r} is not a canonical skill slug; "
            "canonicalize it through profile.canonicalize (PROF-06)"
        )
    return SkillName(value)
