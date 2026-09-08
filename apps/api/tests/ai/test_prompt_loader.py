"""T-AI-07.1 - the prompt loader, and every way a prompt file can be wrong.

`AC-AI-07.1`: "Every prompt file's front matter validates, every
`output_schema` path imports, every declared slot appears in the body and every
`{{slot}}` in the body is declared."

Most of this suite runs against files written into a `tmp_path` rather than
against `app/ai/prompts/`. That is not a shortcut around a thin real inventory
- it is the only way to assert the *failure* paths at all. A test that could
only read committed prompts could never check what happens to a malformed one,
because a malformed one cannot be committed: the loader runs at boot and the
suite would not start. So the loader is exercised on synthetic files, and the
committed inventory is checked separately, at the bottom, by iterating whatever
is actually there.

**The inventory is empty today**, because a prompt cannot exist before the
schema its front matter names. `output_schema` points at a feature module's
Pydantic model, and those arrive in P1-P6 with `RES-03`, `JOB-05`, `MATCH-07`
and the pack requirements. Writing a prompt now would mean either inventing
those schemas - which `CLAUDE.md` forbids - or naming a path that does not
import, which is precisely what `AC-AI-07.1` fails on.

So the checks over the real directory are written to be **live rather than
vacuous**: each one iterates the inventory and asserts a property of every
member. They pass over zero files and start doing work the moment the first
prompt lands, which is the commit where getting it wrong is most likely.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.ai import prompt as prompt_mod
from app.ai.base import Feature, Tier
from app.ai.prompt import PROMPT_ROOT, Prompt, PromptInvalid

#: A model that exists today, so `output_schema` resolution can be tested
#: before any feature module does. Nothing about the loader cares which model
#: it is - only that the path imports and names a `BaseModel`.
REAL_SCHEMA = "app.core.sse.StreamEvent"

GOOD = """\
---
version: 1
feature: resume_extract
tier: fast
output_schema: app.core.sse.StreamEvent
untrusted_slots: [resume_text]
changelog:
  - "v1 - first version."
---

Extract the structured fields from the resume in {{resume_text}}.
Return only fields you can point at in the text.
"""


def write(
    tmp_path: Path,
    text: str = GOOD,
    *,
    feature: str = "resume_extract",
    filename: str = "v1.md",
) -> Path:
    directory = tmp_path / feature
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def edited(**changes: str) -> str:
    """`GOOD` with front matter lines replaced, so each test states only its
    own defect."""
    lines = GOOD.split("\n")
    for key, value in changes.items():
        for index, line in enumerate(lines):
            if line.startswith(f"{key}:"):
                lines[index] = f"{key}: {value}"
                break
        else:  # pragma: no cover - a typo in a test's own key
            raise AssertionError(f"{key} is not a front matter line in GOOD")
    return "\n".join(lines)


# -- the happy path -----------------------------------------------------------


def test_a_valid_prompt_loads(tmp_path: Path):
    """AC-AI-07.1, all four clauses satisfied at once."""
    loaded = prompt_mod.load_file(write(tmp_path))

    assert loaded.feature is Feature.RESUME_EXTRACT
    assert loaded.version == 1
    assert loaded.tier is Tier.FAST
    assert loaded.output_schema == REAL_SCHEMA
    assert loaded.untrusted_slots == ("resume_text",)
    assert loaded.changelog == ("v1 - first version.",)
    assert "Extract the structured fields" in loaded.body


def test_the_prompt_version_string_is_what_artifacts_record(tmp_path: Path):
    """§7: `prompt_version` is `"<feature>/v<N>"`, "recorded on every artifact
    and every `ai_usage` row"."""
    assert prompt_mod.load_file(write(tmp_path)).prompt_version == "resume_extract/v1"


def test_the_hash_covers_the_front_matter_too(tmp_path: Path):
    """The immutability manifest compares this.

    Hashing only the body would let `tier: fast` become `tier: quality`, or
    `output_schema` change to a different model, and still read as untouched -
    and either of those changes what the model is asked to produce as surely as
    the prose does.
    """
    path = write(tmp_path)
    before = prompt_mod.load_file(path).sha256

    path.write_text(
        textwrap.dedent(edited(tier="quality")).replace("tier: fast", "tier: quality"),
        encoding="utf-8",
    )
    after = prompt_mod.load_file(path).sha256

    assert before != after


# -- rendering: a slot is a reference, never content --------------------------


