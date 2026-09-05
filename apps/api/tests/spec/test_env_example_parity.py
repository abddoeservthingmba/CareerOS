"""T-FOUND-02.3 / T-OPS-05.1 - `.env.example` matches `Settings` exactly.

`AC-FOUND-02.3`: "Every field on `Settings` appears in `.env.example`, and every
key in `.env.example` maps to a field. No extras either way."

Shared with `T-OPS-05.2` (`AC-OPS-05.2`): no secret has a non-empty value in the
example.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import SecretStr

from app.core.config import Settings

KEY_LINE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def env_example(repo: Path) -> dict[str, str]:
    path = repo / ".env.example"
    assert path.is_file(), ".env.example is missing"
    out: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = KEY_LINE.match(line)
        assert match, f".env.example:{number}: unparseable {line!r}"
        key, value = match.group(1), match.group(2)
        assert key not in out, f".env.example:{number}: {key} appears twice"
        out[key] = value
    return out


def test_every_setting_appears_in_the_example(repo: Path):
    """AC-FOUND-02.3, first direction."""
    missing = sorted(set(Settings.model_fields) - set(env_example(repo)))
    assert missing == [], f"settings absent from .env.example: {missing}"


def test_every_example_key_maps_to_a_setting(repo: Path):
    """AC-FOUND-02.3, second direction. An orphan key is a variable someone
    sets in production expecting it to do something."""
    extra = sorted(set(env_example(repo)) - set(Settings.model_fields))
    assert extra == [], f".env.example keys with no Settings field: {extra}"


def test_no_secret_has_a_value_in_the_example(repo: Path):
    """AC-OPS-05.2."""
    example = env_example(repo)
    leaked = sorted(
        name
        for name, field in Settings.model_fields.items()
        if field.annotation is SecretStr and example.get(name, "")
    )
    assert leaked == [], f"secrets with a value in .env.example: {leaked}"


def test_the_example_documents_a_working_local_default(repo: Path):
    """`make up` from a clean clone copies this file and boots (`AC-FOUND-01.1`),
    so the non-secret local defaults must actually be usable."""
    example = env_example(repo)
    assert example["APP_ENV"] == "local"
    assert example["PRODUCT_NAME"], "PRODUCT_NAME supplies every user-visible string"
    # D7's default is Resend, but locally nothing may send real mail
    # (`AC-FOUND-16.5`).
    assert example["EMAIL_PROVIDER"] == "mailpit"
    # `MATCH-02b` is the one built-off feature in R1 (`README.md` §1, Call 1).
    assert example["FLAG_LLM_RATIONALE_ENABLED"] == "false"


def test_the_flag_set_matches_admin_03(repo: Path):
    """`12-admin.md` §3 names the R1 flag set; the example must carry all of it."""
    expected = {
        "llm_rationale_enabled",
        "job_enrichment_enabled",
        "ocr_enabled",
        "extension_apply_enabled",
        "digest_enabled",
        "push_enabled",
        "signup_enabled",
        "ingestion_enabled",
    }
    declared = {
        key.removeprefix("FLAG_").lower() for key in env_example(repo) if key.startswith("FLAG_")
    }
    assert declared == expected
