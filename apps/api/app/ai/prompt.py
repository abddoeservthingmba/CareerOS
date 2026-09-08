"""Prompt management — `AI-07`.

`05-ai-layer.md` §7: "A prompt is a versioned artifact with tests, so a change
to it is reviewable and its effect measurable — and so any output can be
reproduced from what is stored beside it."

Three decisions in this module are worth reading before the code, because each
one is the answer to a specific way prompt management usually rots.

**A prompt is a file, not a string in a function.** Prompts at
`ai/prompts/<feature>/v<N>.md` diff like prose, review like prose, and carry
their own front matter. The alternative - an f-string in the module that calls
the model - cannot be versioned, so `prompt_version` on a stored artifact would
name nothing retrievable, and "reproduce this output" would be unanswerable.

**A `{{slot}}` renders to a *reference*, never to content.** This is the part
most likely to be changed by someone who has not read §6. `{{resume_text}}`
becomes the literal `[resume_text]` - the header that `untrusted.render()`
writes above that region of the data block. The résumé itself never enters the
instruction text at all; it travels in `LLMRequest.untrusted` and is rendered
once, inside nonce-delimited fences, by `untrusted.py` alone. Interpolating the
content here would put attacker-controlled text in the same region as the
rules, which is the injection surface HR-11 exists to remove - and it would do
so while still passing every test that only checked the output looked right.

**Validation is at boot, and it is total.** §7: "A malformed prompt fails the
boot." Every declared slot must appear in the body and every `{{slot}}` in the
body must be declared, because both directions are real mistakes with silent
failure modes: an undeclared slot renders as a dangling `[name]` pointing at a
region that was never sent, and an unused declaration means the feature passes
content the model was never told about. Neither raises. Both quietly degrade
the answer.

**Schemas are resolved, not imported.** `output_schema` is a dotted path in a
data file, so `app.ai` has no static dependency on `app.modules` - which is
contract 4 (`ai-is-leaf`), and is why `load_all()` deliberately does *not*
resolve it. Resolution is a separate, explicit call made from `app.main`, which
is allowed to see feature modules. A worker that only embeds can therefore load
the prompt inventory without dragging in every feature package.
"""

from __future__ import annotations

import hashlib
import importlib
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from app.ai.base import Feature, Tier

#: `ai/prompts/<feature>/v<N>.md`, relative to this package.
PROMPT_ROOT = Path(__file__).parent / "prompts"

#: The front matter keys §7 names. Exactly these: an unknown key is refused for
#: the same reason `Settings` sets `extra="forbid"` - a typo in a key silently
#: means "no value", and the value it was meant to set is the one that mattered.
REQUIRED_KEYS = frozenset(
    {"version", "feature", "tier", "output_schema", "untrusted_slots", "changelog"}
)

#: `{{name}}`. Deliberately narrow: no expressions, no filters, no nesting. A
#: template language in a prompt is a way for logic to end up somewhere no test
#: looks.
SLOT = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")

#: A dotted path ending in a class name, so `output_schema` cannot name a
#: module, a function or a variable and have the mistake surface only in
#: production.
SCHEMA_PATH = re.compile(r"^[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+\.[A-Z][A-Za-z0-9_]*$")

FILENAME = re.compile(r"^v(\d+)\.md$")

FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.DOTALL)


class PromptInvalid(Exception):
    """A prompt file is malformed. Raised at boot, never swallowed.

    Not an `AIError`: this is a deployment being wrong about its own contents,
    not a provider misbehaving, and nothing should be tempted to catch it
    alongside a timeout and degrade.
    """