def test_a_slot_renders_to_the_data_block_header(tmp_path: Path):
    """The decision most likely to be undone by someone who has not read §6.

    `{{resume_text}}` becomes `[resume_text]` - the header `untrusted.render()`
    writes above that region. The prompt *points at* the content; it never
    contains it.
    """
    rendered = prompt_mod.load_file(write(tmp_path)).render()

    assert "[resume_text]" in rendered
    assert "{{" not in rendered


def test_the_rendered_header_matches_what_untrusted_actually_writes():
    """The two halves have to agree, or the prompt points at a region label
    that does not exist in the block the model receives.

    Asserted against the real renderer rather than against a copy of its
    format string, because a copy is what drifts.
    """
    from app.ai.untrusted import render

    block = render({"resume_text": "some text"}, nonce="fixed").text

    assert "[resume_text]" in block


def test_render_takes_no_arguments():
    """Structural, and load-bearing.

    There is nothing to pass, which is what makes the injection surface absent
    rather than merely unused. A `render(**slots)` signature is one refactor
    away from putting a resume in the instruction section, and it would pass
    every output-shaped test.
    """
    import inspect

    assert list(inspect.signature(Prompt.render).parameters) == ["self"]


def test_rendering_is_deterministic(tmp_path: Path):
    """`AC-AI-07.3`'s golden tests are only meaningful if this holds."""
    loaded = prompt_mod.load_file(write(tmp_path))

    assert loaded.render() == loaded.render()


# -- front matter -------------------------------------------------------------


def test_no_front_matter_is_refused(tmp_path: Path):
    path = write(tmp_path, "Extract everything from {{resume_text}}.\n")

    with pytest.raises(PromptInvalid, match="no YAML front matter"):
        prompt_mod.load_file(path)


def test_unparseable_front_matter_is_refused(tmp_path: Path):
    path = write(tmp_path, "---\nversion: [1\n---\n\nbody\n")

    with pytest.raises(PromptInvalid, match="not valid YAML"):
        prompt_mod.load_file(path)


@pytest.mark.parametrize("key", sorted(prompt_mod.REQUIRED_KEYS))
def test_a_missing_required_key_is_refused(tmp_path: Path, key: str):
    """All six, each one individually. A parametrised loop rather than one
    example, because the six are checked by six different code paths and any of
    them could be the one that forgets."""
    # Drop the key's line and any indented continuation under it, so removing
    # `changelog` removes its list items too rather than orphaning them.
    lines: list[str] = []
    dropping = False
    for line in GOOD.split("\n"):
        if line.startswith(f"{key}:"):
            dropping = True
            continue
        if dropping and line.startswith(("  ", "\t")):
            continue
        dropping = False
        lines.append(line)
    text = "\n".join(lines)

    with pytest.raises(PromptInvalid, match="missing"):
        prompt_mod.load_file(write(tmp_path, text))


def test_an_unknown_front_matter_key_is_refused(tmp_path: Path):
    """`Settings` sets `extra="forbid"` for the same reason: a misspelled key is
    an unset value, and the value it was meant to set is the one that
    mattered."""
    text = GOOD.replace("tier: fast", "tier: fast\nteir: quality")

    with pytest.raises(PromptInvalid, match="unknown front matter key"):
        prompt_mod.load_file(write(tmp_path, text))


def test_a_feature_outside_the_enum_is_refused(tmp_path: Path):
    """Ten members, and budgets, pricing and the dashboard all key on it."""
    with pytest.raises(PromptInvalid, match="is not one of"):
        prompt_mod.load_file(write(tmp_path, edited(feature="resume_extraction")))


def test_a_tier_outside_the_two_is_refused(tmp_path: Path):
    with pytest.raises(PromptInvalid, match="`fast` or `quality`"):
        prompt_mod.load_file(write(tmp_path, edited(tier="cheap")))


@pytest.mark.parametrize("value", ["0", "-1", "'1'", "1.5", "true"])
def test_a_non_positive_integer_version_is_refused(tmp_path: Path, value: str):
    """`true` is in the list because YAML parses it as a bool and
    `isinstance(True, int)` is True in Python - so `version: true` would
    otherwise silently become version 1."""
    with pytest.raises(PromptInvalid, match="positive integer"):
        prompt_mod.load_file(write(tmp_path, edited(version=value)))


