"""T-AI-07.3 - the golden tests that run on every CI run.

`AC-AI-07.3`: "Golden tests against the fake provider pass on every CI run and
cover every feature that has a prompt."

§7 says exactly what this mode is for: "against the **fake provider** on every
CI run (deterministic, asserts the prompt renders and the schema parses)". It
is not a quality measurement - the fake answers from a hash, so it cannot tell
a good prompt from a bad one. It answers a narrower and more useful question,
on every commit, for free: **does this prompt still work as a program?** Does
its front matter validate, does its schema still import, does the request build,
does `complete_json` produce an instance of the declared model, and is the
untrusted content fenced where §6 says it must be.

Those are the failures that arrive by accident. A model gets a field renamed
three modules away; a slot is added to a prompt and not to the code that fills
it; a schema moves package. Each one breaks a feature silently in a way the
nightly run would catch nine hours later, and this catches in nine seconds.

**The coupling test is the load-bearing one.** `test_every_prompt_has_a_golden_set`
fails the moment a prompt is committed without cases. That is what makes
`AC-AI-07.3`'s "cover every feature that has a prompt" true by construction
rather than by anyone remembering - and it is why this file is worth having
before any prompt exists. Today it passes over zero prompts. In the commit that
adds `resume_extract/v1` it fails, and the fix is to add the golden set in that
same commit, which is what §7 is asking for.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.ai import prompt as prompt_mod
from app.ai.base import Feature, LLMRequest
from app.ai.fake import FakeLLM
from app.ai.untrusted import render as render_untrusted
from tests.ai import golden_harness as harness
from tests.ai.golden_harness import GoldenCaseInvalid

PROMPTS = prompt_mod.load_all()
CASES = harness.discover()

# `(prompt, case)` for every case that has a prompt, which is what a golden run
# actually is. Built at import so the ids name the feature and the case.
PAIRS = [
    (versions[max(versions)], case)
    for feature, versions in PROMPTS.items()
    for case in harness.discover(feature)
]


# -- the criterion ------------------------------------------------------------


def test_every_prompt_has_a_golden_set():
    """`AC-AI-07.3`'s coverage clause, and the reason this file exists now.

    A prompt with no cases is a prompt nobody has tested. This fails in the
    commit that adds one without a golden set, so the two land together.
    """
    uncovered = sorted(feature.value for feature in PROMPTS if not harness.discover(feature))

    assert uncovered == [], (
        f"prompt(s) for {uncovered} have no golden cases. Add at least one "
        f"(input, expected) pair under tests/ai/golden/<feature>/ in the same "
        "commit as the prompt - §7 makes the tests part of the artifact, not a "
        "follow-up."
    )


def test_every_golden_case_has_a_prompt():
    """The other direction. A case for a feature with no prompt is a fixture
    that never runs, and a fixture that never runs is indistinguishable from a
    passing one on a dashboard."""
    orphans = sorted({case.feature.value for case in CASES} - {f.value for f in PROMPTS})

    assert orphans == [], f"golden cases exist for {orphans} but no prompt does"


async def test_every_case_produces_a_validated_instance():
    """§7's fake mode, over every `(prompt, case)` pair.

    Uses the real prompt, the real renderer and the real schema; only the
    provider is fake. That is the whole point - everything except the model is
    exercised, so anything that broke between a feature and its prompt shows up
    here rather than nightly.

    A loop rather than a parametrisation, deliberately: `PAIRS` is empty until
    the first prompt lands, and an empty `parametrize` produces a *skipped*
    test - a green tick for a check that did not run, which is the one thing a
    gate must never do. The loop passes over zero pairs and reports every
    failure over many.
    """
    failures: list[str] = []
    for prompt, case in PAIRS:
        schema = prompt.resolve_schema()
        result = await FakeLLM().complete_json(harness.build_request(prompt, case), schema)
        if not isinstance(result.value, schema):
            failures.append(f"{prompt.prompt_version}:{case.name} did not parse as {schema}")
        if result.response.prompt_version != prompt.prompt_version:
            failures.append(f"{prompt.prompt_version}:{case.name} lost its prompt_version")

    assert failures == []


def test_every_case_fences_its_untrusted_content():
    """§6, asserted per case rather than once in the abstract.

    The instruction text must contain the slot *header* and none of the slot's
    content. This is the assertion that fails if someone "helpfully" changes
    `render()` to interpolate.
    """
    failures: list[str] = []
    for prompt, case in PAIRS:
        request = harness.build_request(prompt, case)
        for slot, content in case.untrusted.items():
            if f"[{slot}]" not in request.system:
                failures.append(f"{case.path}: the prompt never points at [{slot}]")
            if len(content) > 40 and content[:40] in request.system:
                failures.append(f"{case.path}: content from {slot} reached the instruction text")

    assert failures == []


# -- the harness itself, which has to be right for any of the above to mean
# -- anything ----------------------------------------------------------------
# Exercised on synthetic data, because the harness is the part that would fail
# open. A precision function that returned 1.0 on bad input, or a `discover`
# that silently found nothing, would make every assertion above pass while
# measuring nothing - and that is exactly how a green golden suite ends up
# covering a broken prompt.


class Tiny(BaseModel):
    skills: list[str] = []
    employers: list[str] = []


GOOD_PROMPT = """\
---
version: 1
feature: resume_extract
tier: fast
output_schema: tests.ai.test_golden_fake.Tiny
untrusted_slots: [resume_text]
changelog: ["v1"]
---

