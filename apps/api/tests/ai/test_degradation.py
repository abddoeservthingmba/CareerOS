"""T-AI-03.1 - each of the ten features degrades as its row says.

`AC-AI-03.1`: "For each of the ten features in §3.2, with the binding cap
already consumed, the feature exhibits exactly its listed degradation, produces
exactly its listed user-visible state, and writes `outcome: budget_denied`.
Parametrized from `ai-budget.yaml`, so a feature added without a matrix row
fails the test rather than defaulting to an error."

**Parametrized from the file, not from a list here.** That is the criterion's own
requirement and it is what makes the check grow by itself: a feature added to
the enum with no row fails `test_budget_matrix_coverage.py`, and a feature added
with a row is immediately covered by everything below.

**What is asserted, and what is not.** The ten *features* are P2-P6 - there is no
resume pipeline, no feed, no pack generator. What exists today is the mechanism
they all share: the denial, its reason, its `ai_usage` row, and the contract each
one is bound by. So this file asserts the contract and the mechanism, and the
per-feature behaviour is asserted against a `DegradingCall` that implements each
row's `degradation` verb faithfully.

That is a real check rather than a rehearsal, because the verb is what the
feature will have to implement. When `RES-01` lands, `resume_extract` must do
what `retry_with_backoff` does here; if it does something else, the row is wrong
and the row is normative.

`test_none_of_the_ten_features_exists_yet` fails the moment that stops being
true - which is the prompt to point these assertions at the real implementation
rather than to discover later that they never were.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.ai.base import Feature
from app.ai.budget import (
    MATRIX,
    AIBudgetExceeded,
    Budget,
    Caps,
    Counters,
    Degradation,
    global_key,
    utc_day,
)
from app.ai.usage import DenyReason, Outcome, UsageRecorder, build_row

CAP = Decimal("2.00")
USER = "01J000000000000000000USER"
FEATURES = sorted(MATRIX.features)


async def exhausted() -> Budget:
    """A budget whose global cap is fully consumed."""
    counters = Counters()
    await counters.add_spend(global_key(utc_day()), CAP, timedelta(hours=1))
    return Budget(Caps(global_usd=CAP, user_daily_calls=500), counters)


@dataclass
class Outcome_:
    """What a degraded call produced, from the caller's point of view."""

    raised: AIBudgetExceeded | None = None
    result: Any = None
    sets: dict[str, Any] = field(default_factory=dict)
    user_edits: dict[str, Any] = field(default_factory=dict)


class DegradingCall:
    """One feature's denied path, implementing its row's `degradation` verb.

    Every branch here is a transcription of §3.2, and the branch a feature takes
    is read from the file rather than chosen here - so a row changed in the spec
    changes what this does.
    """

    def __init__(self, feature: str, recorder: UsageRecorder) -> None:
        self.row: Degradation = MATRIX[feature]
        self.feature = feature
        self.recorder = recorder
        self.attempts = 0

    async def run(self, budget: Budget, *, user_edits: dict[str, Any] | None = None) -> Outcome_:
        self.attempts += 1
        decision = await budget.check(self.feature, estimate_usd=Decimal("0.01"), user_id=USER)
        if decision.allowed:
            return Outcome_(result={"produced": True})

        # `no_silent_success`: every degraded path writes a row.
        assert decision.reason is not None
        self.recorder.record(
            build_row(
                provider="gemini",
                model="gemini-3.5-flash-lite",
                feature=self.feature,
                outcome=Outcome.BUDGET_DENIED,
                deny_reason=decision.reason,
                user_id=USER,
            )
        )

        verb = self.row.degradation
        if verb == "refuse":
            # The only row that surfaces an error - and it keeps the edits.
            failure = AIBudgetExceeded(self.feature, decision.reason, decision.resets_at)  # type: ignore[arg-type]
            return Outcome_(raised=failure, user_edits=dict(user_edits or {}))
        if verb == "retry_with_backoff":
            return Outcome_(result=None)
        if verb in ("skip", "omit_field", "store_without_embedding"):
            return Outcome_(result=None, sets=dict(self.row.sets))
        if verb in ("fallback_dictionary", "fallback_fuzzy_only", "template_fallback"):
            return Outcome_(result={"fallback": verb}, sets=dict(self.row.sets))
        raise AssertionError(f"{verb} is not a degradation this test knows how to perform")


# -- the criterion, per feature ----------------------------------------------


