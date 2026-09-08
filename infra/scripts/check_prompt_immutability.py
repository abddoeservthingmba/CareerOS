#!/usr/bin/env python
"""A prompt that has run in production is immutable - `AC-AI-07.2`.

`05-ai-layer.md` §7: "A prompt is **immutable once used in production**. An
improvement creates `v<N+1>`. This is what makes `prompt_version` on a stored
artifact meaningful."

That last sentence is the whole justification, and it is easy to read past.
Every extracted résumé, every match rationale, every generated application pack
stores the string `<feature>/v<N>` and nothing else - not the prompt text. So
the text is retrievable only for as long as `v<N>` still says what it said when
it produced that output. Edit `v1` and you have not changed a prompt; you have
silently rewritten the provenance of every artifact that names it (HR-9), and
"why did it answer that in September" becomes unanswerable.

The failure mode is entirely benign in appearance. Someone tightens a sentence
that was producing mediocre extractions. It is an improvement. Nobody would
object in review. The gate exists because there is nothing about the edit that
*looks* wrong.

**Checked against a committed manifest**, `packages/contracts/prompts-in-production.json`,
rather than against the database. CI has no production credential and should not
be given one, and a committed file makes "this version is live" a reviewable
line in a diff instead of a state only the database knows.

    py infra/scripts/check_prompt_immutability.py
    py infra/scripts/check_prompt_immutability.py --record resume_extract/v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "packages" / "contracts" / "prompts-in-production.json"
PROMPT_ROOT = REPO_ROOT / "apps" / "api" / "app" / "ai" / "prompts"


def today() -> str:
    """`AC-FOUND-03.1`: nothing reads the wall clock except `core/clock.py`.

    Including a script. The rule looks like overkill here - a `first_seen` date
    in a manifest is not time-sensitive logic - but the value of "one module
    reads the clock" is that it has no exceptions to remember, and an exception
    for scripts is the one that gets copied.
    """
    sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
    from app.core import clock

    return clock.now().date().isoformat()


def prompt_path(prompt_version: str) -> Path:
    """`resume_extract/v1` -> `.../prompts/resume_extract/v1.md`."""
    feature, _, version = prompt_version.partition("/")
    return PROMPT_ROOT / feature / f"{version}.md"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest() -> dict[str, dict[str, str]]:
    if not MANIFEST.is_file():
        raise SystemExit(
            f"{MANIFEST.relative_to(REPO_ROOT).as_posix()} is missing. Without it, "
            "no prompt is protected."
        )
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    prompts = data.get("prompts")
    if not isinstance(prompts, dict):
        raise SystemExit(f"{MANIFEST.name}: `prompts` must be an object")
    return prompts


def check() -> list[str]:
    """Every manifested version still hashes to what it hashed to."""
    failures: list[str] = []
    for prompt_version, entry in sorted(load_manifest().items()):
        path = prompt_path(prompt_version)
        recorded = str(entry.get("sha256", ""))

        if not path.is_file():
            failures.append(
                f"{prompt_version}: {path.relative_to(REPO_ROOT).as_posix()} has been "
                "deleted, but artifacts in production record this version. Restore "
                "it; a used version stays resolvable forever."
            )
            continue

        actual = digest(path)
        if actual != recorded:
            failures.append(
                f"{prompt_version} has been edited but has already run in "
                f"production.\n"
                f"      recorded {recorded[:16]}...  now {actual[:16]}...\n"
                f"      Create the next version instead:\n"
                f"        cp {path.relative_to(REPO_ROOT).as_posix()} "
                f"{_next_version_path(path).relative_to(REPO_ROOT).as_posix()}\n"
                f"      then bump `version:` in its front matter and add a changelog "
                f"line.\n"
                f"      Editing this file rewrites the provenance of every artifact "
                f"that already recorded {prompt_version} (HR-9)."
            )
    return failures


def _next_version_path(path: Path) -> Path:
    number = int(path.stem.removeprefix("v"))
    return path.with_name(f"v{number + 1}.md")


def record(prompt_version: str, environment: str) -> int:
    """Add an entry. Run by the deploy that first uses a version.

    Refuses to overwrite an existing entry: doing so is how the whole control
    gets defeated in one commit, and it would look like housekeeping.
    """
    path = prompt_path(prompt_version)
    if not path.is_file():
        print(
            f"error: {path.relative_to(REPO_ROOT).as_posix()} does not exist",
            file=sys.stderr,
        )
        return 1

    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    prompts: dict[str, dict[str, str]] = data["prompts"]
    if prompt_version in prompts:
        print(
            f"error: {prompt_version} is already recorded. An entry is never "
            "rewritten - that would make the file agree with any edit. Create "
            "the next version.",
            file=sys.stderr,
        )
        return 1

    prompts[prompt_version] = {
        "sha256": digest(path),
        "first_seen": today(),
        "environment": environment,
    }
    data["prompts"] = dict(sorted(prompts.items()))
    MANIFEST.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"recorded {prompt_version} ({environment})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record",
        metavar="FEATURE/vN",
        help="record a version as live; run by the deploy that first uses it",
    )
    parser.add_argument("--environment", default="prod", choices=["prod", "staging"])
    args = parser.parse_args()

    if args.record:
        return record(args.record, args.environment)

    failures = check()
    if not failures:
        count = len(load_manifest())
        print(f"prompt-immutability: {count} live version(s) unchanged")
        return 0

    print("prompt-immutability FAILED\n", file=sys.stderr)
    for failure in failures:
        print(f"  - {failure}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
