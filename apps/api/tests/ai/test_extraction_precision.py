"""T-AI-07.5 - résumé extraction precision, and the harness that measures it.

`AC-AI-07.5`: "Resume extraction achieves ≥90% field-level precision on skills
and employers across the 10-resume golden set."

`T-AI-07.5` asks for two things: the `real_ai` test, and "a fake-provider
variant asserting the harness itself". Both are here, and the second is not a
consolation prize. A precision function that is wrong in the generous direction
turns the P2 exit gate into a formality - it will report ≥90% on a model that
is inventing skills, and nobody will look again. So the arithmetic is tested
against hand-built cases with known answers, on every CI run, and the nightly
run supplies data rather than logic.

**Why precision is the gate and recall is only reported.** A résumé extraction
that *misses* a skill produces a slightly worse match: a real cost, recoverable,
and the user can add it. One that *invents* a skill writes a claim the user
never made into an application pack they may send to an employer - and the user
is the one who answers for it in an interview. Those are not two sizes of the
same error. The gate is on precision; `test_recall_is_reported_not_gated`
states that on purpose so nobody "fixes" the asymmetry later.

**The `real_ai` test cannot pass yet, and does not lie about it.** It needs
`RES-03`'s extraction schema, a `resume_extract` prompt, ten hand-labelled
résumés and a provider credential. None of those exist. It is marked `real_ai`
and deselected from the default run (`pytest.ini`), so it is nightly-only as §7
requires - and it *fails* rather than skips when it does run without its
inputs, because a green nightly report for a gate that never ran is worse than
a red one.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.ai.base import Feature, LLMProvider, LLMResponse
from app.ai.fake import FakeLLM
from tests.ai import golden_harness as harness
from tests.ai.golden_harness import MIN_PRECISION, REQUIRED_RESUME_CASES

# -- the arithmetic, on data with known answers -------------------------------


def test_a_perfect_answer_scores_one():
    expected = {"skills": ["Python", "Django"]}
    actual = {"skills": ["Python", "Django"]}

    assert harness.precision(expected, actual, "skills").precision == 1.0


def test_an_invented_value_lowers_precision():
    """The failure the gate exists for. Two of three are right, so 0.667 - well
    under the threshold, which is the point."""
    expected = {"skills": ["Python", "Django"]}
    actual = {"skills": ["Python", "Django", "Kubernetes"]}

    result = harness.precision(expected, actual, "skills")

    assert result.produced == 3
    assert result.matched == 2
    assert result.precision == pytest.approx(2 / 3)
    assert result.wrong == ("kubernetes",)


def test_a_missed_value_does_not_lower_precision():
    """Recall's job, not precision's. Stated as a test because the arithmetic
    looks like a bug to anyone expecting an accuracy score."""
    expected = {"skills": ["Python", "Django", "Postgres"]}
    actual = {"skills": ["Python"]}

    assert harness.precision(expected, actual, "skills").precision == 1.0
    assert harness.recall(expected, actual, "skills") == pytest.approx(1 / 3)


def test_an_empty_answer_scores_one_on_precision_and_zero_on_recall():
    """Saying nothing invents nothing.

    Deliberate, and the reason recall is reported alongside: a threshold on
    precision alone could be met by a model that answered less and less, and
    the recall figure is what makes that visible in the nightly report.
    """
    expected = {"skills": ["Python"]}
    actual: dict[str, list[str]] = {"skills": []}

    assert harness.precision(expected, actual, "skills").precision == 1.0
    assert harness.recall(expected, actual, "skills") == 0.0


def test_a_missing_field_is_the_same_as_an_empty_one():
    """A model that omits the key entirely and one that returns `[]` have said
    the same thing, and must not score differently."""
    expected = {"skills": ["Python"]}

    assert harness.precision(expected, {}, "skills").precision == 1.0
    assert harness.recall(expected, {}, "skills") == 0.0


def test_comparison_ignores_case_and_surrounding_whitespace():
    """Otherwise the figure measures formatting rather than extraction."""
    expected = {"skills": ["Python", "Django"]}
    actual = {"skills": [" python ", "DJANGO."]}

    assert harness.precision(expected, actual, "skills").precision == 1.0


def test_a_duplicate_in_the_answer_is_counted_once_as_right_and_once_as_wrong():
    """A model listing "Python" twice has produced two values and only one of
    them is in the labels. Crediting both would let a model reach any precision
    figure by repeating one correct answer.
    """
    expected = {"skills": ["Python", "Django"]}
    actual = {"skills": ["Python", "Python"]}

    result = harness.precision(expected, actual, "skills")

    assert result.produced == 2
    assert result.matched == 1
    assert result.precision == 0.5


def test_an_employer_object_is_measured_on_its_name():
    """Employers arrive as objects, not strings. Comparing the whole object
    would make precision a measurement of JSON shape."""
    expected = {"employers": ["Acme Ltd"]}
    actual = {"employers": [{"name": "Acme Ltd", "start": "2021-01"}]}

    assert harness.precision(expected, actual, "employers").precision == 1.0


def test_an_employer_object_with_no_name_counts_as_wrong():
    """Rather than being dropped. A row with no employer name is a fabrication
    of a different kind, and silently skipping it would raise the score."""
    expected = {"employers": ["Acme Ltd"]}
    actual = {"employers": [{"start": "2021-01"}]}

    assert harness.precision(expected, actual, "employers").precision == 0.0


def test_overall_precision_is_micro_averaged():
    """Forty skills and two employers must not weigh the same.

    Macro-averaging would let a perfect two-item field cover a bad forty-item
    one - 0.5 and 1.0 averaging to a passing 0.75 while three quarters of the
    skills were invented.
    """
    expected = {"skills": ["a", "b", "c", "d"], "employers": ["x"]}
    actual = {"skills": ["a", "z", "y", "w"], "employers": ["x"]}

    # 2 of 5 values correct, not the mean of 0.25 and 1.0.
    assert harness.overall_precision(expected, actual, ("skills", "employers")) == pytest.approx(
        2 / 5
    )


def test_overall_precision_over_nothing_is_one():
    """An extractor that produced no values invented none. Dividing by zero
    here, or returning 0.0, would fail a case that has no labels for a field."""
    assert harness.overall_precision({}, {}, ("skills",)) == 1.0


# -- the fabrication check, which needs no labels -----------------------------


def test_a_value_absent_from_the_source_is_flagged():
    """`ungrounded` is the absolute check: a skill the résumé does not mention
    is a fabrication whether or not anyone labelled that résumé."""
    actual = {"skills": ["Python", "Kubernetes"]}
    source = "Five years of Python at Acme Ltd."

    assert harness.ungrounded(actual, source, ("skills",)) == ["kubernetes"]


def test_a_grounded_answer_flags_nothing():
    actual = {"skills": ["Python"], "employers": ["Acme Ltd"]}
    source = "Five years of Python at Acme Ltd."

    assert harness.ungrounded(actual, source, ("skills", "employers")) == []


def test_grounding_is_case_insensitive():
    """A model that title-cases a skill has not invented it."""
    actual = {"skills": ["PYTHON"]}

    assert harness.ungrounded(actual, "five years of python", ("skills",)) == []


def test_grounding_catches_what_label_comparison_misses():
    """The reason both checks exist.

    Precision compares against `expected`, so a field nobody labelled scores
    1.0 no matter what the model put in it. `ungrounded` has no such blind
    spot, and it applies to every case for free.
    """
    expected: dict[str, list[str]] = {}
    actual = {"skills": ["Rust"]}
    source = "Five years of Python."

    assert harness.overall_precision(expected, actual, ("skills",)) == 0.0
    assert harness.ungrounded(actual, source, ("skills",)) == ["rust"]


# -- the harness against the fake provider ------------------------------------


async def test_the_measurement_path_runs_against_the_fake_provider():
    """`T-AI-07.5`'s "fake-provider variant asserting the harness itself".

    The fake answers from a hash, so its *content* is meaningless and no
    threshold is asserted against it. What is asserted is that a response can
    be measured at all: parsed, bagged, scored, and grounded. If this breaks,
    the nightly run reports a number that came from nowhere.
    """
    from pydantic import BaseModel

    class Extracted(BaseModel):
        skills: list[str] = []
        employers: list[str] = []

    from app.ai.base import LLMRequest

    request = LLMRequest(
        feature=Feature.RESUME_EXTRACT,
        system="List the skills and employers in [resume_text].",
        untrusted={"resume_text": "Python at Acme Ltd."},
        prompt_version="resume_extract/v0",
    )

    result = await FakeLLM().complete_json(request, Extracted)
    produced = result.value.model_dump()

    score = harness.overall_precision({"skills": [], "employers": []}, produced, ("skills",))

    assert 0.0 <= score <= 1.0
    assert isinstance(harness.ungrounded(produced, "Python at Acme Ltd.", ("skills",)), list)


def test_nightly_spend_is_tagged_so_it_is_separable_from_user_spend():
    """§7: nightly runs "write their spend to `ai_usage` under a `feature`
    suffix of `:golden` so test spend is separable from user spend on the
    dashboard".

    Asserted here rather than described in the workflow file, because an
    untagged nightly run inflates every per-feature cost chart the budget
    decisions are made from - and it does so invisibly, since the numbers stay
    plausible.
    """
    assert harness.golden_feature(Feature.RESUME_EXTRACT) == "resume_extract:golden"

    row = harness.record_golden_call(
        "fake",
        "fake-1",
        Feature.RESUME_EXTRACT,
        prompt_version="resume_extract/v1",
        input_tokens=1200,
        output_tokens=300,
        latency_ms=840,
        cost_usd=None,
    )

    assert row["feature"] == "resume_extract:golden"
    assert row["feature"].removesuffix(harness.GOLDEN_SUFFIX) in {f.value for f in Feature}
    # `AC-AI-04.3`: an unpriced model records `None`, never zero. Zero would say
    # "this was free", which is a claim - and it would understate the nightly
    # bill rather than flagging it as unknown.
    assert row["est_cost_usd"] is None


def test_a_golden_row_goes_through_the_same_builder_as_user_spend():
    """One code path, so `AC-AI-04.3`'s rules cannot be right for user spend and
    wrong for test spend."""
    from app.ai.usage import Outcome, build_row

    row = build_row(
        provider="gemini",
        model="gemini-3.5-flash-lite",
        feature=harness.golden_feature(Feature.RESUME_EXTRACT),
        outcome=Outcome.OK,
        input_tokens=10,
        output_tokens=5,
        prompt_version="resume_extract/v1",
    )

    assert row["feature"].endswith(":golden")
    assert row["outcome"] is Outcome.OK


def test_the_threshold_is_the_one_the_phase_gate_names():
    """`00-scope-and-phases.md` §4's P2 exit gate. One constant, so the number
    in the report and the number in the gate cannot diverge."""
    assert MIN_PRECISION == 0.90
    assert REQUIRED_RESUME_CASES == 10


def test_recall_is_reported_not_gated():
    """Stated as a test so the asymmetry is a decision on the record rather
    than an oversight someone tidies up.

    `AC-AI-07.5` names precision. Adding a recall threshold would trade a
    recoverable cost (a missed skill the user can add) against an
    unrecoverable one (a claim the user never made, in a document they send).
    """
    import inspect

    source = inspect.getsource(harness)

    assert "MIN_PRECISION" in source
    assert "MIN_RECALL" not in source


# -- the nightly gate ---------------------------------------------------------


def test_the_real_ai_marker_is_deselected_by_default():
    """§7 makes the real-provider run nightly-only, and `15-infra-and-ops.md`
    §3 keeps required checks fast.

    Asserted against `pytest.ini` rather than trusted, because the cost of
    getting this wrong is asymmetric and silent: every developer's `pytest`
    would start spending real money against a real provider, and the first
    anyone would know is a bill.
    """
    from pathlib import Path

    from tests.conftest import REPO_ROOT

    config = (Path(REPO_ROOT) / "apps" / "api" / "pytest.ini").read_text(encoding="utf-8")

    assert "not real_ai" in config
    assert "not real_source" in config


@pytest.mark.real_ai
async def test_extraction_precision_over_the_golden_set():
    """AC-AI-07.5, against the real provider. Nightly only.

    Fails rather than skips when its inputs are absent. A skip would report
    green for a P2 exit gate that never ran, and this is the assertion the
    phase gate is quoting - so "we could not run it" and "it passed" must not
    look the same in the nightly report.
    """
    from app.ai import prompt as prompt_mod

    cases = harness.discover(Feature.RESUME_EXTRACT)

    assert len(cases) >= REQUIRED_RESUME_CASES, (
        f"AC-AI-07.5 requires {REQUIRED_RESUME_CASES} hand-labelled résumés; "
        f"{len(cases)} are committed. They are the developer's own or explicitly "
        "licensed, scrubbed of contact details, and documented as such (§7)."
    )

    prompt = prompt_mod.latest(Feature.RESUME_EXTRACT)
    schema = prompt.resolve_schema()
    provider = _real_provider()

    matched = produced = 0
    fabrications: list[str] = []
    for case in cases:
        result = await provider.complete_json(harness.build_request(prompt, case), schema)
        answer = result.value.model_dump()
        harness.record_golden_call(
            provider.name,
            result.response.model,
            Feature.RESUME_EXTRACT,
            prompt_version=prompt.prompt_version,
            input_tokens=result.response.input_tokens,
            output_tokens=result.response.output_tokens,
            latency_ms=result.response.latency_ms,
            cost_usd=_cost(result.response),
        )
        for name in case.precision_fields:
            field = harness.precision(case.expected, answer, name)
            matched += field.matched
            produced += field.produced
        fabrications += [
            f"{case.name}: {value}"
            for value in harness.ungrounded(answer, case.source_text, case.precision_fields)
        ]

    score = 1.0 if produced == 0 else matched / produced

    assert fabrications == [], (
        "the model produced values that do not occur in the résumé it was shown; "
        f"each one would appear in an application pack the user sends: {fabrications}"
    )
    assert score >= MIN_PRECISION, (
        f"field-level precision on {list(harness.PRECISION_FIELDS)} is {score:.1%}, "
        f"below the P2 exit gate's {MIN_PRECISION:.0%} ({matched}/{produced} values correct)"
    )


def _cost(response: LLMResponse) -> Decimal | None:
    """The estimated cost of one nightly call, or `None` for an unpriced model.

    `AC-AI-04.3`: never zero for an unknown price. The nightly report says
    "unpriced" rather than "$0.00", because the second reads as free.
    """
    from app.ai.pricing import estimate_cost

    return estimate_cost(response.model, response.input_tokens, response.output_tokens)


def _real_provider() -> LLMProvider:
    """The configured provider, for the nightly run only.

    A separate function so the `real_ai` test reads as the assertion it is, and
    so the credential is fetched at the moment of use rather than at import -
    where it would be read on every default run that does not need it.
    """
    from app.ai.registry import build
    from app.core.config import get_settings

    settings = get_settings()
    return build(settings).llm(Feature.RESUME_EXTRACT)
