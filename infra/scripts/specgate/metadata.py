"""`SPEC-METADATA.json` - the whole specification as data.

Regenerates the committed artifact from `docs/spec/`, adding the two fields
v2.1 requires but the shipped `docs/spec/spec_metadata.py` does not emit: a
`bundle` per requirement (`AC-DEP-06.4`) and a `status` per requirement
(`FOUND-15`). Section statuses are corrected by the parser's heading-aware
split - see the note in `parser.py`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import repo_root
from .bundle import bundle_for
from .manifest import Manifest, manifest
from .parser import Spec, parse_spec


def _field(text: str, name: str) -> str | None:
    m = re.search(rf"\*\*{re.escape(name)}:?\*\*\s*(.+)", text)
    return m.group(1).strip() if m else None


def build(spec: Spec | None = None, m: Manifest | None = None) -> dict[str, Any]:
    spec = spec or parse_spec()
    m = m or manifest()

    dependencies: dict[str, dict[str, Any]] = {}
    for entry in sorted(m, key=lambda e: (e.phase_index, e.id)):
        row: dict[str, Any] = {
            "track": entry.track,
            "phase": entry.phase,
            "module": entry.module,
            "requires": list(entry.requires),
        }
        if entry.enabled_in:
            row["enabled_in"] = entry.enabled_in
        for key in (
            "consumes_events",
            "publishes_events",
            "reads_collections",
            "writes_collections",
        ):
            value = getattr(entry, key)
            if value:
                row[key] = list(value)
        bundle = bundle_for(entry.id, m, spec)
        row["bundle"] = [f"docs/spec/{name}" for name in bundle.files]
        dependencies[entry.id] = row

    files: list[dict[str, Any]] = []
    for name, sf in spec.files.items():
        files.append(
            {
                "file": name,
                "title": next(
                    (line[2:].strip() for line in sf.lines if line.startswith("# ")), name
                ),
                "track": _field(sf.text, "Track"),
                "module": _field(sf.text, "Module"),
                "requirements": _field(sf.text, "Requirements"),
                "depends": _field(sf.text, "Depends on"),
                "lines": len(sf.lines),
                "words": len(sf.text.split()),
                "ac": len(sf.criteria),
                "tests": len(sf.tests),
                "sections": [
                    {
                        "n": s.number,
                        "title": s.title,
                        "heading": s.heading,
                        "level": s.level,
                        "requirements": list(s.requirements),
                        "track": s.track,
                        "status": s.status,
                    }
                    for s in sf.sections
                ],
            }
        )

    return {
        "spec": "JobPilot Agent Build Specification",
        "spec_version": "2.1",
        "generated_from": "docs/spec/*.md",
        "note": "Regenerate with `make spec-metadata` (infra/scripts/specgate).",
        "section_contract": [
            "Objective",
            "Constraints",
            "Inputs",
            "Outputs",
            "Acceptance criteria",
            "Tests",
        ],
        "implementation_states": ["built", "built-off", "stub-501", "absent"],
        "dependencies": dependencies,
        "totals": {
            "files": len(files),
            "sections": sum(len(f["sections"]) for f in files),
            "requirements": len(dependencies),
            "acceptance_criteria": len(spec.criteria),
            "tests_named": len(spec.tests),
        },
        "files": files,
    }


def render(spec: Spec | None = None, m: Manifest | None = None) -> str:
    return json.dumps(build(spec, m), indent=2) + "\n"


def target_path() -> Path:
    return repo_root() / "docs" / "spec" / "SPEC-METADATA.json"
