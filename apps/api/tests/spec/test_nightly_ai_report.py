"""T-AI-07.4 - the nightly report says what `AC-AI-07.4` requires it to say.

`AC-AI-07.4`: "The nightly `real_ai` run posts a report: per feature, pass/fail,
tokens, cost, and any tolerance breach."

The named test location is `.github/workflows/nightly-ai.yml`. This file asserts
that the workflow exists and is wired correctly, and that the renderer produces
the five things the criterion lists - because a report that quietly omits one of
them is a report that reads as complete.

**Why the report's failure behaviour is tested at all.** The report is the only
artifact anyone looks at, so its bugs are invisible by construction: if it drops
a failure, the night looks fine. Two of the assertions below exist for exactly
that - `test_a_tolerance_breach_is_reported_separately` and
`test_missing_spend_is_stated_rather_than_shown_as_zero`. The second is the one
that matters most in practice. A cost column reading `$0.0000` because the
database was unreachable is a lie the same shape as good news.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(".github") / "workflows" / "nightly-ai.yml"
SCRIPT = Path("infra") / "scripts" / "ai_nightly_report.py"

JUNIT = """\
<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="3">
  <testcase classname="tests.ai.test_extraction_precision" name="test_precision_over_the_set">
    <failure message="field-level precision is 71.4%, below the P2 exit gate">..</failure>
  </testcase>
  <testcase classname="tests.ai.test_golden_real" name="test_job_enrich_shape"/>
  <testcase classname="tests.ai.test_golden_real" name="test_pack_generate_smoke">
    <error message="httpx.ConnectTimeout">...</error>
  </testcase>
</testsuite></testsuites>
"""


@pytest.fixture
def report_module(repo: Path):
    sys.path.insert(0, str(repo / "infra" / "scripts"))
    import ai_nightly_report as module

    return module


@pytest.fixture
def junit(tmp_path: Path) -> Path:
    path = tmp_path / "junit.xml"
    path.write_text(JUNIT, encoding="utf-8")
    return path


# -- the workflow -------------------------------------------------------------


def test_the_workflow_exists(repo: Path):
    assert (repo / WORKFLOW).is_file()


def test_it_runs_nightly_on_a_schedule(repo: Path):
    """ "Nightly" is the requirement, not "on demand". A `workflow_dispatch`-only
    workflow is one that runs the week someone remembers it."""
    workflow = yaml.safe_load((repo / WORKFLOW).read_text(encoding="utf-8"))
    # PyYAML parses a bare `on` key as the boolean True.
    triggers = workflow.get("on") or workflow.get(True)

    assert "schedule" in triggers
    assert triggers["schedule"][0]["cron"].endswith("* * *")


def test_it_selects_the_real_ai_marker(repo: Path):
    """§7's two modes are distinguished by the marker. A nightly run that used
    the default selection would run the fake suite again and report a pass
    against a provider it never called."""
    text = (repo / WORKFLOW).read_text(encoding="utf-8")

    assert "-m real_ai" in text


def test_it_overrides_the_default_deselection(repo: Path):
    """`pytest.ini` deselects `real_ai` for everyone, which would leave the
    nightly run selecting nothing and passing.

    This is the trap in the arrangement: `addopts` and `-m` do not merge, the
    `addopts` filter wins, and the result is a green run of zero tests. So the
    workflow clears `addopts` explicitly.
    """
    text = (repo / WORKFLOW).read_text(encoding="utf-8")

    assert '-o addopts=""' in text


def test_it_renders_the_report_even_when_the_suite_fails(repo: Path):
    """The nights the report is most worth reading are the nights something
    failed, so rendering must not be conditional on success."""
    workflow = yaml.safe_load((repo / WORKFLOW).read_text(encoding="utf-8"))
    steps = {step.get("name"): step for step in workflow["jobs"]["golden"]["steps"]}

    assert steps["Run the golden set against the real provider"]["continue-on-error"] is True
    assert "if" not in steps["Render the report"]


def test_it_still_fails_the_job(repo: Path):
    """`continue-on-error` on the test step exists so the report is produced,
    not so the failure is swallowed. A nightly gate that reports green on a
    failed run is worse than no gate, because it is believed."""
    workflow = yaml.safe_load((repo / WORKFLOW).read_text(encoding="utf-8"))
    steps = {step.get("name"): step for step in workflow["jobs"]["golden"]["steps"]}
    guard = steps["Fail if the golden set failed"]

    assert "steps.golden.outcome != 'success'" in guard["if"]
    assert "exit 1" in guard["run"]


def test_it_publishes_the_report(repo: Path):
    """`AC-AI-07.4`'s "posts a report". An artifact and a step summary, so it is
    readable without downloading anything."""
    text = (repo / WORKFLOW).read_text(encoding="utf-8")

    assert "upload-artifact" in text
    assert "GITHUB_STEP_SUMMARY" in text


def test_the_credential_is_a_secret_not_a_literal(repo: Path):
    """`CLAUDE.md`: secrets never enter the repo. And `AC-AI-05.1`: the key
    belongs to the dedicated Cloud project, which the workflow comment names."""
    text = (repo / WORKFLOW).read_text(encoding="utf-8")

    assert "secrets.NIGHTLY_GEMINI_API_KEY" in text
    assert "AIza" not in text, "an API key literal is in the workflow"


# -- the report itself --------------------------------------------------------


def test_it_reports_pass_and_fail_per_feature(report_module, junit: Path):
    """`AC-AI-07.4`'s first two items."""
    results = report_module.merge(report_module.parse_junit(junit), {})
    rendered = report_module.render(results, spend_available=True, window="test")

    assert "| Feature | Result | Passed | Failed" in rendered
    assert "`resume_extract` | FAIL" in rendered
    assert "`job_enrich` | pass" in rendered