@pytest.mark.parametrize("feature", FEATURES)
async def test_every_feature_writes_a_budget_denied_row(feature: str):
    """AC-AI-03.1's "writes `outcome: budget_denied`", and §3.2's
    `no_silent_success` invariant.

    "A feature that quietly does nothing is indistinguishable from a bug."
    """
    recorder = UsageRecorder()
    await DegradingCall(feature, recorder).run(await exhausted())

    rows = recorder.drain()
    assert len(rows) == 1
    assert rows[0]["outcome"] is Outcome.BUDGET_DENIED
    assert rows[0]["deny_reason"] is DenyReason.GLOBAL
    assert rows[0]["feature"] == feature


@pytest.mark.parametrize("feature", FEATURES)
async def test_only_pack_generate_raises(feature: str):
    """§3.2's opening rule: "**No feature may propagate `AIBudgetExceeded` to the
    user as an unhandled error**", with one stated exception."""
    outcome = await DegradingCall(feature, UsageRecorder()).run(await exhausted())

    if feature == "pack_generate":
        assert outcome.raised is not None
    else:
        assert outcome.raised is None, f"{feature} surfaced an error to the user"


@pytest.mark.parametrize("feature", FEATURES)
async def test_the_row_and_the_behaviour_agree_about_surfacing(feature: str):
    """The row's `surfaces_error` is the contract; the behaviour is the
    implementation. This is the assertion that they are the same claim."""
    outcome = await DegradingCall(feature, UsageRecorder()).run(await exhausted())

    assert (outcome.raised is not None) is MATRIX[feature].surfaces_error


@pytest.mark.parametrize("feature", FEATURES)
async def test_every_feature_states_what_the_user_sees(feature: str):
    """AC-AI-03.1's "produces exactly its listed user-visible state".

    A row that said nothing here would leave the client free to render a spinner
    for ever, which is the failure mode users actually report.
    """
    assert MATRIX[feature].user_visible.strip()


@pytest.mark.parametrize("feature", [f for f in FEATURES if MATRIX[f].sets])
async def test_a_feature_that_sets_a_field_sets_it(feature: str):
    """Three rows name a field they set when denied - `skills_source:
    dictionary`, `rationale: null`. Those are what the rest of the product reads
    to know the value it is looking at is a fallback."""
    outcome = await DegradingCall(feature, UsageRecorder()).run(await exhausted())

    assert outcome.sets == dict(MATRIX[feature].sets)


# -- the row that refuses ----------------------------------------------------


async def test_pack_generate_returns_the_stated_status_and_code():
    """§3.2: "**Refuses**: `503 ai_budget_exceeded` with `Retry-After` set to
    seconds until the UTC reset"."""
    row = MATRIX["pack_generate"]

    assert row.http_status == 503
    assert row.error_code == "ai_budget_exceeded"


async def test_pack_generate_preserves_every_user_edit():
    """§3.2's `no_data_loss` invariant: "`pack_generate` is the only feature that
    refuses outright, and it preserves every user edit; nothing else discards
    work."

    Refusing is acceptable. Refusing *and* discarding a half-written cover
    letter is the thing that makes a user stop trusting the product.
    """
    edits = {"cover_letter": "Dear hiring manager, I have been...", "tone": "direct"}

    outcome = await DegradingCall("pack_generate", UsageRecorder()).run(
        await exhausted(), user_edits=edits
    )

    assert outcome.raised is not None
    assert outcome.user_edits == edits


async def test_the_refusal_carries_seconds_until_the_reset():
    """`AC-AI-03.11`. The user-facing copy is "try after HH:MM", and it is only
    honest if this number is."""
    outcome = await DegradingCall("pack_generate", UsageRecorder()).run(await exhausted())

    assert outcome.raised is not None
    assert 0 < outcome.raised.retry_after_seconds <= 86_400


# -- the rows that fall back -------------------------------------------------


@pytest.mark.parametrize(
    "feature", [f for f in FEATURES if MATRIX[f].degradation.startswith(("fallback", "template"))]
)
async def test_a_fallback_still_produces_something(feature: str):
    """Three features fall back rather than skipping: dictionary skills, a
    template draft, fuzzy-only matching. Each returns a usable result, which is
    the difference between a degraded feature and an absent one."""
    outcome = await DegradingCall(feature, UsageRecorder()).run(await exhausted())

    assert outcome.result is not None
    assert outcome.raised is None


async def test_the_followup_draft_is_labelled_a_template():
    """§3.2: "a draft the user can edit, labelled as a template rather than
    AI-written".

    HR-9 again: a template presented as AI-written would be a provenance claim
    that is simply false.
    """
    assert "labelled as a template" in MATRIX["followup_draft"].user_visible


