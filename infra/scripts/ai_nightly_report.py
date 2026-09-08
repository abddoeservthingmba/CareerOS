#!/usr/bin/env python
"""The nightly AI report - `AC-AI-07.4`.

"The nightly `real_ai` run posts a report: per feature, pass/fail, tokens, cost,
and any tolerance breach."

**Why a report and not just a red build.** A nightly suite that only goes red is
a nightly suite people stop reading. The interesting states are the ones between
pass and fail: precision at 91% and drifting down, a tolerance breach in one
field, tokens up 40% because a prompt grew, a model that has quietly become
unpriced. None of those fail a build on the night they start, and all of them
are cheap to fix on the night they start and expensive three weeks later.

**Cost comes from `ai_usage`, not from a counter in the test.** §7 has nightly
spend written under a `:golden` feature suffix, which means the report and the
admin dashboard are reading the same rows through the same accounting path. A
separate tally in the harness would be a second source of truth for money, and
the two would disagree eventually - with no way to tell which was right.

Reads a JUnit XML for pass/fail, and `ai_usage` for tokens and cost. Both are
optional: with no database it reports the test results and says the spend is
unavailable, rather than failing and reporting nothing.

    py infra/scripts/ai_nightly_report.py --junit results.xml --out report.md
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

GOLDEN_SUFFIX = ":golden"

#: A failure message that names one of these is a tolerance breach rather than
#: a broken test - the distinction `AC-AI-07.4` asks the report to draw. Matched
#: on the assertion text the golden suites actually write.
BREACH_MARKERS = ("precision", "fabricat", "do not occur", "tolerance", "below the")


@dataclass
class FeatureResult:
    feature: str
    passed: int = 0
    failed: int = 0
    breaches: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    #: `None` means "no priced call recorded", which is not the same as $0.00.
    cost_usd: float | None = None
    unpriced_calls: int = 0

    @property
    def ok(self) -> bool:
        return self.failed == 0

    @property
    def status(self) -> str:
        return "pass" if self.ok else "FAIL"


def parse_junit(path: Path) -> dict[str, FeatureResult]:
    """Group test cases by the feature their name mentions.

    Grouping by name because the report is per feature and pytest reports per
    test. A test whose name names no feature is filed under `general`, which is
    visible in the report rather than dropped - a silently omitted failure is
    the one thing a report must not do.
    """
    results: dict[str, FeatureResult] = {}
    tree = ET.parse(path)

    for case in tree.iter("testcase"):
        name = f"{case.get('classname', '')}.{case.get('name', '')}"
        feature = _feature_of(name)
        result = results.setdefault(feature, FeatureResult(feature=feature))

        failures = list(case.iter("failure")) + list(case.iter("error"))
        if not failures:
            result.passed += 1
            continue

        result.failed += 1
        for failure in failures:
            message = (failure.get("message") or "").strip().split("\n")[0][:300]
            if any(marker in message.casefold() for marker in BREACH_MARKERS):
                result.breaches.append(f"{case.get('name')}: {message}")
            else:
                result.errors.append(f"{case.get('name')}: {message}")

    return results


def _feature_of(test_name: str) -> str:
    """The `Feature` a test's id mentions, or `general`.

    The enum is read rather than a list copied here, so a feature added to
    `Feature` is grouped by this report without anyone remembering to.
    """
    lowered = test_name.casefold()
    for value in _feature_values():
        if value in lowered:
            return value
    # `extraction` is what the résumé suite is called; map it rather than
    # renaming a test file to satisfy a report.
    if "extraction" in lowered or "resume" in lowered:
        return "resume_extract"
    return "general"


def _feature_values() -> list[str]:
    _add_app_to_path()
    try:
        from app.ai.base import Feature
    except ImportError:  # pragma: no cover - report still works without the app
        return []
    return [f.value for f in Feature]


def _add_app_to_path() -> None:
    path = str(Path(__file__).resolve().parents[2] / "apps" / "api")
    if path not in sys.path:
        sys.path.insert(0, path)


def _now() -> datetime:
    """`AC-FOUND-03.1`: one module reads the wall clock, and it is not this one.

    Read once and reused for both the window's start and its end, so a report
    cannot describe a window that drifted by however long the database query
    took - a small thing that makes "last 6h" not quite mean 6h, and is exactly
    the kind of discrepancy nobody can reproduce later.
    """
    _add_app_to_path()
    from app.core import clock

    return clock.now()


async def load_spend(uri: str, database: str, since: datetime) -> dict[str, FeatureResult]:
    """Tokens and cost per feature, from the `:golden` rows this run wrote."""
    from pymongo import AsyncMongoClient

    client: AsyncMongoClient = AsyncMongoClient(uri)
    try:
        rows = client[database]["ai_usage"].find(
            {
                "at": {"$gte": since},
                "feature": {"$regex": f"{re.escape(GOLDEN_SUFFIX)}$"},
            }
        )
        totals: dict[str, FeatureResult] = {}
        priced: dict[str, float] = defaultdict(float)
        seen_price: set[str] = set()
        async for row in rows:
            feature = str(row.get("feature", "")).removesuffix(GOLDEN_SUFFIX) or "general"
            result = totals.setdefault(feature, FeatureResult(feature=feature))
            result.input_tokens += int(row.get("input_tokens") or 0)
            result.output_tokens += int(row.get("output_tokens") or 0)
            cost = row.get("est_cost_usd")
            if cost is None:
                result.unpriced_calls += 1
            else:
                priced[feature] += float(cost)
                seen_price.add(feature)
        for feature in seen_price:
            totals[feature].cost_usd = priced[feature]
        return totals
    finally:
        await client.close()


def merge(tests: dict[str, FeatureResult], spend: dict[str, FeatureResult]) -> list[FeatureResult]:
    for feature, totals in spend.items():
        result = tests.setdefault(feature, FeatureResult(feature=feature))
        result.input_tokens = totals.input_tokens
        result.output_tokens = totals.output_tokens
        result.cost_usd = totals.cost_usd
        result.unpriced_calls = totals.unpriced_calls
    return sorted(tests.values(), key=lambda r: (r.ok, r.feature))


def render(results: list[FeatureResult], *, spend_available: bool, window: str) -> str:
    lines = [
        "# Nightly AI report",
        "",
        f"Window: {window}",
        "",
        "| Feature | Result | Passed | Failed | Input tok | Output tok | Cost |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    total_cost = 0.0
    any_priced = False
    for result in results:
        if result.cost_usd is None:
            cost = "unpriced" if result.unpriced_calls else "—"
        else:
            cost = f"${result.cost_usd:.4f}"
            total_cost += result.cost_usd
            any_priced = True
        lines.append(
            f"| `{result.feature}` | {result.status} | {result.passed} | {result.failed} "
            f"| {result.input_tokens:,} | {result.output_tokens:,} | {cost} |"
        )

    lines += [
        "",
        f"**Total cost:** {f'${total_cost:.4f}' if any_priced else 'unavailable'}",
    ]
    if not spend_available:
        lines.append("")
        lines.append(
            "> Spend was not read: no database was reachable. Tokens and cost above "
            "are zero because nothing was queried, **not** because nothing was spent."
        )

    breaches = [(r.feature, b) for r in results for b in r.breaches]
    lines += ["", "## Tolerance breaches", ""]
    if breaches:
        lines += [f"- `{feature}` — {detail}" for feature, detail in breaches]
    else:
        lines.append("None.")

    errors = [(r.feature, e) for r in results for e in r.errors]
    lines += ["", "## Other failures", ""]
    lines += [f"- `{feature}` — {detail}" for feature, detail in errors] or ["None."]

    unpriced = [r.feature for r in results if r.unpriced_calls]
    if unpriced:
        lines += [
            "",
            "## Unpriced models",
            "",
            (
                "Calls were made against a model with no entry in "
                f"`model-pricing.yaml`: {', '.join(f'`{f}`' for f in unpriced)}. Cost "
                "is unknown, not zero (`AC-AI-04.3`) — add the price and date it."
            ),
        ]

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the nightly AI report")
    parser.add_argument("--junit", type=Path, required=True, help="pytest --junitxml output")
    parser.add_argument("--out", type=Path, help="write here instead of stdout")
    parser.add_argument("--hours", type=int, default=6, help="how far back to read :golden spend")
    args = parser.parse_args()

    if not args.junit.is_file():
        print(f"error: {args.junit} does not exist", file=sys.stderr)
        return 1

    tests = parse_junit(args.junit)

    now = _now()
    since = now - timedelta(hours=args.hours)
    uri = os.environ.get("MONGODB_URI", "")
    database = os.environ.get("MONGODB_DB", "jobpilot")
    spend: dict[str, FeatureResult] = {}
    spend_available = False
    if uri:
        try:
            spend = asyncio.run(load_spend(uri, database, since))
            spend_available = True
        except Exception as failure:  # noqa: BLE001 - a report must still be posted
            print(f"warning: could not read ai_usage: {failure}", file=sys.stderr)

    results = merge(tests, spend)
    report = render(
        results,
        spend_available=spend_available,
        window=f"last {args.hours}h, to {now.isoformat(timespec='minutes')} (UTC)",
    )

    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(report)

    # Non-zero if anything failed, so the workflow is red as well as informative.
    return 1 if any(not result.ok for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
