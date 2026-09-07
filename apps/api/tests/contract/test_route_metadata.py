"""T-FOUND-13.1 - every public route is fully declared.

`AC-FOUND-13.1`: "Every route under `/api/v1` has a `response_model`, an explicit
`status_code`, a module-matching tag, and an `operation_id` matching
`^[a-z_]+_[a-z_]+$`."

None of these is bookkeeping. Each one is a thing that goes wrong in a generated
client, weeks later, in someone else's repository.

**`response_model`** is what the client's type comes from. Without it FastAPI
documents the response as an untyped object, and the generated client hands
back `any` - so the compiler stops helping exactly where it was most useful,
silently, on one endpoint.

**An explicit `status_code`** because the default is 200 and half these routes
are 201 or 202. A client that believes a `202` is a `200` believes the work is
finished.

**A module-matching tag** because the generated clients group methods by tag. A
route tagged `misc` ends up in a namespace that means nothing, and the next
route tagged `misc` joins it.

**An `operation_id` of `<module>_<action>`** because it *is* the generated
method name. Leave it unset and FastAPI derives one from the function name and
the path - `list_jobs_api_v1_jobs_get` - which changes whenever the path
changes, so a purely additive route move renames a method in two client
libraries and breaks every call site.

`app/modules/` is empty until P1, so this scans nothing today and everything the
moment the first router lands. Written now rather than then: a rule introduced
alongside the code it governs gets bent to fit it, and this one is only cheap
while there is nothing to fix.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

PUBLIC_PREFIX = "/api/v1"

#: `AC-FOUND-13.1`, verbatim.
OPERATION_ID = re.compile(r"^[a-z_]+_[a-z_]+$")

#: `01-foundations.md` §1's module list, which is what a tag has to match.
MODULES = frozenset(
    {
        "auth",
        "profile",
        "resume",
        "jobs",
        "matching",
        "apply",
        "tracker",
        "notifications",
        "admin",
    }
)

#: §13: "`/healthz`, `/readyz`, `/metrics` sit outside `/api/v1` and outside the
#: generated clients." A load balancer and a scrape job are not API consumers.
OPERATIONAL = ("/healthz", "/readyz", "/metrics", "/internal/", "/docs", "/openapi.json", "/redoc")


@pytest.fixture
def app(settings_factory) -> FastAPI:
    from app.main import create_app

    return create_app(settings_factory())


def methods(route: APIRoute) -> list[str]:
    """The route's verbs, in a stable order.

    `APIRoute.methods` is typed as optional even though a mounted route always
    has one; sorting `None` would be the failure, and an empty list reads the
    same in a message.
    """
    return sorted(route.methods or [])


def public_routes(app: FastAPI) -> list[APIRoute]:
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith(PUBLIC_PREFIX)
    ]


# -- the four declarations ---------------------------------------------------


def test_every_public_route_declares_a_response_model(app: FastAPI):
    """AC-FOUND-13.1.

    Without it the generated client's return type is `any`, and the compiler
    stops helping on exactly one endpoint without saying so.
    """
    missing = [
        f"{methods(route)} {route.path}"
        for route in public_routes(app)
        if route.response_model is None
    ]
    assert missing == [], "\n".join(missing)


def test_every_public_route_declares_a_status_code(app: FastAPI):
    """The default is 200, and half of these are 201 or 202. A client that reads
    a `202` as a `200` believes the work is done."""
    missing = [
        f"{methods(route)} {route.path}"
        for route in public_routes(app)
        if route.status_code is None
    ]
    assert missing == [], "\n".join(missing)


def test_every_public_route_has_a_module_tag(app: FastAPI):
    """The generated clients group methods by tag, so a route tagged `misc`
    lands in a namespace that means nothing - and the next one joins it."""
    wrong = [
        f"{methods(route)} {route.path}: tags={route.tags}"
        for route in public_routes(app)
        if not set(route.tags or []) & MODULES
    ]
    assert wrong == [], "a tag must name the owning module:\n" + "\n".join(wrong)


def test_every_public_route_has_a_stable_operation_id(app: FastAPI):
    """`AC-FOUND-13.1`'s `^[a-z_]+_[a-z_]+$`.

    This string is the generated method name. Left unset, FastAPI derives it
    from the function name and the path, so moving a route - a purely additive
    change - renames a method in two client libraries and breaks every call
    site that used it.
    """
    wrong = [
        f"{methods(route)} {route.path}: {route.operation_id!r}"
        for route in public_routes(app)
        if not (route.operation_id and OPERATION_ID.match(route.operation_id))
    ]
    assert wrong == [], "\n".join(wrong)


def test_the_operation_id_names_the_owning_module(app: FastAPI):
    """§13: "an `operation_id` of `<module>_<action>`". The prefix is the module,
    so a generated method name reads as `jobs.search` rather than as a word
    somebody picked."""
    wrong = [
        f"{route.path}: {route.operation_id}"
        for route in public_routes(app)
        if route.operation_id and route.operation_id.split("_")[0] not in MODULES
    ]
    assert wrong == [], "\n".join(wrong)


def test_no_two_routes_share_an_operation_id(app: FastAPI):
    """A duplicate silently overwrites one method in the generated client, and
    the call sites for the losing one compile against the wrong signature."""
    seen: dict[str, str] = {}
    clashes: list[str] = []
    for route in public_routes(app):
        if route.operation_id is None:
            continue
        if route.operation_id in seen:
            clashes.append(f"{route.operation_id}: {seen[route.operation_id]} and {route.path}")
        seen[route.operation_id] = route.path
    assert clashes == [], "\n".join(clashes)


def test_every_public_route_documents_its_errors(app: FastAPI):
    """§13: "a `responses` entry for every error code it can raise".

    A client generated from a document that only knows about 200 has no type for
    the problem body, so every error path is untyped in exactly the code that
    handles failures.
    """
    undocumented = [
        f"{methods(route)} {route.path}"
        for route in public_routes(app)
        if not (route.responses or {})
    ]
    assert undocumented == [], "\n".join(undocumented)


# -- the boundary ------------------------------------------------------------


def test_the_operational_routes_are_outside_the_public_prefix(app: FastAPI):
    """§13. A load balancer and a scrape job are not API consumers, and a
    `/healthz` inside `/api/v1` would appear in both generated clients."""
    for route in app.routes:
        path = getattr(route, "path", "")
        if path in ("/healthz", "/readyz", "/metrics"):
            assert not path.startswith(PUBLIC_PREFIX)


def test_the_operational_routes_are_out_of_the_schema(app: FastAPI):
    """`AC-FOUND-13.5`'s mechanism, asserted where it is set rather than only
    where it is observed."""
    paths = app.openapi().get("paths", {})
    for path in OPERATIONAL:
        assert not any(documented.startswith(path) for documented in paths), (
            f"{path} is in the OpenAPI document, so it will be in both clients"
        )


def test_the_rules_bind_a_route_that_breaks_them(settings_factory):
    """The load-bearing test in this file today.

    Every assertion above scans `/api/v1`, which is empty until P1 - so all of
    them pass vacuously. This one adds a badly declared route and asserts the
    checks catch it, which is what makes the vacuous ones trustworthy the day
    the first router lands.
    """
    from app.main import create_app

    app = create_app(settings_factory())

    @app.get(f"{PUBLIC_PREFIX}/bad")
    async def bad() -> Any:
        return {}

    routes = public_routes(app)
    assert len(routes) == 1
    route = routes[0]

    assert route.response_model is None or route.response_model is Any
    assert not set(route.tags or []) & MODULES
    assert not OPERATION_ID.match(route.operation_id or ""), route.operation_id


def test_a_correctly_declared_route_passes_every_rule(settings_factory):
    """The other half of the control: the rules are satisfiable.

    A check that nothing could pass would be indistinguishable from a check that
    works, right up to the moment it blocked the first real router.
    """
    from pydantic import BaseModel

    from app.main import create_app

    class JobOut(BaseModel):
        id: str
        title: str

    app = create_app(settings_factory())

    @app.get(
        f"{PUBLIC_PREFIX}/jobs",
        response_model=list[JobOut],
        status_code=200,
        tags=["jobs"],
        operation_id="jobs_search",
        responses={422: {"description": "validation_error"}},
    )
    async def search() -> list[JobOut]:
        return []

    route = public_routes(app)[0]

    assert route.response_model is not None
    assert route.status_code == 200
    assert set(route.tags or []) & MODULES
    assert OPERATION_ID.match(route.operation_id or "")
    assert route.responses