List the skills and employers named in {{resume_text}}.
"""


@pytest.fixture
def synthetic(tmp_path: Path) -> tuple[Path, Path]:
    """A one-prompt, one-case world, so the harness is measured end to end."""
    prompts = tmp_path / "prompts"
    (prompts / "resume_extract").mkdir(parents=True)
    (prompts / "resume_extract" / "v1.md").write_text(GOOD_PROMPT, encoding="utf-8")

    golden = tmp_path / "golden"
    (golden / "resume_extract").mkdir(parents=True)
    (golden / "resume_extract" / "one.json").write_text(
        json.dumps(
            {
                "description": "a synthetic resume",
                "input": {"untrusted": {"resume_text": "Python and Django at Acme Ltd."}},
                "expected": {"skills": ["Python", "Django"], "employers": ["Acme Ltd"]},
            }
        ),
        encoding="utf-8",
    )
    return prompts, golden


def test_discover_finds_a_case(synthetic):
    _, golden = synthetic
    found = harness.discover(root=golden)

    assert [c.name for c in found] == ["one"]
    assert found[0].feature is Feature.RESUME_EXTRACT
    assert found[0].untrusted["resume_text"].startswith("Python")


def test_discover_over_a_missing_directory_returns_nothing(tmp_path: Path):
    """And does not raise. The golden root is legitimately absent for a feature
    that has no prompt yet, and an exception there would make adding the first
    prompt harder than adding the tests."""
    assert harness.discover(root=tmp_path / "nope") == []


def test_a_case_for_an_unknown_feature_is_refused(tmp_path: Path):
    directory = tmp_path / "resume_extraction"
    directory.mkdir()
    (directory / "a.json").write_text('{"input": {}, "expected": {}}', encoding="utf-8")

    with pytest.raises(GoldenCaseInvalid, match="is not a Feature"):
        harness.discover(root=tmp_path)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("{", "not valid JSON"),
        ("[]", "a case is an object"),
        ('{"expected": {}}', "missing 'input'"),
        ('{"input": {}}', "missing 'expected'"),
        ('{"input": {}, "expected": {}, "extra": 1}', "unknown key"),
        ('{"input": {"nope": 1}, "expected": {}}', "unknown input key"),
        ('{"input": {"untrusted": {"a": 1}}, "expected": {}}', "name -> text"),
        ('{"input": {}, "expected": []}', "`expected` is an object"),
        ('{"input": {}, "expected": {}, "tolerance": {"nope": 1}}', "unknown tolerance key"),
    ],
)
def test_a_malformed_case_is_refused_loudly(tmp_path: Path, payload: str, message: str):
    """A golden set that silently skips a case is a gate reporting a pass it did
    not earn. Every malformed shape raises."""
    directory = tmp_path / "resume_extract"
    directory.mkdir()
    (directory / "a.json").write_text(payload, encoding="utf-8")

    with pytest.raises(GoldenCaseInvalid, match=message):
        harness.discover(root=tmp_path)


def test_a_case_cannot_lower_the_precision_threshold(tmp_path: Path):
    """A fixture that could relax its own bar is not a bar.

    This is the shape the gate gets defeated in: not by deleting the threshold,
    but by one case with a comment saying it is an unusual résumé.
    """
    directory = tmp_path / "resume_extract"
    directory.mkdir()
    (directory / "a.json").write_text(
        '{"input": {}, "expected": {}, "tolerance": {"min_precision": 0.5}}', encoding="utf-8"
    )

    with pytest.raises(GoldenCaseInvalid, match="below the gate"):
        harness.discover(root=tmp_path)


def test_a_case_may_raise_its_own_threshold(tmp_path: Path):
    directory = tmp_path / "resume_extract"
    directory.mkdir()
    (directory / "a.json").write_text(
        '{"input": {}, "expected": {}, "tolerance": {"min_precision": 1.0}}', encoding="utf-8"
    )

    assert harness.discover(root=tmp_path)[0].min_precision == 1.0


def test_build_request_uses_the_prompt_not_the_fixture(synthetic):
    """A fixture that supplied its own system string would test the fixture."""
    prompts, golden = synthetic
    prompt = prompt_mod.latest(Feature.RESUME_EXTRACT, prompts)
    case = harness.discover(root=golden)[0]

    request = harness.build_request(prompt, case)

    assert isinstance(request, LLMRequest)
    assert request.system == prompt.render()
    assert request.prompt_version == "resume_extract/v1"
    assert request.untrusted == {"resume_text": "Python and Django at Acme Ltd."}


def test_build_request_refuses_a_case_that_omits_a_declared_slot(synthetic, tmp_path: Path):
    """Otherwise the rendered prompt points at an empty region and the model
    answers from nothing - producing a confident, entirely invented result."""
    prompts, _ = synthetic
    prompt = prompt_mod.latest(Feature.RESUME_EXTRACT, prompts)
    directory = tmp_path / "empty" / "resume_extract"
    directory.mkdir(parents=True)
    (directory / "a.json").write_text('{"input": {}, "expected": {}}', encoding="utf-8")
    case = harness.discover(root=tmp_path / "empty")[0]

    with pytest.raises(GoldenCaseInvalid, match="does not supply"):
        harness.build_request(prompt, case)


async def test_the_synthetic_case_runs_end_to_end(synthetic):
    """The whole fake mode, on data this file owns - so the mode is proven
    working before any real prompt exists to run through it."""
    prompts, golden = synthetic
    prompt = prompt_mod.latest(Feature.RESUME_EXTRACT, prompts)
    case = harness.discover(root=golden)[0]

    result = await FakeLLM().complete_json(harness.build_request(prompt, case), Tiny)

    assert isinstance(result.value, Tiny)
    assert result.response.prompt_version == "resume_extract/v1"


def test_the_rendered_prompt_and_the_data_block_agree(synthetic):
    """The header the prompt points at is the header the block writes.

    Two independent pieces of code produce `[resume_text]`; if either changes
    format, the prompt refers to a region label the model never sees.
    """
    prompts, golden = synthetic
    prompt = prompt_mod.latest(Feature.RESUME_EXTRACT, prompts)
    case = harness.discover(root=golden)[0]

    block = render_untrusted(case.untrusted, nonce="fixed").text

    for slot in prompt.untrusted_slots:
        assert f"[{slot}]" in prompt.render()
        assert f"[{slot}]" in block


def test_source_text_is_everything_the_model_saw(synthetic):
    """The fabrication check compares against this, so it has to be the union
    of the slots rather than one of them."""
    _, golden = synthetic
    case = harness.discover(root=golden)[0]

    assert case.source_text == "Python and Django at Acme Ltd."