def test_an_empty_changelog_is_refused(tmp_path: Path):
    """A version with no changelog does not say why it exists, which is the
    whole reason an improvement creates v<N+1> instead of editing v<N>."""
    text = GOOD.replace('changelog:\n  - "v1 - first version."', "changelog: []")

    with pytest.raises(PromptInvalid, match="changelog"):
        prompt_mod.load_file(write(tmp_path, text))


def test_a_single_string_changelog_is_accepted(tmp_path: Path):
    """The shape someone writes on the first version. Accepting it costs
    nothing and refusing it would be pedantry, not a control."""
    text = GOOD.replace('changelog:\n  - "v1 - first version."', 'changelog: "v1 - first."')

    assert prompt_mod.load_file(write(tmp_path, text)).changelog == ("v1 - first.",)


@pytest.mark.parametrize(
    "value",
    [
        "app.modules.resumes.schemas",  # a module, not a class
        "ExtractedResume",  # no module
        "app.modules.resumes.schemas.extracted_resume",  # not a class name
        "42",
    ],
)
def test_an_output_schema_that_is_not_a_dotted_class_path_is_refused(tmp_path: Path, value: str):
    """Refused on *form* at load time, and on *importability* separately. A
    path that names a module or a function fails only where it is used, which
    in this case is the first production request for that feature."""
    with pytest.raises(PromptInvalid, match="dotted path to a class"):
        prompt_mod.load_file(write(tmp_path, edited(output_schema=value)))


# -- slots, both directions ---------------------------------------------------


def test_an_undeclared_slot_in_the_body_is_refused(tmp_path: Path):
    """Nothing would fill it. The rendered prompt would point at a region of
    the data block that was never sent, and the model would answer anyway -
    which is the failure mode: an answer, just a worse one."""
    text = GOOD.replace("{{resume_text}}", "{{resume_text}} and {{cover_letter}}")

    with pytest.raises(PromptInvalid, match="undeclared slot"):
        prompt_mod.load_file(write(tmp_path, text))


def test_a_declared_slot_missing_from_the_body_is_refused(tmp_path: Path):
    """The other direction, and the more dangerous one: the content is sent
    without the prompt ever telling the model it is there."""
    text = GOOD.replace("untrusted_slots: [resume_text]", "untrusted_slots: [resume_text, jd]")

    with pytest.raises(PromptInvalid, match="never reference"):
        prompt_mod.load_file(write(tmp_path, text))


def test_a_repeated_slot_declaration_is_refused(tmp_path: Path):
    text = GOOD.replace(
        "untrusted_slots: [resume_text]", "untrusted_slots: [resume_text, resume_text]"
    )

    with pytest.raises(PromptInvalid, match="repeats a name"):
        prompt_mod.load_file(write(tmp_path, text))


def test_a_slot_name_that_is_not_an_identifier_is_refused(tmp_path: Path):
    """The name is a key in `LLMRequest.untrusted` and a header in the data
    block, so it has to be usable as both."""
    text = GOOD.replace(
        "untrusted_slots: [resume_text]", 'untrusted_slots: ["Resume Text"]'
    ).replace("{{resume_text}}", "")

    with pytest.raises(PromptInvalid):
        prompt_mod.load_file(write(tmp_path, text))


def test_no_slots_at_all_is_valid(tmp_path: Path):
    """A prompt that takes no untrusted content - a template for a follow-up
    email, say - is a legitimate shape and must not need a dummy slot."""
    text = GOOD.replace("untrusted_slots: [resume_text]", "untrusted_slots: []").replace(
        "in {{resume_text}}", "below"
    )

    assert prompt_mod.load_file(write(tmp_path, text)).untrusted_slots == ()


def test_an_untrusted_delimiter_in_the_body_is_refused(tmp_path: Path):
    """Only `untrusted.py` writes those, with a per-request nonce
    (`AC-AI-06.4`). A literal here is a fence content could close - which turns
    the rest of the data block into instructions."""
    text = GOOD.replace("Extract the", "<<<UNTRUSTED-x>>> Extract the")

    with pytest.raises(PromptInvalid, match="untrusted delimiter"):
        prompt_mod.load_file(write(tmp_path, text))


def test_an_empty_body_is_refused(tmp_path: Path):
    text = GOOD.split("---")[0] + "---" + GOOD.split("---")[1] + "---\n\n\n"

    with pytest.raises(PromptInvalid, match="body is empty"):
        prompt_mod.load_file(write(tmp_path, text.replace("[resume_text]", "[]")))


