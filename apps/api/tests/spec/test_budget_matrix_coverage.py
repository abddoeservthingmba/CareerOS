"""T-AI-03.12 - the matrix covers every feature, and nothing else.

`AC-AI-03.12`: "`ai-budget.yaml` has one row per `Feature` enum member; a member
without a row, or a row without a member, fails."

`05-ai-layer.md` §3.2 calls the matrix "normative", and says each row is "the
complete contract for one feature: what it does when the budget denies it, what
the user sees, what is recorded, and how it recovers".

A feature with no row has no such contract, and the behaviour it would fall back
to is an unhandled `AIBudgetExceeded` reaching the user - which §3.2 forbids in
its first sentence. So this check is not bookkeeping: it is what stops a
feature added in a hurry from becoming a 503 on the day the cap first trips.

The other direction matters too. A row for a feature that no longer exists is a
contract nobody is bound by, and it makes the parametrized degradation test in
`test_degradation.py` look more thorough than it is.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.base import Feature
from app.ai.budget import MATRIX, MATRIX_FILE, Degradation, load_matrix

#: The degradations §3.2's table actually uses. A new one is a new behaviour and
#: should be a deliberate addition here as well as in the file.
KNOWN_DEGRADATIONS = frozenset(
    {
        "retry_with_backoff",
        "skip",
        "fallback_dictionary",
        "omit_field",
        "refuse",
        "template_fallback",
        "store_without_embedding",
        "fallback_fuzzy_only",
    }
)


# -- AC-AI-03.12 -------------------------------------------------------------


def test_every_feature_has_a_row():
    """A member without a row would default to an unhandled error, which §3.2's
    first sentence forbids."""
    missing = sorted(str(f) for f in Feature if str(f) not in MATRIX.features)
    assert missing == [], f"these features have no degradation contract: {missing}"


def test_every_row_has_a_feature():
    """A row for a feature that no longer exists makes `test_degradation.py`
    look more thorough than it is."""
    stray = sorted(set(MATRIX.features) - {str(f) for f in Feature})
    assert stray == [], f"these rows name no Feature member: {stray}"


def test_there_are_ten_of_each():
    """The number §3.2 and `ai/base.py` both state. Two empty lists would
    satisfy the two assertions above."""
    assert len(Feature) == 10
    assert len(MATRIX.features) == 10


def test_the_matrix_file_is_the_one_the_spec_names(repo: Path):
    """§3's Outputs: "`docs/spec/ai-budget.yaml` - the matrix above in
    machine-readable form, which parametrizes the degradation tests"."""
    assert repo / "docs" / "spec" / "ai-budget.yaml" == MATRIX_FILE
    assert MATRIX_FILE.is_file()


# -- every row is complete ---------------------------------------------------


@pytest.mark.parametrize("feature", sorted(MATRIX.features))
def test_every_row_answers_all_four_questions(feature: str):
    """§3.2: "what it does when the budget denies it, what the user sees, what
    is recorded, and how it recovers"."""
    row: Degradation = MATRIX.features[feature]

    assert row.degradation, f"{feature} does not say what it does instead"
    assert row.user_visible, f"{feature} does not say what the user sees"
    assert row.recovery, f"{feature} does not say how it recovers"
    assert isinstance(row.surfaces_error, bool)


@pytest.mark.parametrize("feature", sorted(MATRIX.features))
def test_every_degradation_is_a_known_behaviour(feature: str):
    """A new degradation is a new behaviour, and should be a deliberate addition
    rather than a string nobody implemented."""
    assert MATRIX.features[feature].degradation in KNOWN_DEGRADATIONS


@pytest.mark.parametrize("feature", sorted(MATRIX.features))
def test_every_row_names_a_tier(feature: str):
    """§5.2: "`fast` for extraction, enrichment, rationale, follow-up drafts and
    answer suggestions; `quality` for pack generation"."""
    assert MATRIX.features[feature].tier in {"fast", "quality", "embedding"}


# -- §3.2's three invariants -------------------------------------------------


def test_only_pack_generate_surfaces_an_error():
    """§3.2: "No feature may propagate `AIBudgetExceeded` to the user as an
    unhandled error", and the invariant `no_data_loss`: "only `pack_generate`
    refuses outright"."""
    surfacing = sorted(name for name, row in MATRIX.features.items() if row.surfaces_error)

    assert surfacing == ["pack_generate"]


def test_the_refusing_feature_states_its_status_and_code():
    """§3.2: "the two rows that do surface an error do so with a specific code
    and a `Retry-After`"."""
    row = MATRIX["pack_generate"]

    assert row.degradation == "refuse"
    assert row.http_status == 503
    assert row.error_code == "ai_budget_exceeded"
    assert row.retry_after == "seconds_until_utc_reset"


def test_the_refusing_feature_preserves_user_edits():
    """The `no_data_loss` invariant. Refusing is acceptable; refusing *and*
    discarding a half-written cover letter is not."""
    assert MATRIX["pack_generate"].preserves_user_edits is True


def test_every_feature_names_a_recovery():
    """The `no_permanent_degradation` invariant. A degradation with no way back
    is an outage with better manners."""
    for name, row in MATRIX.features.items():
        assert row.recovery, f"{name} degrades with no stated recovery"


def test_the_two_that_do_not_backfill_say_why():
    """§3.2: "the two rows that deliberately do not backfill (`match_rationale`,
    `resume_quality`) say so and say why"."""
    not_backfilled = sorted(name for name, row in MATRIX.features.items() if not row.backfilled)

    assert not_backfilled == ["match_rationale"]
    assert MATRIX["match_rationale"].backfill_reason, (
        "a feature that is never backfilled must say why, or it reads as an oversight"
    )
    assert "worth nothing" in MATRIX["match_rationale"].backfill_reason
    # `resume_quality` recovers on the next re-analysis rather than by a
    # backfill task, which the row states directly.
    assert MATRIX["resume_quality"].recovery == "next_reanalysis"


def test_every_backfill_names_a_task():
    """A recovery of "a backfill task" that does not name the task is a recovery
    nobody can find."""
    for name, row in MATRIX.features.items():
        if row.recovery == "backfill_task":
            assert row.backfill_task, f"{name} recovers by a backfill with no task named"
            assert "." in row.backfill_task, f"{name}: {row.backfill_task} is not a task name"


def test_the_invariants_are_the_three_the_spec_names():
    """§3.2's three, transcribed in the file and read back here so a fourth
    added to the spec is noticed."""
    assert [entry["id"] for entry in MATRIX.invariants] == [
        "no_silent_success",
        "no_data_loss",
        "no_permanent_degradation",
    ]


def test_the_deny_precedence_is_the_fixed_order():
    """§3.1: "Check order is fixed and the first failure wins"."""
    assert list(MATRIX.deny_precedence) == ["user", "feature", "global"]


# -- the loader --------------------------------------------------------------


def test_an_unknown_feature_raises_with_the_reason():
    """The message has to say what to do. "KeyError: 'x'" sends the reader to
    the loader; this sends them to §3.2."""
    with pytest.raises(KeyError, match="no row in ai-budget.yaml"):
        MATRIX["a_feature_that_does_not_exist"]


def test_the_matrix_is_loaded_not_transcribed():
    """A dict in a module beside a table in a spec file is two copies of one
    contract, and only one of them is normative."""
    reloaded = load_matrix()

    assert set(reloaded.features) == set(MATRIX.features)
    assert reloaded.features["pack_generate"] == MATRIX.features["pack_generate"]