async def test_job_enrich_marks_its_skills_as_dictionary_sourced():
    """`08-matching.md` reads `skills_source` to know whether it is scoring
    against enriched skills or dictionary ones. A fallback that did not say so
    would be scored as though it were the real thing."""
    outcome = await DegradingCall("job_enrich", UsageRecorder()).run(await exhausted())

    assert outcome.sets == {"skills_source": "dictionary"}


async def test_match_rationale_leaves_the_field_null():
    """§3.2: "the full deterministic breakdown with no empty placeholder".

    An empty string would render as a blank box where an explanation should be,
    which is worse than the honest absence of one.
    """
    outcome = await DegradingCall("match_rationale", UsageRecorder()).run(await exhausted())

    assert outcome.sets == {"rationale": None}


# -- the row that retries ----------------------------------------------------


async def test_resume_extract_retries_rather_than_failing():
    """§3.2: "Task retries with backoff for up to 24 h; the resume stays in
    `structuring`" and "never `failed`".

    A resume marked failed is a user who thinks their upload was rejected. It
    was not - the budget was busy.
    """
    row = MATRIX["resume_extract"]
    recorder = UsageRecorder()
    call = DegradingCall("resume_extract", recorder)
    budget = await exhausted()

    for _ in range(3):
        outcome = await call.run(budget)
        assert outcome.raised is None

    assert row.retry_window_hours == 24
    assert "never `failed`" in row.user_visible
    assert len(recorder.drain()) == 3


async def test_the_retry_recovers_when_the_budget_does():
    """The retry is only worth doing if it eventually succeeds. §3.2's recovery
    for this row is "Automatic at the next reset, or when the retry lands"."""
    call = DegradingCall("resume_extract", UsageRecorder())

    denied = await call.run(await exhausted())
    allowed = await call.run(Budget(Caps(global_usd=CAP, user_daily_calls=500), Counters()))

    assert denied.result is None
    assert allowed.result == {"produced": True}


# -- the boundary between this file and the features -------------------------


def test_no_feature_is_routable_yet():
    """Stated rather than assumed.

    The ten features are P2-P6. When one becomes reachable, this fails - which
    is the prompt to point the assertions above at the real implementation,
    rather than to discover later that they only ever exercised a
    transcription.

    **Keyed on a routable feature, not on a module directory.** It used to
    check whether `app/modules/<name>/` existed, and `DATA-02` made all nine
    exist in P0 - to hold their Beanie documents, with every other file still
    the scaffold's docstring. That fired the sentinel with no feature built,
    which is a false alarm, and a sentinel that cries wolf is one somebody
    deletes. A feature is *reachable* when its `router.py` declares an
    `APIRouter`; until then there is no code path a budget denial could
    degrade.
    """
    assert routable_modules() == [], (
        f"{routable_modules()} now expose routes; wire test_degradation.py to them"
    )


def routable_modules() -> list[str]:
    """Modules whose `router.py` declares an `APIRouter`.

    By AST rather than by import, so a module that fails to import for an
    unrelated reason does not silently count as un-routable - which would make
    this sentinel pass for the wrong reason.
    """
    import ast
    from pathlib import Path

    modules = Path(__file__).resolve().parents[2] / "app" / "modules"
    found: list[str] = []
    for path in sorted(modules.iterdir()):
        router = path / "router.py"
        if not router.is_file():
            continue
        tree = ast.parse(router.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name | ast.Attribute)
            and "APIRouter" in ast.unparse(node.func)
            for node in ast.walk(tree)
        ):
            found.append(path.name)
    return found


def test_every_feature_in_the_enum_is_parametrized():
    """The criterion says "each of the ten features". A parametrization that
    silently covered nine would still be green."""
    assert set(FEATURES) == {str(f) for f in Feature}
    assert len(FEATURES) == 10


def test_every_degradation_verb_is_implemented_here():
    """A row whose verb `DegradingCall` does not know would raise
    `AssertionError` at run time rather than being quietly skipped - but only
    for features that are exercised. This checks all ten up front."""
    verbs = {MATRIX[f].degradation for f in FEATURES}
    known = {
        "refuse",
        "retry_with_backoff",
        "skip",
        "omit_field",
        "store_without_embedding",
        "fallback_dictionary",
        "fallback_fuzzy_only",
        "template_fallback",
    }
    assert verbs <= known, f"unimplemented degradations: {sorted(verbs - known)}"
