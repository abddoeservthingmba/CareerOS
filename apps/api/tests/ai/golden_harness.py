"""The golden-test harness - `AI-07` §7.

Not a test module (no `test_` prefix, so pytest does not collect it). It holds
the machinery both golden suites share, so `test_golden_fake.py` and
`test_extraction_precision.py` measure the same things the same way. Two
harnesses would drift, and the nightly one is the one nobody watches.

`05-ai-layer.md` §7 sets the shape: `(input, expected)` pairs under
`tests/ai/golden/<feature>/`, run "against the **fake provider** on every CI
run (deterministic, asserts the prompt renders and the schema parses), and
against the **real provider** nightly ... with tolerance-based assertions (field
presence, precision thresholds, no fabrication) rather than string equality".

**Why precision and not accuracy.** Precision asks: of what the model said, how
much was right. Recall asks: of what was there, how much did it find. For this
product they are not interchangeable and the choice is not a statistical
preference. A résumé extraction that misses a skill produces a slightly worse
match. One that *invents* a skill puts a claim the user never made into an
application pack they may send to an employer, and the user is the one who
answers for it. Missing is a quality problem; inventing is a lie with the
user's name on it. So the gate is on precision, and the fabrication check below
is separate and absolute.

**Why `grounded_in` exists as well.** Comparing against `expected` catches a
value that is wrong. It does not catch a value that is *invented* in a field
nobody labelled. `grounded_in` asserts every extracted string actually occurs
in the source text, which is the property that has to hold whatever the labels
say - and it needs no hand-labelling, so it applies to every case for free.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.ai.base import Feature, LLMRequest, Message
from app.ai.prompt import Prompt

GOLDEN_ROOT = Path(__file__).parent / "golden"

#: Fields `AC-AI-07.5` names, and the threshold the P2 exit gate sets
#: (`00-scope-and-phases.md` §4).
PRECISION_FIELDS = ("skills", "employers")
MIN_PRECISION = 0.90

#: `AC-AI-07.5`: "across the 10-resume golden set".
REQUIRED_RESUME_CASES = 10

_WHITESPACE = re.compile(r"\s+")


class GoldenCaseInvalid(Exception):
    """A fixture is malformed. Loud, because a golden set that silently skips a
    case is a gate that reports a pass it did not earn."""


@dataclass(frozen=True, slots=True)
class Case:
    """One `(input, expected)` pair."""

    feature: Feature
    name: str
    path: Path
    description: str
    #: Name -> text, exactly as it goes into `LLMRequest.untrusted`.
    untrusted: Mapping[str, str]
    messages: tuple[Message, ...]
    expected: Mapping[str, Any]
    #: Per-case override of `MIN_PRECISION`. Raising it is fine; a case that
    #: lowers it is refused by `load_case`, because a threshold a fixture can
    #: relax is not a threshold.
    min_precision: float = MIN_PRECISION
    precision_fields: tuple[str, ...] = PRECISION_FIELDS
    _tags: tuple[str, ...] = field(default=(), repr=False)

    @property
    def source_text(self) -> str:
        """Everything the model was shown, for the fabrication check."""
        return "\n".join(self.untrusted[name] for name in sorted(self.untrusted))


def load_case(path: Path) -> Case:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GoldenCaseInvalid(f"{path}: not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise GoldenCaseInvalid(f"{path}: a case is an object")

    feature_name = path.parent.name
    try:
        feature = Feature(feature_name)
    except ValueError as exc:
        raise GoldenCaseInvalid(
            f"{path}: {feature_name!r} is not a Feature; golden cases live in "
            "tests/ai/golden/<feature>/"
        ) from exc

    if unknown := sorted(set(raw) - {"description", "input", "expected", "tolerance"}):
        raise GoldenCaseInvalid(f"{path}: unknown key(s) {unknown}")
    for required in ("input", "expected"):
        if required not in raw:
            raise GoldenCaseInvalid(f"{path}: missing {required!r}")

    payload = raw["input"]
    if not isinstance(payload, dict):
        raise GoldenCaseInvalid(f"{path}: `input` is an object")
    if unknown := sorted(set(payload) - {"untrusted", "messages"}):
        raise GoldenCaseInvalid(f"{path}: unknown input key(s) {unknown}")

    untrusted = payload.get("untrusted") or {}
    if not isinstance(untrusted, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in untrusted.items()
    ):
        raise GoldenCaseInvalid(f"{path}: `input.untrusted` is name -> text")

    messages = tuple(
        Message(role=m["role"], content=m["content"]) for m in payload.get("messages") or []
    )

    expected = raw["expected"]
    if not isinstance(expected, dict):
        raise GoldenCaseInvalid(f"{path}: `expected` is an object")

    tolerance = raw.get("tolerance") or {}
    if not isinstance(tolerance, dict):
        raise GoldenCaseInvalid(f"{path}: `tolerance` is an object")
    if unknown := sorted(set(tolerance) - {"min_precision", "precision_fields"}):
        raise GoldenCaseInvalid(f"{path}: unknown tolerance key(s) {unknown}")

    minimum = float(tolerance.get("min_precision", MIN_PRECISION))
    if minimum < MIN_PRECISION:
        raise GoldenCaseInvalid(
            f"{path}: min_precision {minimum} is below the gate's {MIN_PRECISION}. A "
            "fixture cannot lower the bar it is measured against - that turns a "
            "failing case into a passing one with no code change and no review."
        )

    fields = tuple(tolerance.get("precision_fields", PRECISION_FIELDS))

    return Case(
        feature=feature,
        name=path.stem,
        path=path,
        description=str(raw.get("description", "")),
        untrusted=dict(untrusted),
        messages=messages,
        expected=dict(expected),
        min_precision=minimum,
        precision_fields=fields,
    )


def discover(feature: Feature | None = None, root: Path | None = None) -> list[Case]:
    """Every case, or every case for one feature, in a stable order."""
    base = root if root is not None else GOLDEN_ROOT
    if not base.is_dir():
        return []
    pattern = f"{feature.value}/*.json" if feature is not None else "*/*.json"
    return [load_case(path) for path in sorted(base.glob(pattern))]


def features_with_cases(root: Path | None = None) -> set[Feature]:
    return {case.feature for case in discover(root=root)}


def build_request(prompt: Prompt, case: Case) -> LLMRequest:
    """The request a feature module would make for this case.

    Built from the prompt rather than from the fixture, so a golden run
    exercises the real rendering path: `prompt.render()` for the system text,
    and the case's content in `untrusted` where `untrusted.py` will fence it.
    A fixture that supplied its own system string would test the fixture.
    """
    missing = sorted(set(prompt.untrusted_slots) - set(case.untrusted))
    if missing:
        raise GoldenCaseInvalid(
            f"{case.path}: {prompt.prompt_version} declares slot(s) {missing} that "
            "this case does not supply, so the prompt would point at an empty region."
        )
    return LLMRequest(
        feature=prompt.feature,
        system=prompt.render(),
        messages=case.messages,
        untrusted=dict(case.untrusted),
        prompt_version=prompt.prompt_version,
    )


# -- the measurements ---------------------------------------------------------


def normalise(value: object) -> str:
    """Casefolded, whitespace-collapsed, punctuation-trimmed.

    `"Python"`, `"python"` and `" Python "` are the same skill. Comparing raw
    strings would make the precision figure a measurement of formatting.
    """
    return _WHITESPACE.sub(" ", str(value).strip().strip(".,;:")).casefold()


def _bag(values: object) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        return [normalise(values)]
    if isinstance(values, Mapping):
        return [normalise(v) for v in values.values()]
    if isinstance(values, Sequence):
        out: list[str] = []
        for item in values:
            # An employer is usually an object; the name is what is being
            # measured, and a dict with no name is a fabrication of a different
            # kind, so it is counted rather than dropped.
            if isinstance(item, Mapping):
                out.append(normalise(item.get("name") or item.get("value") or json.dumps(item)))
            else:
                out.append(normalise(item))
        return out
    return [normalise(values)]


@dataclass(frozen=True, slots=True)
class FieldPrecision:
    field: str
    matched: int
    produced: int
    wrong: tuple[str, ...]

    @property
    def precision(self) -> float:
        """1.0 for an empty answer.

        Deliberate: saying nothing invents nothing, so it cannot fail a
        *precision* gate. Recall is what an empty answer fails, and that is
        measured separately - conflating them would let a threshold be met by a
        model that answered less and less.
        """
        return 1.0 if self.produced == 0 else self.matched / self.produced


def precision(expected: Mapping[str, Any], actual: Mapping[str, Any], name: str) -> FieldPrecision:
    """Of what the model produced for `name`, how much was in the labels."""
    wanted = _bag(expected.get(name))
    got = _bag(actual.get(name))
    remaining = list(wanted)
    matched = 0
    wrong: list[str] = []
    for item in got:
        if item in remaining:
            remaining.remove(item)
            matched += 1
        else:
            wrong.append(item)
    return FieldPrecision(field=name, matched=matched, produced=len(got), wrong=tuple(wrong))


def recall(expected: Mapping[str, Any], actual: Mapping[str, Any], name: str) -> float:
    """Reported, never gated. A missed skill is a worse match; an invented one
    is a false claim in a document the user sends."""
    wanted = _bag(expected.get(name))
    if not wanted:
        return 1.0
    got = list(_bag(actual.get(name)))
    found = 0
    for item in wanted:
        if item in got:
            got.remove(item)
            found += 1
    return found / len(wanted)


def overall_precision(
    expected: Mapping[str, Any], actual: Mapping[str, Any], fields: Iterable[str]
) -> float:
    """Micro-averaged over the named fields.

    Micro rather than macro: a field with forty skills and a field with two
    employers should not weigh the same, and macro-averaging lets a perfect
    two-item field cover a bad forty-item one.
    """
    matched = produced = 0
    for name in fields:
        result = precision(expected, actual, name)
        matched += result.matched
        produced += result.produced
    return 1.0 if produced == 0 else matched / produced


def ungrounded(actual: Mapping[str, Any], source: str, fields: Iterable[str]) -> list[str]:
    """Values the model produced that do not occur in what it was shown.

    The absolute check, independent of labels. A skill the résumé does not
    mention is a fabrication whether or not anyone labelled that résumé, and
    this is the assertion that would have caught it.
    """
    haystack = normalise(source)
    return [
        item for name in fields for item in _bag(actual.get(name)) if item and item not in haystack
    ]


# -- nightly accounting -------------------------------------------------------


#: §7: "Nightly real-provider runs write their spend to `ai_usage` under a
#: `feature` suffix of `:golden` so test spend is separable from user spend on
#: the dashboard."
GOLDEN_SUFFIX = ":golden"


def golden_feature(feature: Feature) -> str:
    """The `feature` value a nightly row carries.

    A suffix rather than a separate collection, so the dashboard's per-feature
    grouping needs no special case and the nightly spend is visible in the same
    place as everything else - but a `WHERE feature NOT LIKE '%:golden'` is
    enough to exclude it. Test spend hidden in its own table is test spend
    nobody notices doubling.
    """
    return f"{feature.value}{GOLDEN_SUFFIX}"


def record_golden_call(
    provider: str,
    model: str,
    feature: Feature,
    *,
    prompt_version: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    cost_usd: Any | None,
) -> dict[str, Any]:
    """Buffer one nightly row. Returns it, so a test can assert its shape.

    Goes through `build_row` rather than writing a dict directly: the outcome
    and cost rules (`AC-AI-04.3`'s "never zero for an unknown price") are the
    same for test spend as for user spend, and a second code path would be the
    one that got them wrong.
    """
    from app.ai.usage import RECORDER, Outcome, build_row

    row = build_row(
        provider=provider,
        model=model,
        feature=golden_feature(feature),
        outcome=Outcome.OK,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        est_cost_usd=cost_usd,
        latency_ms=latency_ms,
        prompt_version=prompt_version,
    )
    RECORDER.record(row)
    return row


__all__ = [
    "GOLDEN_ROOT",
    "GOLDEN_SUFFIX",
    "MIN_PRECISION",
    "PRECISION_FIELDS",
    "REQUIRED_RESUME_CASES",
    "Case",
    "FieldPrecision",
    "GoldenCaseInvalid",
    "build_request",
    "discover",
    "features_with_cases",
    "golden_feature",
    "load_case",
    "normalise",
    "overall_precision",
    "precision",
    "recall",
    "record_golden_call",
    "ungrounded",
]
