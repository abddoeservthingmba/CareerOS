"""T-DATA-02.5 - the scorer cannot see the model's prose.

`AC-DATA-02.5`: "`match_scores.rationale` is not reachable from the scoring
function's input type (HR-3)."

`17-data-model.md` §2.8 states it as a structural requirement rather than a
rule: "the scorer reads `explain` and `components`; it must be **structurally
incapable** of reading `rationale`."

**Why structural.** HR-3 forbids a model's prose from influencing a score, and
HR-11 forbids model output from steering the program at all. Written as a
convention - "don't read `rationale` in the scorer" - it holds until someone has
a good reason, and there is a good reason: the rationale frequently contains a
real observation the arithmetic missed, and using it would make the scores
better on the day it was added. It would also make every score unreproducible,
because the prose that produced it is not deterministic and is not stored
alongside the weights.

So the guarantee is a type with no such attribute. This file asserts that by
introspection, in both directions:

* nothing named `rationale*` is reachable from `ScoreInput`, at the top level or
  one level of nesting;
* `ScoreInput` still carries `components` and `explain`, because a type that
  guaranteed the first by containing nothing would pass and be useless.

The second half is the part that would rot silently. A refactor that reduced
`ScoreInput` to `(user_id, job_id)` would satisfy `AC-DATA-02.5` perfectly and
leave the scorer with nothing to score.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect

import pytest

from app.modules.matching.models import Explain, MatchScore, ScoreComponents
from app.modules.matching.scoring import FORBIDDEN_FIELDS, ScoreInput, input_field_names

# -- the criterion ------------------------------------------------------------


def test_no_rationale_field_is_reachable_from_the_scorer_input():
    """AC-DATA-02.5."""
    reachable = input_field_names()

    leaked = sorted(reachable & FORBIDDEN_FIELDS)
    assert leaked == [], (
        f"{leaked} reachable from ScoreInput. HR-3: a model's prose must not "
        "influence a score, and a score influenced by prose is not reproducible "
        "from the weights and the profile."
    )


def test_no_field_name_contains_rationale():
    """Broader than the exact list, because the next one will be spelled
    differently - `llm_rationale`, `rationale_summary`, `why`."""
    offenders = sorted(name for name in input_field_names() if "rationale" in name)

    assert offenders == []


def test_the_scorer_input_carries_what_the_scorer_needs():
    """The other direction, and the one that would rot quietly.

    A `ScoreInput` reduced to two ids would satisfy the criterion above and
    leave the scorer unable to score - and nothing else in the suite would
    notice until `MATCH-01` landed.
    """
    reachable = input_field_names()

    assert {"components", "explain"} <= set(ScoreInput.__dataclass_fields__)
    assert {"skills", "experience", "title", "location"} <= reachable
    assert {"matched_required", "missing_required", "skills_basis"} <= reachable


def test_the_match_score_document_does_have_a_rationale():
    """So the check above is not passing because the field does not exist.

    `rationale` is a real, stored field - it is `MATCH-07`'s output. The
    guarantee is that the *scorer* cannot see it, not that nothing can.
    """
    assert "rationale" in MatchScore.model_fields
    assert "rationale_model" in MatchScore.model_fields
    assert "rationale_prompt_version" in MatchScore.model_fields


def test_rationale_is_a_sibling_of_explain_not_a_field_inside_it():
    """§2.8, exactly.

    This is the shape the guarantee rests on. If `rationale` moved inside
    `explain`, `ScoreInput.explain` would carry it and every check above would
    still pass - the field names would simply be reachable through a different
    path. So the nesting itself is asserted.
    """
    assert "rationale" not in Explain.model_fields
    assert not any("rationale" in name for name in Explain.model_fields)


# -- the type's own shape -----------------------------------------------------


def test_the_scorer_input_is_not_the_document():
    """A scorer taking `MatchScore` would have the rationale in scope by
    definition, and would also be able to write to it."""
    # By name: mypy proves the identity comparison statically, which makes it a
    # tautology rather than a test.
    assert ScoreInput.__name__ != MatchScore.__name__
    assert not issubclass(ScoreInput, MatchScore)


def test_the_scorer_input_is_frozen():
    """A scorer that mutated its input would make a rescore depend on
    evaluation order, and `MATCH-05` rescores a candidate set in an unspecified
    one."""
    assert ScoreInput.__dataclass_params__.frozen  # type: ignore[attr-defined]

    instance = _instance()
    with pytest.raises(dataclasses.FrozenInstanceError):
        instance.profile_version = 99  # type: ignore[misc]


def test_the_scorer_input_names_no_model_or_provider():
    """A scorer that could see which model wrote a rationale could branch on
    it, which is the same violation one step removed - and it would not contain
    the word "rationale" anywhere."""
    reachable = input_field_names()

    for forbidden in ("model", "provider", "prompt_version", "llm"):
        offenders = sorted(name for name in reachable if forbidden in name)
        assert offenders == [], f"ScoreInput exposes {offenders}"


def test_the_scoring_module_imports_nothing_it_should_not():
    """`AC-FOUND-05.5`: a pure-logic file has no imports from `app.infra`,
    another module's `models`, or any `repository`.

    Checked here as well as by `lint-imports` because this particular file's
    purity is what the criterion rests on: a `scoring.py` that could reach a
    repository could load the `MatchScore` document and read the rationale from
    the database, with a type that still looked clean.
    """
    from app.modules.matching import scoring

    tree = ast.parse(inspect.getsource(scoring))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    # By import, not by text: the docstring above explains *why* this file
    # imports no `fastapi`, so a substring search over the source finds the
    # word and fails on the explanation. A check that a comment can break is a
    # check someone deletes.
    for forbidden in ("app.infra", "fastapi", "pymongo", "beanie"):
        offenders = sorted(name for name in imported if name.startswith(forbidden))
        assert offenders == [], f"scoring.py imports {offenders}"
    assert not any("repository" in name for name in imported)


def test_the_forbidden_list_matches_the_documents_rationale_fields():
    """`FORBIDDEN_FIELDS` is hand-written, so it can fall behind.

    A fifth rationale field added to `MatchScore` and not to the list would be
    a field this check does not look for - and the check would still pass.
    """
    on_document = {name for name in MatchScore.model_fields if "rationale" in name}

    assert on_document == set(FORBIDDEN_FIELDS), (
        f"MatchScore has rationale field(s) {sorted(on_document - FORBIDDEN_FIELDS)} "
        "that FORBIDDEN_FIELDS does not list"
    )


def test_the_introspection_would_catch_a_violation():
    """The detector, on a type that does leak.

    `input_field_names` reads the real type, so it cannot be exercised against
    a violation directly - a violation would be a code change. This asserts the
    mechanism instead: the same intersection over a set that does contain a
    forbidden name is non-empty.
    """
    pretend = set(input_field_names()) | {"rationale"}

    assert pretend & FORBIDDEN_FIELDS == {"rationale"}


def _instance() -> ScoreInput:
    return ScoreInput(
        user_id="01JBQ8Z3F7KX2M4N6P8R0S2T4V",
        job_id="01JBQ8Z3F7KX2M4N6P8R0S2T4W",
        profile_version=12,
        weights_version="w1",
        scorer_build="sha-abc1234",
        components=ScoreComponents(skills=34),
        explain=Explain(matched_required=["react"]),
    )
