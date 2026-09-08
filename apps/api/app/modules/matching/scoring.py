"""The scorer's input type - HR-3, `AC-DATA-02.5`.

`17-data-model.md` §2.8: "`rationale` is a sibling of `explain`, not a field
inside it. HR-3: the scorer reads `explain` and `components`; it must be
structurally incapable of reading `rationale`. A test asserts the scoring
function's input type has no rationale field."

**Why a separate type rather than a rule.** HR-3 says a model's prose must never
influence a score. Written as a convention - "don't read `rationale` in the
scorer" - it holds until someone adds a feature that would be improved by
reading it, which is a plausible and well-intentioned change: the rationale
often contains a real observation the arithmetic missed. The type is what makes
that change impossible to write by accident. There is no attribute to reach.

This file holds only the boundary. The weights, the component arithmetic and the
incremental rescoring are `MATCH-01`..`MATCH-05` in phase P3; they will import
`ScoreInput` and take nothing else, which is what keeps the guarantee once the
scorer exists rather than only while it does not.

`01-foundations.md` §5 permits `scoring.py` as a pure-logic file alongside the
nine required ones. It imports no `fastapi`, no Beanie document, and nothing
from another module - so the property is checkable by `lint-imports` as well as
by the introspection test.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.modules.matching.models import Explain, ScoreComponents

#: The field names a scorer input must never carry, in any nesting. Named here
#: rather than only in the test so that the prohibition lives beside the type
#: it constrains - a test in another directory is easy to read as someone
#: else's concern.
FORBIDDEN_FIELDS = frozenset(
    {"rationale", "rationale_model", "rationale_prompt_version", "rationale_at"}
)


@dataclass(frozen=True, slots=True)
class ScoreInput:
    """Everything the scoring function may see.

    Frozen because a scorer that mutated its input would make a rescore depend
    on evaluation order, and `MATCH-05`'s incremental rescoring runs over a
    candidate set in an unspecified one.

    Note what is absent: no `MatchScore`, no rationale in any form, and no
    provider or model name. A scorer that could see which model wrote a
    rationale could branch on it, which is the same violation one step removed.
    """

    user_id: str
    job_id: str
    profile_version: int
    weights_version: str
    scorer_build: str
    components: ScoreComponents = field(default_factory=ScoreComponents)
    explain: Explain = field(default_factory=Explain)
    embedding_sim: float | None = None


def input_field_names() -> frozenset[str]:
    """Every field name reachable from `ScoreInput`, one level of nesting deep.

    Used by `AC-DATA-02.5`'s test. Computed here rather than in the test so
    that the answer comes from the type itself - a test that hand-listed the
    fields would keep passing after a field was added.
    """
    names: set[str] = set(ScoreInput.__dataclass_fields__)
    for nested in (ScoreComponents, Explain):
        names |= set(nested.model_fields)
    return frozenset(names)


__all__ = ["FORBIDDEN_FIELDS", "ScoreInput", "input_field_names"]