@dataclass(frozen=True, slots=True)
class Prompt:
    """One version of one feature's prompt."""

    feature: Feature
    version: int
    tier: Tier
    #: A dotted path. Not a type - see the module docstring.
    output_schema: str
    untrusted_slots: tuple[str, ...]
    changelog: tuple[str, ...]
    body: str
    path: Path

    @property
    def prompt_version(self) -> str:
        """§7: `prompt_version` is `"<feature>/v<N>"`, recorded on every artifact
        and every `ai_usage` row."""
        return f"{self.feature.value}/v{self.version}"

    @property
    def sha256(self) -> str:
        """The whole file, front matter included.

        The immutability check (`AC-AI-07.2`) compares this against a committed
        manifest. Hashing the body alone would let a change to `output_schema`
        or `tier` pass as untouched, and either of those changes what the model
        is asked to produce just as surely as the prose does.
        """
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def render(self) -> str:
        """The system text, with each `{{slot}}` replaced by `[slot]`.

        `[slot]` is the header `untrusted.render()` writes above that region of
        the data block, so the rendered prompt *points at* the untrusted content
        without containing any of it. Takes no arguments for that reason: there
        is nothing to pass, which is what makes a golden test deterministic and
        an injection through this path impossible.
        """
        return SLOT.sub(lambda m: f"[{m.group(1)}]", self.body).strip()

    def resolve_schema(self) -> type[BaseModel]:
        """Import the model `output_schema` names.

        Separate from loading on purpose (module docstring). Called from
        `app.main` at boot, so a bad path fails the boot rather than the first
        request that needed it.
        """
        return _resolve(self.output_schema)


def _resolve(path: str) -> type[BaseModel]:
    module_path, _, name = path.rpartition(".")
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise PromptInvalid(
            f"output_schema {path!r} does not import: {exc}. The path is "
            "`<module>.<ClassName>` and the module must be importable at boot."
        ) from exc
    found = getattr(module, name, None)
    if found is None:
        raise PromptInvalid(f"output_schema {path!r}: {module_path} has no {name!r}")
    if not (isinstance(found, type) and issubclass(found, BaseModel)):
        raise PromptInvalid(
            f"output_schema {path!r} is {type(found).__name__}, not a pydantic model. "
            "`complete_json` validates against it, so it has to be one."
        )
    return found


# -- loading ------------------------------------------------------------------


def parse(text: str, path: Path) -> Prompt:
    """Parse one prompt file. Every failure is a `PromptInvalid` naming the file.

    The error messages are long on purpose. This runs at boot, so whoever reads
    one is looking at a container that will not start, usually in a deploy log,
    usually without the spec open.
    """
    matched = FRONT_MATTER.match(text)
    if matched is None:
        raise PromptInvalid(
            f"{path}: no YAML front matter. A prompt file opens with `---`, the "
            f"keys {sorted(REQUIRED_KEYS)}, then `---`, then the body."
        )
    raw, body = matched.group(1), matched.group(2)

    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise PromptInvalid(f"{path}: front matter is not valid YAML: {exc}") from exc
    if not isinstance(loaded, dict):
        raise PromptInvalid(f"{path}: front matter is {type(loaded).__name__}, not a mapping")

    meta: dict[str, Any] = loaded
    keys = set(meta)
    if missing := sorted(REQUIRED_KEYS - keys):
        raise PromptInvalid(f"{path}: front matter is missing {missing}")
    if unknown := sorted(keys - REQUIRED_KEYS):
        raise PromptInvalid(
            f"{path}: unknown front matter key(s) {unknown}. A misspelled key is "
            "an unset value, which is why unknown keys are refused rather than ignored."
        )

    feature = _feature(meta["feature"], path)
    tier = _tier(meta["tier"], path)
    version = _version(meta["version"], path)
    slots = _slots(meta["untrusted_slots"], path)
    changelog = _changelog(meta["changelog"], path)
    schema = _schema_path(meta["output_schema"], path)
    body = body.strip()

    _check_filename(path, version)
    _check_directory(path, feature)
    _check_body(body, slots, path)

    return Prompt(
        feature=feature,
        version=version,
        tier=tier,
        output_schema=schema,
        untrusted_slots=slots,
        changelog=changelog,
        body=body,
        path=path,
    )


def load_file(path: Path) -> Prompt:
    return parse(path.read_text(encoding="utf-8"), path)