# -- the file's name and place have to agree with its contents ----------------


def test_a_filename_disagreeing_with_the_version_is_refused(tmp_path: Path):
    """Two answers is no answer, and the filename is what a reviewer sees in a
    diff."""
    with pytest.raises(PromptInvalid, match="but the file is named"):
        prompt_mod.load_file(write(tmp_path, filename="v2.md"))


def test_a_directory_disagreeing_with_the_feature_is_refused(tmp_path: Path):
    with pytest.raises(PromptInvalid, match="but the file is in"):
        prompt_mod.load_file(write(tmp_path, feature="job_enrich"))


# -- the inventory ------------------------------------------------------------


def test_load_all_over_several_features(tmp_path: Path):
    write(tmp_path)
    write(
        tmp_path,
        edited(feature="job_enrich").replace("resume_text", "job_description"),
        feature="job_enrich",
    )

    loaded = prompt_mod.load_all(tmp_path)

    assert set(loaded) == {Feature.RESUME_EXTRACT, Feature.JOB_ENRICH}
    assert list(loaded[Feature.RESUME_EXTRACT]) == [1]


def test_latest_returns_the_highest_version(tmp_path: Path):
    """§7 makes an old version immutable, not unusable. New work uses the
    latest; a stored artifact points at the version that produced it."""
    write(tmp_path)
    write(
        tmp_path,
        edited(version="2").replace('- "v1 - first version."', '- "v2 - tightened."'),
        filename="v2.md",
    )

    assert prompt_mod.latest(Feature.RESUME_EXTRACT, tmp_path).version == 2


def test_latest_says_where_a_missing_prompt_goes(tmp_path: Path):
    with pytest.raises(PromptInvalid, match="ai/prompts/job_enrich/v1.md"):
        prompt_mod.latest(Feature.JOB_ENRICH, tmp_path)


def test_a_version_gap_is_refused(tmp_path: Path):
    """A gap means a version was deleted, which orphans every artifact that
    recorded it - silently, because the artifact still reads fine."""
    write(tmp_path, edited(version="1"))
    write(
        tmp_path,
        edited(version="3").replace('- "v1 - first version."', '- "v3."'),
        filename="v3.md",
    )

    with pytest.raises(PromptInvalid, match="have a gap"):
        prompt_mod.load_all(tmp_path)


def test_by_version_finds_what_an_artifact_recorded(tmp_path: Path):
    """This is what makes `prompt_version` on a stored artifact meaningful: the
    text that produced an output is retrievable from the string beside it."""
    write(tmp_path)

    found = prompt_mod.by_version("resume_extract/v1", tmp_path)

    assert found.body.startswith("Extract the structured fields")


def test_by_version_on_a_missing_file_says_why_that_matters(tmp_path: Path):
    with pytest.raises(PromptInvalid, match="reproducible"):
        prompt_mod.by_version("resume_extract/v1", tmp_path)


@pytest.mark.parametrize("value", ["resume_extract", "resume_extract/1", "resume_extract/vx"])
def test_by_version_refuses_a_malformed_string(tmp_path: Path, value: str):
    with pytest.raises(PromptInvalid, match="is not `<feature>/v<N>`"):
        prompt_mod.by_version(value, tmp_path)


def test_by_version_refuses_an_unknown_feature(tmp_path: Path):
    with pytest.raises(PromptInvalid, match="names no feature"):
        prompt_mod.by_version("resume_extraction/v1", tmp_path)


def test_the_readme_is_not_loaded_as_a_prompt():
    """`prompts/README.md` documents the layout. Globbing `*.md` instead of
    `v*.md` would try to parse it and fail the boot on a documentation file."""
    assert (PROMPT_ROOT / "README.md").is_file()
    assert (PROMPT_ROOT / "README.md") not in prompt_mod.prompt_files()


# -- schema resolution, which is separate on purpose --------------------------


def test_load_all_does_not_import_the_schema(tmp_path: Path):
    """Contract 4, `ai-is-leaf`: `app.ai` must not depend on `app.modules`.

    `output_schema` is a dotted path in a data file precisely so there is no
    static dependency, and resolution is a separate call made from `app.main`,
    which is allowed to see feature modules. Asserted by loading a prompt whose
    schema path cannot possibly import: if `load_all` resolved, this would
    raise.
    """
    write(tmp_path, edited(output_schema="app.modules.nothing.at.all.Missing"))

    loaded = prompt_mod.load_all(tmp_path)

    assert loaded[Feature.RESUME_EXTRACT][1].output_schema.endswith(".Missing")


