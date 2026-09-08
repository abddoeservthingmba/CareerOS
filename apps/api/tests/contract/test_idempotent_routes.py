"""T-FOUND-08.4 - the routes that must be protected, are.

`AC-FOUND-08.4`: "A route in the "must honour" list that lacks the dependency
fails a contract test."

`01-foundations.md` §8 names the list: "Any `POST` that spends money, sends a
message, or creates a durable artifact **must** honour an `Idempotency-Key`
header: pack generation, pack regeneration, applied-confirmation, custom
reminders, export requests, admin connector runs."

**An explicit allowlist, not a pattern.** The specification's Tests list says so
- "asserts the dependency is present on an explicit route allowlist kept in the
test" - and the reason is that every inference rule has a hole. "Every POST" is
too broad and would be relaxed the first time it flagged something harmless.
"Every route whose handler charges money" cannot be seen from the route table.
A named list is the only rule that a new spending endpoint cannot slip past by
being shaped differently: it has to be added here, and adding it is a decision
someone makes on purpose.

**Most of it does not exist yet.** `app/modules/` is empty until P1; pack
generation is `APPLY-02` in P4. So the file-level assertions run today - the
allowlist is checked against the specification's own sentence, so a spec change
fails here - and the per-route assertion binds the moment a route appears.
`AC-FOUND-15.7` forbids skipping, and a gate written after the violation is a
gate written to accommodate it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import pytest
from fastapi import Depends

from app.core.idempotency import RequiresIdempotency, Scope

#: Declared at module level, not inside the tests that use them. With
#: `from __future__ import annotations` every annotation is a string, and
#: FastAPI resolves it against the module's globals - a type alias defined
#: inside a function is invisible there, and the dependency silently does not
#: register. That failure looks exactly like "the detector does not work".
Protection = Annotated[Scope, Depends(RequiresIdempotency())]
Spending = Annotated[Scope, Depends(RequiresIdempotency(spends_money=True))]


async def spending_endpoint(scope: Spending) -> Scope:
    """A shared "authenticated spending endpoint" dependency, as a route would
    realistically declare it."""
    return scope


Nested = Annotated[Scope, Depends(spending_endpoint)]


@dataclass(frozen=True)
class Protected:
    """One entry of §8's list.

    `path` is `None` where the specification names the capability but has not
    fixed the route - custom reminders and export requests are both like this.
    Recorded as `None` rather than guessed: a guessed path silently matches
    nothing, which is a gate that passes because it is looking in the wrong
    place.
    """

    capability: str
    method: str
    path: str | None
    requirement: str
    spends_money: bool


#: §8's six, in its order.
MUST_HONOUR: tuple[Protected, ...] = (
    Protected(
        "pack generation",
        "POST",
        "/api/v1/applications/{id}/pack",
        "APPLY-02",
        spends_money=True,
    ),
    Protected(
        "pack regeneration",
        "POST",
        "/api/v1/applications/{id}/pack/regenerate",
        "APPLY-04",
        spends_money=True,
    ),
    Protected(
        "applied-confirmation",
        "POST",
        "/api/v1/applications/{id}/applied",
        "APPLY-06",
        spends_money=False,
    ),
    Protected("custom reminders", "POST", None, "NOTIF-03", spends_money=False),
    Protected("export requests", "POST", None, "AUTH-08", spends_money=False),
    Protected(
        "admin connector runs",
        "POST",
        "/api/v1/admin/connectors/{name}/run",
        "ADMIN-01",
        spends_money=False,
    ),
)


def declared_capabilities(repo: Path) -> list[str]:
    """§8's sentence, read out of the specification.

    Parsed rather than transcribed so that adding a seventh capability to the
    specification fails this file instead of silently leaving the seventh
    endpoint unprotected.
    """
    text = (repo / "docs" / "spec" / "01-foundations.md").read_text(encoding="utf-8")
    sentence = next(
        line for line in text.split("\n") if "must** honour an `Idempotency-Key`" in line
    )
    listed = sentence.split("header:", 1)[1]
    return [item.strip().rstrip(".") for item in listed.split(",")]


def routes_of(app: Any) -> dict[tuple[str, str], Any]:
    """`(method, path)` to route, flattened through included routers."""
    found: dict[tuple[str, str], Any] = {}

    def walk(routes: Any) -> None:
        for route in routes:
            for method in getattr(route, "methods", ()) or ():
                found[(method, getattr(route, "path", ""))] = route
            walk(getattr(route, "routes", ()) or ())

    walk(app.routes)
    return found


def has_the_dependency(route: Any) -> bool:
    """Whether `RequiresIdempotency` is anywhere in the route's dependency tree.

    By type, not by name. A naming convention would be satisfied by a handler
    called `create_pack_idempotent` that does nothing, and that is exactly the
    kind of thing that gets written at the end of a long day.
    """
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return False

    def walk(node: Any) -> bool:
        if isinstance(getattr(node, "call", None), RequiresIdempotency):
            return True
        return any(walk(child) for child in getattr(node, "dependencies", ()))

    return walk(dependant)


# -- the list itself ---------------------------------------------------------


def test_the_allowlist_is_the_one_the_specification_names(repo: Path):
    """A seventh capability in §8 fails here rather than shipping unprotected."""
    assert [entry.capability for entry in MUST_HONOUR] == declared_capabilities(repo)


def test_every_entry_is_a_post():
    """§8: "Any **`POST`** that spends money...". A `PATCH` on this list would
    mean the rule had quietly grown."""
    assert {entry.method for entry in MUST_HONOUR} == {"POST"}


def test_the_paths_that_are_known_come_from_the_specification(repo: Path):
    """Each stated path appears in the requirement that owns it, so a route
    renamed in the spec fails here rather than going unwatched."""
    spec_text = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((repo / "docs" / "spec").glob("*.md"))
    )
    for entry in MUST_HONOUR:
        if entry.path is None:
            continue
        # The specification writes routes without the `/api/v1` prefix.
        tail = entry.path.removeprefix("/api/v1")
        stem = tail.rsplit("/", 1)[0] if tail.endswith("/regenerate") else tail
        assert re.search(re.escape(stem), spec_text), (
            f"{entry.capability}: {stem} appears nowhere in the specification"
        )


def test_the_spending_entries_are_the_ai_ones():
    """§8: "a durable record for anything that spent money". The two pack
    operations are the ones behind an AI call; a `POST` that only writes a row
    costs nothing to repeat beyond the row."""
    assert {entry.capability for entry in MUST_HONOUR if entry.spends_money} == {
        "pack generation",
        "pack regeneration",
    }


def test_no_capability_is_listed_twice():
    capabilities = [entry.capability for entry in MUST_HONOUR]
    assert len(set(capabilities)) == len(capabilities)


# -- the routes, as they land ------------------------------------------------


@pytest.mark.parametrize("entry", MUST_HONOUR, ids=lambda e: e.requirement)
def test_the_route_declares_the_dependency_once_it_exists(entry: Protected, settings_factory):
    """AC-FOUND-08.4.

    Vacuous until the route lands, and binding from the moment it does. Written
    now rather than with the route, because a gate added alongside the thing it
    guards is a gate written to fit it.
    """
    from app.main import create_app

    app = create_app(settings_factory())
    if entry.path is None:
        return
    route = routes_of(app).get((entry.method, entry.path))
    if route is None:
        return
    assert has_the_dependency(route), (
        f"{entry.capability} ({entry.requirement}) is on §8's must-honour list "
        f"but {entry.method} {entry.path} does not depend on RequiresIdempotency"
    )


def test_a_route_without_the_dependency_is_detected(settings_factory):
    """The negative control, and the load-bearing test in this file today.

    Every assertion above is vacuous while `app/modules/` is empty. This one
    proves the detector actually detects - so that when the first route lands,
    a missing dependency fails rather than passing quietly.
    """
    from fastapi import FastAPI

    app = FastAPI()

    @app.post("/protected")
    async def protected(scope: Protection) -> dict[str, str]:
        return {}

    @app.post("/unprotected")
    async def unprotected() -> dict[str, str]:
        return {}

    routes = routes_of(app)
    assert has_the_dependency(routes[("POST", "/protected")]) is True
    assert has_the_dependency(routes[("POST", "/unprotected")]) is False


def test_a_nested_dependency_is_detected(settings_factory):
    """A route that declares protection through a shared "authenticated
    spending endpoint" dependency is still protected, and a detector that only
    looked one level deep would say otherwise - then someone would "fix" it by
    removing the nesting."""
    from fastapi import FastAPI

    app = FastAPI()

    @app.post("/nested")
    async def nested(scope: Nested) -> dict[str, str]:
        return {}

    assert has_the_dependency(routes_of(app)[("POST", "/nested")]) is True


def test_the_dependency_requires_the_header(settings_factory):
    """A route on the list that accepted a request without a key would be
    unprotected for exactly the clients that need it - the ones retrying because
    something already went wrong."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(settings_factory())

    @app.post("/_test/spend", include_in_schema=False)
    async def spend(scope: Spending) -> dict[str, str]:
        return {"scope": scope.route}

    client = TestClient(app, raise_server_exceptions=False)

    missing = client.post("/_test/spend", json={})
    assert missing.status_code == 422
    assert "Idempotency-Key" in missing.json()["detail"]

    present = client.post(
        "/_test/spend", json={}, headers={"Idempotency-Key": "6f1b0b6e-6d2f-4f0a"}
    )
    assert present.status_code == 200
    assert present.json()["scope"] == "POST /_test/spend"


def test_the_health_endpoints_are_not_on_the_list(settings_factory):
    """The rule is about side effects, not about every route. A `GET` that
    required a key would be noise, and noise is how a rule stops being read."""
    from app.main import create_app

    app = create_app(settings_factory())
    for (method, path), route in routes_of(app).items():
        if path in ("/healthz", "/readyz"):
            assert method == "GET"
            assert not has_the_dependency(route)