def test_it_reports_tokens_and_cost(report_module, junit: Path):
    """The other two. Both come from `ai_usage`, which is the same accounting
    path the admin dashboard reads - so the report and the dashboard cannot
    disagree about money."""
    spend = {
        "resume_extract": report_module.FeatureResult(
            feature="resume_extract", input_tokens=12_400, output_tokens=3_100, cost_usd=0.0182
        )
    }
    results = report_module.merge(report_module.parse_junit(junit), spend)
    rendered = report_module.render(results, spend_available=True, window="test")

    assert "12,400" in rendered
    assert "$0.0182" in rendered
    assert "**Total cost:** $0.0182" in rendered


def test_a_tolerance_breach_is_reported_separately(report_module, junit: Path):
    """§7's real mode uses "tolerance-based assertions", and `AC-AI-07.4` asks
    for breaches specifically.

    A precision miss and a connection timeout are not the same news: one is the
    model getting worse, the other is the network. Filing both under "failed"
    is how a real quality regression sits unnoticed behind a flaky night.
    """
    results = report_module.merge(report_module.parse_junit(junit), {})
    rendered = report_module.render(results, spend_available=True, window="test")

    breaches = rendered.split("## Tolerance breaches", 1)[1].split("##", 1)[0]
    others = rendered.split("## Other failures", 1)[1]

    assert "below the P2 exit gate" in breaches
    assert "ConnectTimeout" in others
    assert "ConnectTimeout" not in breaches


def test_no_breach_says_none_rather_than_nothing(report_module, tmp_path: Path):
    """An empty section reads as a rendering bug. "None." reads as an answer."""
    path = tmp_path / "clean.xml"
    path.write_text(
        '<testsuites><testsuite><testcase classname="a" name="test_job_enrich_ok"/>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    results = report_module.merge(report_module.parse_junit(path), {})

    rendered = report_module.render(results, spend_available=True, window="test")

    assert "## Tolerance breaches\n\nNone." in rendered


def test_missing_spend_is_stated_rather_than_shown_as_zero(report_module, junit: Path):
    """The most dangerous shape of report bug.

    A cost column of `$0.0000` because the database was unreachable is a lie
    the same shape as good news: the run looks cheap. So an unread spend says
    so, in the report, next to the zeros.
    """
    results = report_module.merge(report_module.parse_junit(junit), {})

    rendered = report_module.render(results, spend_available=False, window="test")

    assert "not read" in rendered
    assert "**not** because nothing was spent" in rendered
    assert "**Total cost:** unavailable" in rendered


def test_an_unpriced_model_is_called_unpriced_not_free(report_module, junit: Path):
    """`AC-AI-04.3` again, at the reporting layer. "$0.00" for a model with no
    price entry says the night was free, which is a claim - and the model
    somebody just switched to is exactly the one with no price."""
    spend = {
        "resume_extract": report_module.FeatureResult(
            feature="resume_extract", input_tokens=100, output_tokens=20, unpriced_calls=4
        )
    }
    results = report_module.merge(report_module.parse_junit(junit), spend)

    rendered = report_module.render(results, spend_available=True, window="test")

    assert "unpriced" in rendered
    assert "$0.0000" not in rendered
    assert "## Unpriced models" in rendered


def test_a_test_naming_no_feature_is_filed_visibly(report_module, tmp_path: Path):
    """Rather than dropped. A silently omitted failure is the one thing a report
    must not do, and "general" is at least visible."""
    path = tmp_path / "odd.xml"
    path.write_text(
        '<testsuites><testsuite><testcase classname="a" name="test_something"/>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )

    results = report_module.merge(report_module.parse_junit(path), {})

    assert [r.feature for r in results] == ["general"]


def test_the_feature_list_comes_from_the_enum(report_module):
    """So a feature added to `Feature` is grouped by this report without anyone
    remembering to update a list here."""
    from app.ai.base import Feature

    assert set(report_module._feature_values()) == {f.value for f in Feature}


def test_the_script_exits_non_zero_when_something_failed(repo: Path, junit: Path):
    """The workflow reads the exit code, so it has to be right.

    `MONGODB_URI` is removed rather than the whole environment replaced: on
    Windows an empty environment breaks `asyncio`'s own imports, which would
    make this test fail for a reason that has nothing to do with the script.
    """
    environment = {k: v for k, v in os.environ.items() if k != "MONGODB_URI"}
    result = subprocess.run(  # noqa: S603 - our own script, fixed argv
        [sys.executable, str(repo / SCRIPT), "--junit", str(junit)],
        capture_output=True,
        text=True,
        cwd=repo,
        check=False,
        env=environment,
    )

    assert result.returncode == 1
    assert "Nightly AI report" in result.stdout


def test_a_missing_junit_file_is_an_error_not_an_empty_report(repo: Path, tmp_path: Path):
    """An empty report for a run that never produced results would read as a
    clean night."""
    result = subprocess.run(  # noqa: S603 - our own script, fixed argv
        [sys.executable, str(repo / SCRIPT), "--junit", str(tmp_path / "nope.xml")],
        capture_output=True,
        text=True,
        cwd=repo,
        check=False,
    )

    assert result.returncode == 1
    assert "does not exist" in result.stderr