def prompt_files(root: Path | None = None) -> list[Path]:
    """Every `v<N>.md` under the prompt root, in a stable order."""
    base = root if root is not None else PROMPT_ROOT
    if not base.is_dir():
        return []
    return sorted(p for p in base.glob("*/v*.md") if p.is_file())


def load_all(root: Path | None = None) -> dict[Feature, dict[int, Prompt]]:
    """Load and validate every prompt. Raises on the first invalid one.

    Does **not** resolve `output_schema` - see the module docstring. Ordered by
    path, so the file named in a failure is the first one that is wrong rather
    than an arbitrary one.
    """
    loaded: dict[Feature, dict[int, Prompt]] = {}
    for path in prompt_files(root):
        prompt = load_file(path)
        versions = loaded.setdefault(prompt.feature, {})
        if prompt.version in versions:
            raise PromptInvalid(
                f"{path}: {prompt.prompt_version} is already defined by "
                f"{versions[prompt.version].path}"
            )
        versions[prompt.version] = prompt
    _check_version_runs(loaded)
    return loaded


def latest(feature: Feature, root: Path | None = None) -> Prompt:
    """The highest version for `feature`.

    §7 makes an old version immutable, not unusable: a stored artifact points at
    the version that produced it. New work uses the latest.
    """
    versions = load_all(root).get(feature)
    if not versions:
        raise PromptInvalid(
            f"no prompt for {feature.value}. Prompts live at "
            f"ai/prompts/{feature.value}/v1.md and arrive with the feature that uses them."
        )
    return versions[max(versions)]


def by_version(prompt_version: str, root: Path | None = None) -> Prompt:
    """Look a prompt up by the string stored on an artifact.

    This is what makes `prompt_version` on a stored artifact meaningful: the
    text that produced an output is retrievable from the string beside it.
    """
    feature_name, _, tail = prompt_version.partition("/")
    matched = re.fullmatch(r"v(\d+)", tail)
    if not matched:
        raise PromptInvalid(f"{prompt_version!r} is not `<feature>/v<N>`")
    try:
        feature = Feature(feature_name)
    except ValueError as exc:
        raise PromptInvalid(f"{prompt_version!r} names no feature") from exc
    versions = load_all(root).get(feature, {})
    version = int(matched.group(1))
    if version not in versions:
        raise PromptInvalid(
            f"{prompt_version} is recorded on an artifact but the file is gone. "
            "A used version is immutable and must not be deleted; that is what "
            "makes a stored output reproducible."
        )
    return versions[version]


@cache
def inventory() -> Mapping[Feature, Mapping[int, Prompt]]:
    """The validated inventory, loaded once.

    Cached because it is read on a request path and the files cannot change
    under a running process - the image is immutable. Tests that write prompts
    to a `tmp_path` pass `root=` and bypass this.
    """
    return load_all()


def validate_at_startup(
    root: Path | None = None, resolve: Callable[[str], type[BaseModel]] | None = None
) -> dict[Feature, dict[int, Prompt]]:
    """§7's "loaded and validated at startup".

    The one call that does everything, including resolving `output_schema` -
    which is why it is invoked from `app.main` rather than from anywhere in
    `app.ai`. `resolve` is injectable so the loader's own tests can exercise
    the failure paths without a feature module in the repository.
    """
    resolver = resolve if resolve is not None else _resolve
    loaded = load_all(root)
    for versions in loaded.values():
        for prompt in versions.values():
            resolver(prompt.output_schema)
    return loaded


# -- the individual checks ----------------------------------------------------


def _feature(value: object, path: Path) -> Feature:
    try:
        return Feature(str(value))
    except ValueError as exc:
        raise PromptInvalid(
            f"{path}: feature {value!r} is not one of {[f.value for f in Feature]}. "
            "Budgets, pricing and the dashboard all key on it, so it cannot be free text."
        ) from exc


def _tier(value: object, path: Path) -> Tier:
    try:
        return Tier(str(value))
    except ValueError as exc:
        raise PromptInvalid(
            f"{path}: tier {value!r} is not `fast` or `quality`. A prompt names a "
            "tier, never a model (`AC-AI-02.2`)."
        ) from exc


