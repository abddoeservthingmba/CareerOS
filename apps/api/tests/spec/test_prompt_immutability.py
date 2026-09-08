"""T-AI-07.2 - a prompt that has run in production cannot be edited.

`AC-AI-07.2`: "Editing a prompt file whose version has been used in production
(detected by presence in `ai_usage` on staging or prod, checked in CI against a
committed manifest) fails CI with a message to create the next version."

The named test location is the `prompt-immutability` step in `api-ci.yml`. This
file is the other half: it asserts the step exists and wires to the right
script, and it exercises the script's logic - which has real branches and would
otherwise be code that only ever runs in CI, where a bug in it looks exactly
like a pass.

**What the control is actually protecting.** Every extracted résumé, every
match rationale, every generated application pack stores the string
`<feature>/v<N>` and nothing else - not the prompt text. So the text is
retrievable only for as long as `v<N>` still says what it said when it produced
that output. Editing `v1` does not change a prompt; it silently rewrites the
provenance of every artifact that names it (HR-9), and "why did it answer that
in September" stops having an answer.

The failure mode is entirely benign in appearance: someone tightens a sentence
that was producing mediocre extractions. It is an improvement, and nobody would
object in review. That is why this is a gate rather than a convention - there is
nothing about the edit that looks wrong.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SCRIPT = Path("infra") / "scripts" / "check_prompt_immutability.py"
MANIFEST = Path("packages") / "contracts" / "prompts-in-production.json"
WORKFLOW = Path(".github") / "workflows" / "api-ci.yml"
STEP_NAME = "prompt-immutability"


@pytest.fixture
def checker(repo: Path):
    """The script, imported as a module with its paths pointed at a temporary
    repository - so the failure branches can be exercised without committing a
    tampered prompt."""
    sys.path.insert(0, str(repo / "infra" / "scripts"))
    import check_prompt_immutability as module

    return module


# -- the CI step exists and runs the right thing ------------------------------


def test_the_workflow_has_the_step_the_spec_names(repo: Path):
    """`T-AI-07.2` names `.github/workflows/api-ci.yml` step
    `prompt-immutability`. A test that only checked the script would pass with
    the script never being run."""
    workflow = yaml.safe_load((repo / WORKFLOW).read_text(encoding="utf-8"))
    steps = workflow["jobs"]["checks"]["steps"]
    names = [step.get("name") for step in steps]

    assert STEP_NAME in names, f"api-ci.yml has no {STEP_NAME!r} step; it has {names}"


def test_the_step_invokes_the_checker(repo: Path):
    workflow = yaml.safe_load((repo / WORKFLOW).read_text(encoding="utf-8"))
    step = next(s for s in workflow["jobs"]["checks"]["steps"] if s.get("name") == STEP_NAME)

    assert "check_prompt_immutability.py" in step["run"]


def test_the_step_is_not_allowed_to_fail(repo: Path):
    """`continue-on-error` here would make the gate advisory, which is the same
    as absent - nobody reads a green build's warnings."""
    workflow = yaml.safe_load((repo / WORKFLOW).read_text(encoding="utf-8"))
    step = next(s for s in workflow["jobs"]["checks"]["steps"] if s.get("name") == STEP_NAME)

    assert step.get("continue-on-error") in (None, False)


