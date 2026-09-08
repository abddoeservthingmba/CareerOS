"""T-AI-02.2 - model identifiers are configuration, never code.

`AC-AI-02.2`: "No model identifier string appears in any `.py` file (checked
against a pattern list for the known provider naming shapes)."

`05-ai-layer.md` §2 gives the reason plainly: "Gemini model names and free-tier
limits change often enough that a hard-coded name is a scheduled outage."
"""

from __future__ import annotations

import re
from pathlib import Path

# The naming shapes the known providers use.
MODEL_PATTERNS = (
    re.compile(r"\bgemini-[0-9][\w.-]*", re.I),
    re.compile(r"\bmodels/gemini[\w./-]*", re.I),
    re.compile(r"\btext-embedding-\d[\w-]*", re.I),
    re.compile(r"\bembedding-\d{3}\b", re.I),
    re.compile(r"\bgpt-[0-9o][\w.-]*", re.I),
    re.compile(r"\bclaude-[0-9][\w.-]*", re.I),
    re.compile(r"\bclaude-(?:opus|sonnet|haiku)-[\w.-]*", re.I),
    re.compile(r"\bllama-?[0-9][\w.:-]*", re.I),
    re.compile(r"\bmistral-(?:large|small|medium)[\w.-]*", re.I),
)

SEARCH_ROOTS = ("apps/api/app", "infra/scripts")

# The fake provider names its own model, which is not a provider's identifier
# and cannot become one - `AC-AI-02.2` is about names that change under us.
# The test file that asserts this rule necessarily contains the patterns.
ALLOWED = (
    "apps/api/app/ai/fake.py",
    "apps/api/tests/spec/test_no_model_literals.py",
)


def test_no_model_identifier_in_any_python_file(repo: Path):
    """AC-AI-02.2."""
    offenders: list[str] = []
    for root in SEARCH_ROOTS:
        base = repo / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            relative = path.relative_to(repo).as_posix()
            if relative in ALLOWED:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
                for pattern in MODEL_PATTERNS:
                    found = pattern.search(line)
                    if found:
                        offenders.append(f"{relative}:{number}: {found.group(0)}")
    assert offenders == [], (
        "model ids come from Settings (GEMINI_MODEL_FAST and friends), never "
        "from a literal:\n" + "\n".join(offenders)
    )


def test_the_model_settings_exist_and_are_empty_by_default():
    """The mechanism the rule depends on: a model id has somewhere to come from,
    and no code default that could mask a missing one."""
    from app.core.config import Settings

    for name in ("GEMINI_MODEL_FAST", "GEMINI_MODEL_QUALITY", "GEMINI_EMBEDDING_MODEL"):
        field = Settings.model_fields[name]
        assert field.default == "", f"{name} must not carry a hard-coded model id"


def test_the_patterns_actually_match_real_model_names():
    """A pattern list that matches nothing would make this check vacuous."""
    samples = (
        "gemini-2.5-flash",
        "models/gemini-2.5-pro",
        "text-embedding-004",
        "gpt-4o-mini",
        "claude-sonnet-4-5",
        "llama3.1:8b",
        "mistral-large-latest",
    )
    for sample in samples:
        assert any(p.search(sample) for p in MODEL_PATTERNS), sample