def _version(value: object, path: Path) -> int:
    # `isinstance(True, int)` is True, and `version: true` in YAML is a typo
    # that would otherwise become version 1.
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise PromptInvalid(f"{path}: version must be a positive integer, got {value!r}")
    return value


def _slots(value: object, path: Path) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise PromptInvalid(f"{path}: untrusted_slots must be a list of names, got {value!r}")
    names = tuple(str(v) for v in value)
    if len(set(names)) != len(names):
        raise PromptInvalid(f"{path}: untrusted_slots repeats a name: {names}")
    for name in names:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise PromptInvalid(
                f"{path}: untrusted_slot {name!r} is not a lowercase identifier. The "
                "name is a key in `LLMRequest.untrusted` and a header in the data block."
            )
    return names


def _changelog(value: object, path: Path) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        raise PromptInvalid(
            f"{path}: changelog must be a non-empty list of lines. A version with no "
            "changelog does not say why it exists, which is the whole reason "
            "an improvement creates v<N+1> instead of editing v<N>."
        )
    return tuple(str(v).strip() for v in value)


def _schema_path(value: object, path: Path) -> str:
    if not isinstance(value, str) or not SCHEMA_PATH.match(value):
        raise PromptInvalid(
            f"{path}: output_schema {value!r} is not a dotted path to a class, "
            "e.g. `app.modules.resumes.schemas.ExtractedResume`."
        )
    return value


def _check_filename(path: Path, version: int) -> None:
    matched = FILENAME.match(path.name)
    if matched is None:
        raise PromptInvalid(f"{path}: a prompt file is named `v<N>.md`")
    if int(matched.group(1)) != version:
        raise PromptInvalid(
            f"{path}: front matter says version {version} but the file is named "
            f"{path.name}. Two answers is no answer, and the filename is what a "
            "reviewer sees in a diff."
        )


def _check_directory(path: Path, feature: Feature) -> None:
    if path.parent.name != feature.value:
        raise PromptInvalid(
            f"{path}: front matter says feature {feature.value!r} but the file is in "
            f"{path.parent.name!r}/"
        )


def _check_body(body: str, slots: Iterable[str], path: Path) -> None:
    if not body:
        raise PromptInvalid(f"{path}: the body is empty")

    declared = set(slots)
    used = set(SLOT.findall(body))

    if undeclared := sorted(used - declared):
        raise PromptInvalid(
            f"{path}: the body references undeclared slot(s) {undeclared}. Nothing "
            "would fill them: the rendered prompt would point at a region of the "
            "data block that was never sent, and the model would answer anyway."
        )
    if unused := sorted(declared - used):
        raise PromptInvalid(
            f"{path}: untrusted_slots declares {unused} but the body never "
            "references them. The content would be sent without the prompt ever "
            "telling the model it was there."
        )
    if "<<<UNTRUSTED" in body:
        raise PromptInvalid(
            f"{path}: the body contains an untrusted delimiter. Only "
            "`ai/untrusted.py` writes those, and it uses a per-request nonce "
            "(`AC-AI-06.4`); a literal here is a fence content could close."
        )


def _check_version_runs(loaded: Mapping[Feature, Mapping[int, Prompt]]) -> None:
    """Versions run 1..N with no gaps.

    A gap means a version was deleted. §7 makes a used prompt immutable so a
    stored `prompt_version` stays resolvable; deleting v2 breaks every artifact
    that names it, and it breaks silently - the artifact still reads fine.
    """
    for feature, versions in loaded.items():
        expected = list(range(1, max(versions) + 1))
        if sorted(versions) != expected:
            raise PromptInvalid(
                f"{feature.value}: versions {sorted(versions)} have a gap; expected "
                f"{expected}. A deleted version orphans every artifact that "
                "recorded it."
            )


__all__ = [
    "PROMPT_ROOT",
    "REQUIRED_KEYS",
    "Prompt",
    "PromptInvalid",
    "by_version",
    "inventory",
    "latest",
    "load_all",
    "load_file",
    "parse",
    "prompt_files",
    "validate_at_startup",
]