def test_the_checker_exists_and_runs_clean(repo: Path):
    """End to end, against the real repository. Passes today because the
    manifest is empty; it starts doing work with the first entry."""
    result = subprocess.run(  # noqa: S603 - our own script, fixed argv
        [sys.executable, str(repo / SCRIPT)],
        capture_output=True,
        text=True,
        cwd=repo,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "unchanged" in result.stdout


# -- the manifest -------------------------------------------------------------


def test_the_manifest_is_committed_and_well_formed(repo: Path):
    """Without it, no prompt is protected - and its absence would look like
    "no live prompts yet", which is indistinguishable from correct."""
    data = json.loads((repo / MANIFEST).read_text(encoding="utf-8"))

    assert isinstance(data["prompts"], dict)
    assert data["version"] >= 1


def test_the_manifest_explains_itself(repo: Path):
    """Whoever hits this gate for the first time reads the manifest before the
    spec. It has to say why an entry is never removed."""
    comment = " ".join(json.loads((repo / MANIFEST).read_text(encoding="utf-8"))["$comment"])

    assert "never removed" in comment
    assert "ai_usage" in comment


def test_the_manifest_is_empty_because_nothing_has_run(repo: Path):
    """Stated so the first entry is a visible change to this expectation rather
    than a silent one, and so an accidentally-populated manifest fails."""
    data = json.loads((repo / MANIFEST).read_text(encoding="utf-8"))

    assert data["prompts"] == {}, (
        "a prompt is recorded as live. Delete this assertion and replace it with "
        "one that asserts each entry's file exists - the checker already does the "
        "hashing."
    )


# -- the checker's logic ------------------------------------------------------


def _world(tmp_path: Path, checker, *, body: str, recorded_hash: str | None):
    """Point the checker at a temporary repository with one prompt."""
    prompts = tmp_path / "prompts" / "resume_extract"
    prompts.mkdir(parents=True)
    path = prompts / "v1.md"
    path.write_text(body, encoding="utf-8")

    manifest = tmp_path / "manifest.json"
    entry = (
        {}
        if recorded_hash is None
        else {
            "resume_extract/v1": {
                "sha256": recorded_hash,
                "first_seen": "2026-09-01",
                "environment": "prod",
            }
        }
    )
    manifest.write_text(json.dumps({"version": 1, "prompts": entry}), encoding="utf-8")

    checker.PROMPT_ROOT = tmp_path / "prompts"
    checker.MANIFEST = manifest
    checker.REPO_ROOT = tmp_path
    return path


def test_an_unchanged_live_prompt_passes(tmp_path: Path, checker):
    """The ordinary case: the file still hashes to what the manifest recorded."""
    path = _world(tmp_path, checker, body="one\n", recorded_hash=None)
    manifest = json.loads(checker.MANIFEST.read_text(encoding="utf-8"))
    manifest["prompts"]["resume_extract/v1"] = {
        "sha256": checker.digest(path),
        "first_seen": "2026-09-01",
        "environment": "prod",
    }
    checker.MANIFEST.write_text(json.dumps(manifest), encoding="utf-8")

    assert checker.check() == []


def test_an_edited_live_prompt_fails(tmp_path: Path, checker):
    """The criterion. The message has to say what to do, because the person
    reading it believes they made an improvement - and they did."""
    _world(tmp_path, checker, body="original\n", recorded_hash="0" * 64)

    failures = checker.check()

    assert len(failures) == 1
    assert "already run in production" in failures[0]
    assert "Create the next version" in failures[0]
    assert "v2.md" in failures[0], "the message must name the file to create"
    assert "provenance" in failures[0]


def test_a_deleted_live_prompt_fails(tmp_path: Path, checker):
    """Deletion is the other way to break a stored `prompt_version`, and it is
    the one a tidy-up commit does by accident."""
    path = _world(tmp_path, checker, body="original\n", recorded_hash="0" * 64)
    path.unlink()

    failures = checker.check()

    assert "has been deleted" in failures[0]
    assert "resolvable forever" in failures[0]


def test_a_prompt_that_has_not_run_is_not_frozen(tmp_path: Path, checker):
    """An unreleased prompt is still being written. Freezing it would mean a
    version bump for every typo before the feature ever shipped, and a rule
    that inconvenient gets removed rather than followed."""
    _world(tmp_path, checker, body="a draft, freely edited\n", recorded_hash=None)

    assert checker.check() == []


def test_recording_a_version_stores_its_hash(tmp_path: Path, checker):
    path = _world(tmp_path, checker, body="live now\n", recorded_hash=None)

    assert checker.record("resume_extract/v1", "prod") == 0

    stored = json.loads(checker.MANIFEST.read_text(encoding="utf-8"))["prompts"]
    assert stored["resume_extract/v1"]["sha256"] == checker.digest(path)
    assert stored["resume_extract/v1"]["environment"] == "prod"


def test_recording_refuses_to_overwrite_an_entry(tmp_path: Path, checker):
    """This is how the whole control gets defeated in one commit, and it would
    look like housekeeping: re-record the version, and the manifest agrees with
    whatever the file now says."""
    _world(tmp_path, checker, body="live\n", recorded_hash="0" * 64)

    assert checker.record("resume_extract/v1", "prod") == 1


def test_recording_a_missing_file_fails(tmp_path: Path, checker):
    _world(tmp_path, checker, body="live\n", recorded_hash=None)

    assert checker.record("job_enrich/v1", "prod") == 1


def test_the_next_version_path_increments(tmp_path: Path, checker):
    assert checker._next_version_path(Path("a/v1.md")).name == "v2.md"
    assert checker._next_version_path(Path("a/v9.md")).name == "v10.md"
