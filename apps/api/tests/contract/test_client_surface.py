"""T-FOUND-13.5 - the clients see `/api/v1` and nothing else.

`AC-FOUND-13.5`: "No route outside `/api/v1` appears in either generated
client."

`01-foundations.md` §13: "`/healthz`, `/readyz`, `/metrics` sit outside
`/api/v1` and outside the generated clients."

A load balancer is not an API consumer, and neither is a scrape job or a mail
provider posting a bounce. Letting their routes into the contract has three
costs and no benefit:

* **They become API.** Anything in the generated client is something a client
  developer can call, and anything a client calls is something that cannot be
  changed freely. `/readyz`'s body is an operational detail that should be free
  to change on a Tuesday.
* **They get versioned.** A `/healthz` in the contract is subject to §13's
  breaking-change rule, so removing a field from a readiness probe would need a
  `BREAKING-API-APPROVED:` token.
* **They advertise the surface.** `/internal/email/bounce` in a public client
  library is a documented endpoint for something a stranger should not know is
  there.

Two locks on the same door: `include_in_schema=False` on the routes, and
`export_openapi.prune()` dropping anything outside `/api/v1` on the way to the
committed document. The second exists because the first is a per-route flag, and
a per-route flag is a thing someone forgets exactly once.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

PUBLIC_PREFIX = "/api/v1"

#: Every operational route that exists today. Named rather than pattern-matched:
#: a pattern would quietly stop covering the next one, and this list failing is
#: how a new operational route gets considered.
OPERATIONAL = (
    "/healthz",
    "/readyz",
    "/internal/email/bounce",
    "/docs",
    "/redoc",
    "/openapi.json",
)


@pytest.fixture
def app(settings_factory) -> FastAPI:
    from app.main import create_app

    return create_app(settings_factory())


def exported(repo: Path) -> dict[str, Any]:
    sys.path.insert(0, str(repo / "infra" / "scripts"))
    import export_openapi

    return export_openapi.document()


# -- the document ------------------------------------------------------------


def test_the_document_contains_only_public_paths(app: FastAPI, repo: Path):
    """AC-FOUND-13.5."""
    paths = exported(repo).get("paths", {})
    outside = [path for path in paths if not path.startswith(PUBLIC_PREFIX)]
    assert outside == [], f"these would be generated into both clients: {outside}"


@pytest.mark.parametrize("path", OPERATIONAL)
def test_no_operational_route_reaches_the_document(repo: Path, path: str):
    """Each one named, so adding an operational route is a decision rather than
    an oversight."""
    paths = exported(repo).get("paths", {})
    assert path not in paths


def test_the_operational_routes_still_exist(app: FastAPI):
    """The control. A test asserting "these are not in the contract" would pass
    just as well if the routes had been deleted, and `/readyz` disappearing is a
    deployment that never becomes ready."""
    served = {getattr(route, "path", "") for route in app.routes}
    for path in ("/healthz", "/readyz"):
        assert path in served


def test_the_committed_document_matches_the_code(repo: Path):
    """`AC-FOUND-13.2`, asserted locally as well as in CI.

    CI is where the criterion is enforced, but a developer who regenerates
    nothing finds out at review rather than at commit - and by then the two
    generated clients in the PR describe a server that does not exist.
    """
    sys.path.insert(0, str(repo / "infra" / "scripts"))
    import export_openapi

    committed = repo / "packages" / "contracts" / "openapi.json"
    assert committed.is_file(), (
        "packages/contracts/openapi.json is missing; run "
        "`py infra/scripts/export_openapi.py --write`"
    )
    assert committed.read_text(encoding="utf-8") == export_openapi.render(
        export_openapi.document()
    ), (
        "the committed contract is stale, so both generated clients describe a "
        "server that no longer exists. Run "
        "`py infra/scripts/export_openapi.py --write`"
    )


def test_the_document_is_deterministic(repo: Path):
    """Sorted keys, so a reordering of `include_router` calls is not a diff.

    After the third false alarm nobody reads the API diff, and the first real
    breaking change goes through unread.
    """
    sys.path.insert(0, str(repo / "infra" / "scripts"))
    import export_openapi

    assert export_openapi.render(export_openapi.document()) == export_openapi.render(
        export_openapi.document()
    )
    rendered = export_openapi.render({"b": 1, "a": 2})
    assert rendered.index('"a"') < rendered.index('"b"')
    assert rendered.endswith("\n")


def test_the_prune_removes_a_route_that_forgot_the_flag(repo: Path):
    """The second lock, asserted directly.

    `include_in_schema=False` is a per-route flag, which is a thing someone
    forgets exactly once. This is what catches that once.
    """
    sys.path.insert(0, str(repo / "infra" / "scripts"))
    import export_openapi

    leaked: dict[str, Any] = {
        "paths": {
            "/api/v1/jobs": {"get": {}},
            "/healthz": {"get": {}},
            "/internal/email/bounce": {"post": {}},
        }
    }
    assert set(export_openapi.prune(leaked)["paths"]) == {"/api/v1/jobs"}


def test_the_document_declares_the_version_prefix(repo: Path):
    """§13: "All routes under `/api/v1`." With no routes yet the document is
    empty, and an empty document must not be mistaken for a passing check."""
    document = exported(repo)
    assert "openapi" in document
    assert "paths" in document
    for path in document["paths"]:
        assert path.startswith(PUBLIC_PREFIX)


# -- the generated clients ---------------------------------------------------


def test_the_generated_clients_are_ci_written_only(repo: Path):
    """`AC-FOUND-01.5`: "`packages/contracts` has no commits whose author is not
    the CI bot."

    Asserted here as the presence of the rule rather than as a git history
    check: the history assertion is `contracts.yml`'s guard step, and this is
    what makes the intent visible from the code.
    """
    readme = repo / "packages" / "contracts" / "README.md"
    assert readme.is_file(), "packages/contracts needs a README stating who writes it"
    text = readme.read_text(encoding="utf-8")
    assert "CI" in text
    assert "hand-edit" in text.lower() or "never edited" in text.lower()


def test_the_generated_client_directories_are_not_committed_by_hand(repo: Path):
    """`ts/` and `dart/` are build outputs. A committed one would be the version
    everyone actually uses, and it would drift from `openapi.json` silently."""
    ignore = (repo / ".gitignore").read_text(encoding="utf-8")
    assert "packages/contracts/ts/" in ignore
    assert "packages/contracts/dart/" in ignore


def test_an_operational_path_would_be_caught_if_it_reached_the_clients(repo: Path):
    """The negative control for this whole file.

    Every assertion above passes trivially while `paths` is empty. This proves
    the check can fail, which is what makes the others worth running before the
    first route lands.
    """
    sys.path.insert(0, str(repo / "infra" / "scripts"))
    import export_openapi

    leaked: dict[str, Any] = json.loads(json.dumps({"paths": {"/healthz": {"get": {}}}}))
    assert export_openapi.prune(leaked)["paths"] == {}