def test_resolve_schema_returns_the_model(tmp_path: Path):
    resolved = prompt_mod.load_file(write(tmp_path)).resolve_schema()

    assert isinstance(resolved, type)
    assert issubclass(resolved, BaseModel)


def test_a_schema_path_that_does_not_import_is_refused(tmp_path: Path):
    """`AC-AI-07.1`'s "every `output_schema` path imports"."""
    loaded = prompt_mod.load_file(write(tmp_path, edited(output_schema="app.nope.Missing")))

    with pytest.raises(PromptInvalid, match="does not import"):
        loaded.resolve_schema()


def test_a_schema_path_naming_something_absent_is_refused(tmp_path: Path):
    loaded = prompt_mod.load_file(write(tmp_path, edited(output_schema="app.core.sse.NotThere")))

    with pytest.raises(PromptInvalid, match="has no"):
        loaded.resolve_schema()


def test_a_schema_path_naming_a_non_model_is_refused(tmp_path: Path):
    """`complete_json` validates against it, so it has to be a pydantic model.
    A path to a dataclass or a plain class would fail at the first call."""
    loaded = prompt_mod.load_file(
        write(tmp_path, edited(output_schema="app.ai.prompt.PromptInvalid"))
    )

    with pytest.raises(PromptInvalid, match="not a pydantic model"):
        loaded.resolve_schema()


def test_validate_at_startup_resolves_every_schema(tmp_path: Path):
    """§7: "Prompts are loaded and validated at startup ... A malformed prompt
    fails the boot"."""
    write(tmp_path, edited(output_schema="app.nope.Missing"))

    with pytest.raises(PromptInvalid, match="does not import"):
        prompt_mod.validate_at_startup(tmp_path)


def test_validate_at_startup_accepts_an_injected_resolver(tmp_path: Path):
    """Injectable so the loader's own tests can exercise the failure paths
    without a feature module in the repository - which is the state the
    repository is in until P1."""
    write(tmp_path, edited(output_schema="app.modules.resumes.schemas.ExtractedResume"))
    seen: list[str] = []

    def resolver(path: str) -> type[BaseModel]:
        seen.append(path)
        return BaseModel

    prompt_mod.validate_at_startup(tmp_path, resolve=resolver)

    assert seen == ["app.modules.resumes.schemas.ExtractedResume"]


# -- the committed inventory --------------------------------------------------
# Live, not vacuous: each of these iterates whatever is in `app/ai/prompts/` and
# asserts a property of every member. They pass over zero files and start doing
# work in the commit that adds the first prompt, which is where getting it
# wrong is most likely.


def test_every_committed_prompt_is_valid():
    """The real inventory, through the real loader. This is the assertion that
    turns "a malformed prompt fails the boot" into something a pull request
    finds out about before a deploy does."""
    prompt_mod.load_all()


def test_every_committed_prompt_resolves_its_schema():
    """`AC-AI-07.1`'s import clause over the committed files.

    Empty today because no feature module exists to own a schema. It becomes
    the check that a prompt and its output model land together.
    """
    for versions in prompt_mod.load_all().values():
        for committed in versions.values():
            resolved = committed.resolve_schema()
            assert issubclass(resolved, BaseModel), committed.path


def test_every_committed_prompt_declares_a_tier_not_a_model():
    """`AC-AI-02.2` from the prompt side: a prompt names `fast` or `quality`,
    never a model id. `test_no_model_literals.py` covers `.py` files; a prompt
    is a file too, and it is the one a non-engineer is most likely to edit."""
    for versions in prompt_mod.load_all().values():
        for committed in versions.values():
            assert isinstance(committed.tier, Tier)
            for banned in ("gemini-", "gpt-", "claude-", "llama", "qwen"):
                assert banned not in committed.body.casefold(), (
                    f"{committed.path} names a model in its body; a prompt declares a tier"
                )


def test_no_committed_prompt_interpolates_content():
    """Every `{{slot}}` must be a declared untrusted slot, which the loader
    already enforces - asserted again over the real files because the property
    it protects (HR-11) is the one worth stating twice."""
    for versions in prompt_mod.load_all().values():
        for committed in versions.values():
            rendered = committed.render()
            assert "{{" not in rendered and "}}" not in rendered
            for slot in committed.untrusted_slots:
                assert f"[{slot}]" in rendered
