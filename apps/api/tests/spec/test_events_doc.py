"""T-FOUND-09.5 - `docs/events.md` is generated and matches §9's table.

`AC-FOUND-09.5`: "`docs/events.md` is generated from the registry and matches
the table above."

The table in `01-foundations.md` §9 is the design; `R1_EVENTS` is the code. The
document is generated from the code and this compares it back to the
specification, so the three cannot drift apart quietly.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.events import R1_EVENTS, render_events_doc

TARGET = "docs/events.md"


def test_the_document_is_current(repo: Path):
    """AC-FOUND-09.5."""
    committed = repo / TARGET
    assert committed.is_file(), f"run `make events-doc` to publish {TARGET}"
    assert committed.read_text(encoding="utf-8") == render_events_doc(), (
        f"{TARGET} is stale; regenerate with `make events-doc`"
    )


def test_the_registry_matches_the_specification(repo: Path):
    """The ten rows of §9's "R1 event set" table, by name and publisher.

    Read out of the specification rather than restated here, so editing one
    without the other fails.

    Eight until `AUTH-01`. §9's table listed neither `UserRegistered` nor
    `UserDeletionRequested` while `02-auth-and-account.md` §8 named auth as
    their publisher and `AUTH-01`'s Outputs required the first of them - so
    `publish` rejected a name the specification demanded, and registration was
    unbuildable. §9 gained both rows and `AC-FOUND-09.4` now says ten.

    The count is asserted separately from the set comparison below, and both
    are worth keeping: the comparison catches a rename, the count catches a row
    silently dropped from the table while the code still has it.
    """
    section = (repo / "docs" / "spec" / "01-foundations.md").read_text(encoding="utf-8")
    table = section.split("**R1 event set.**", 1)[1].split("**Inputs.**", 1)[0]

    # Rows look like: | `ProfileUpdated{...}` | profile | matching | enqueue ... |
    rows = re.findall(r"^\|\s*`([A-Za-z]+)\{[^}]*\}`\s*\|\s*([a-z]+)\s*\|", table, re.MULTILINE)
    declared = {name: publisher for name, publisher in rows}

    assert declared, "no event rows parsed out of §9 - has the table moved?"
    assert len(declared) == 10, f"§9 declares {len(declared)} events, expected 10"

    in_code = {spec.name: spec.published_by for spec in R1_EVENTS}
    assert in_code == declared, (
        "app/core/events.py and 01-foundations.md §9 disagree about the event set"
    )


def test_every_event_declares_its_payload_fields():
    for spec in R1_EVENTS:
        assert spec.fields, f"{spec.name} declares no payload"
        for field in spec.fields:
            assert re.fullmatch(r"[a-z][a-z0-9_]*", field), f"{spec.name}.{field}"


def test_the_document_names_every_event(repo: Path):
    text = (repo / TARGET).read_text(encoding="utf-8")
    for spec in R1_EVENTS:
        assert spec.name in text, f"{spec.name} is absent from {TARGET}"


def test_the_document_says_it_is_generated(repo: Path):
    text = (repo / TARGET).read_text(encoding="utf-8")
    assert "Do not edit" in text
