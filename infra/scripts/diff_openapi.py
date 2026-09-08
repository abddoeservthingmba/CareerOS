#!/usr/bin/env python
"""Classify an API change - `FOUND-13`.

`01-foundations.md` §13: "A PR whose API surface changes gets an automatic diff
comment classifying each change as additive or breaking. A breaking change on
`v1` fails CI unless the PR body contains `BREAKING-API-APPROVED:` with a
reason."

The rule this enforces is the one people agree with and then break by accident:
**additive changes are free, breaking ones need a `/api/v2`**. Nobody sets out
to remove a field. What happens is that a response model is tidied, a name is
improved, a `str` becomes an `int` because it was always an id - and three
weeks later a mobile build in the field starts crashing, because a shipped app
cannot be asked to redeploy.

So the classification is deliberately asymmetric, and errs toward "breaking":

* **Additive** - a new path, a new operation, a new *optional* request field, a
  new response field, a new enum value in a *request* (the server now accepts
  more), a widened response type nobody was narrowing on.
* **Breaking** - a removed path, operation, or field; a new *required* request
  field; an optional request field becoming required; a response field becoming
  optional (a client that read it unconditionally now crashes); a changed type;
  a removed enum value from a response; a changed `operation_id` (which renames
  a generated client method, so every call site fails to compile).

Anything this cannot classify is reported as breaking with a reason. A diff tool
that guessed "probably additive" would be wrong exactly on the changes nobody
thought about, which are the ones that reach production.

    py infra/scripts/diff_openapi.py before.json after.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

#: The token §13 requires in a PR body to land a breaking change on `v1`.
APPROVAL_TOKEN = "BREAKING-API-APPROVED:"


@dataclass(frozen=True)
class Change:
    """One difference, and what it costs a client."""

    kind: str
    where: str
    detail: str
    breaking: bool

    def __str__(self) -> str:
        mark = "BREAKING" if self.breaking else "additive"
        return f"[{mark}] {self.kind} {self.where} - {self.detail}"


def _operations(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """`"GET /api/v1/jobs"` to its operation object."""
    found: dict[str, dict[str, Any]] = {}
    for path, methods in (schema.get("paths") or {}).items():
        for method, operation in (methods or {}).items():
            if method.lower() in ("get", "post", "put", "patch", "delete", "head"):
                found[f"{method.upper()} {path}"] = operation
    return found


def _schemas(schema: dict[str, Any]) -> dict[str, Any]:
    return (schema.get("components") or {}).get("schemas") or {}


def _properties(model: dict[str, Any]) -> dict[str, Any]:
    return model.get("properties") or {}


def _required(model: dict[str, Any]) -> set[str]:
    return set(model.get("required") or [])


def _type_of(field: dict[str, Any]) -> str:
    """A field's type, flattened enough to compare.

    `anyOf` is how pydantic writes `str | None`, and comparing the raw
    structures would report a change every time a field order shifted.
    """
    if "$ref" in field:
        return str(field["$ref"])
    if "anyOf" in field:
        return "|".join(sorted(_type_of(part) for part in field["anyOf"]))
    kind = str(field.get("type", "unknown"))
    if kind == "array":
        return f"array[{_type_of(field.get('items') or {})}]"
    return kind


def compare(before: dict[str, Any], after: dict[str, Any]) -> list[Change]:
    """Every difference between two documents, classified."""
    changes: list[Change] = []
    changes.extend(_compare_operations(before, after))
    changes.extend(_compare_schemas(before, after))
    return changes


def _compare_operations(before: dict[str, Any], after: dict[str, Any]) -> list[Change]:
    old, new = _operations(before), _operations(after)
    changes: list[Change] = []

    for route in sorted(set(old) - set(new)):
        changes.append(
            Change(
                "route",
                route,
                "removed; every client calling it now gets a 404",
                breaking=True,
            )
        )
    for route in sorted(set(new) - set(old)):
        changes.append(Change("route", route, "added", breaking=False))

    for route in sorted(set(old) & set(new)):
        old_id = old[route].get("operationId")
        new_id = new[route].get("operationId")
        if old_id != new_id:
            changes.append(
                Change(
                    "operation_id",
                    route,
                    f"{old_id!r} -> {new_id!r}; this renames the generated client "
                    "method, so every call site stops compiling",
                    breaking=True,
                )
            )
        old_codes = set(old[route].get("responses") or {})
        new_codes = set(new[route].get("responses") or {})
        for code in sorted(old_codes - new_codes):
            changes.append(
                Change(
                    "response",
                    f"{route} {code}",
                    "documented response removed",
                    breaking=True,
                )
            )
        for code in sorted(new_codes - old_codes):
            changes.append(
                Change(
                    "response",
                    f"{route} {code}",
                    "documented response added",
                    breaking=False,
                )
            )

    return changes


def _compare_schemas(before: dict[str, Any], after: dict[str, Any]) -> list[Change]:
    old, new = _schemas(before), _schemas(after)
    changes: list[Change] = []

    for name in sorted(set(old) - set(new)):
        changes.append(Change("model", name, "removed", breaking=True))
    for name in sorted(set(new) - set(old)):
        changes.append(Change("model", name, "added", breaking=False))

    for name in sorted(set(old) & set(new)):
        changes.extend(_compare_model(name, old[name], new[name]))
    return changes


def _compare_model(name: str, old: dict[str, Any], new: dict[str, Any]) -> list[Change]:
    changes: list[Change] = []
    old_fields, new_fields = _properties(old), _properties(new)
    old_required, new_required = _required(old), _required(new)

    for field in sorted(set(old_fields) - set(new_fields)):
        changes.append(
            Change(
                "field",
                f"{name}.{field}",
                "removed; a client reading it gets `undefined`",
                breaking=True,
            )
        )

    for field in sorted(set(new_fields) - set(old_fields)):
        if field in new_required:
            changes.append(
                Change(
                    "field",
                    f"{name}.{field}",
                    "added as required; every existing client's requests are now "
                    "invalid",
                    breaking=True,
                )
            )
        else:
            changes.append(
                Change("field", f"{name}.{field}", "added as optional", breaking=False)
            )

    for field in sorted(set(old_fields) & set(new_fields)):
        old_type = _type_of(old_fields[field])
        new_type = _type_of(new_fields[field])
        if old_type != new_type:
            changes.append(
                Change(
                    "field",
                    f"{name}.{field}",
                    f"type {old_type} -> {new_type}",
                    breaking=True,
                )
            )
        if field not in old_required and field in new_required:
            changes.append(
                Change(
                    "field",
                    f"{name}.{field}",
                    "became required; requests that omitted it are now rejected",
                    breaking=True,
                )
            )
        if field in old_required and field not in new_required:
            changes.append(
                Change(
                    "field",
                    f"{name}.{field}",
                    "became optional; a client that read it unconditionally now "
                    "reads a missing value",
                    breaking=True,
                )
            )

    old_values = set(old.get("enum") or [])
    new_values = set(new.get("enum") or [])
    for value in sorted(old_values - new_values):
        changes.append(
            Change("enum", f"{name}.{value}", "value removed", breaking=True)
        )
    for value in sorted(new_values - old_values):
        # Additive in a request, breaking in a response, and the document does
        # not say which this model is used for. Reported as additive with the
        # ambiguity stated rather than silently guessed either way.
        changes.append(
            Change(
                "enum",
                f"{name}.{value}",
                "value added (breaking if this enum appears in a response a "
                "client switches on exhaustively)",
                breaking=False,
            )
        )

    return changes


def render(changes: list[Change]) -> str:
    """The PR comment §13 asks for."""
    if not changes:
        return "No API surface change."

    breaking = [change for change in changes if change.breaking]
    additive = [change for change in changes if not change.breaking]

    lines = ["## API surface change", ""]
    if breaking:
        lines.append(f"### {len(breaking)} breaking")
        lines.append("")
        lines.append(
            f"A breaking change on `v1` needs `{APPROVAL_TOKEN} <reason>` in the PR "
            "body, or a new `/api/v2`. §13: a breaking change is never made in place."
        )
        lines.append("")
        lines.extend(f"- {change}" for change in breaking)
        lines.append("")
    if additive:
        lines.append(f"### {len(additive)} additive")
        lines.append("")
        lines.extend(f"- {change}" for change in additive)
        lines.append("")
    return "\n".join(lines)


def approved(pr_body: str) -> bool:
    """Whether the PR body carries §13's token *with a reason*.

    A bare token is not approval. The token exists to make someone write down
    why a shipped mobile app is allowed to break, and an empty one is the
    ritual without the thinking.
    """
    for line in pr_body.split("\n"):
        if APPROVAL_TOKEN in line:
            reason = line.split(APPROVAL_TOKEN, 1)[1].strip()
            if len(reason) >= 10:
                return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path, help="the previous openapi.json")
    parser.add_argument("after", type=Path, help="the current openapi.json")
    parser.add_argument(
        "--pr-body", default="", help="the PR body, searched for the approval token"
    )
    parser.add_argument("--comment", type=Path, help="write the PR comment here")
    args = parser.parse_args(argv)

    before = (
        json.loads(args.before.read_text(encoding="utf-8"))
        if args.before.is_file()
        else {}
    )
    after = json.loads(args.after.read_text(encoding="utf-8"))

    changes = compare(before, after)
    comment = render(changes)
    if args.comment:
        args.comment.write_text(comment + "\n", encoding="utf-8", newline="")
    print(comment)

    breaking = [change for change in changes if change.breaking]
    if not breaking:
        return 0
    if approved(args.pr_body):
        print(f"\n{len(breaking)} breaking change(s), approved in the PR body.")
        return 0
    print(
        f"\n{len(breaking)} breaking change(s) on v1 and no {APPROVAL_TOKEN} in the "
        "PR body. Add a new /api/v2, or state the reason.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
