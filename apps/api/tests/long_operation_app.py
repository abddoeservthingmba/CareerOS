"""A route triple in the shape `FOUND-11` §11 prescribes.

`POST` returning `202`, a status `GET`, and an events `GET` - three routes over
one `OperationStore`, which is the arrangement every long operation in the
product will use: the resume pipeline (`RES-01`, P2) and pack generation
(`APPLY-02`, P4) first.

Built here rather than imported from a module, because neither of those exists
yet and `app/modules/` is empty. Four of `FOUND-11`'s five criteria are about
the *contract* a triple has to satisfy - the `202` body, the poll fallback, the
ownership answer, the headers - and those are assertable now, against a triple
that does nothing but move an operation through its stages.

Written before the first real one so that it is measured against the contract,
rather than the contract being written to describe whatever the first one did.

Not a `conftest.py` fixture: this is a fixture *and* a worked example of the
shape, and burying it in a fixture file would hide the second half.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from fastapi import FastAPI, Request

from app.core.errors import NotFound
from app.core.sse import (
    OperationStore,
    Stages,
    Status,
    accepted,
    event_stream,
    sse_response,
)

OWNER = "01J000000000000000000OWNER"
STRANGER = "01J0000000000000000STRANGE"
BASE = "/api/v1/applications/01J0000000000000000APP/pack"

#: `09-apply.md` §2's stages for pack generation: "gathering → generating →
#: checking → ready". A per-operation enum declared by the module that owns the
#: operation, exactly as §11 requires.
PACK_STAGES = Stages.of("apply.generate_pack", "gathering", "generating", "checking", "ready")


def caller_of(request: Request) -> str:
    """Who is asking.

    A header here; `AUTH-02`'s bearer token in P1. What matters for
    `AC-FOUND-11.3` is that the *store* enforces ownership, not the shape of the
    credential - so swapping this for a real one changes nothing below it.
    """
    return request.headers.get("X-Test-User", OWNER)


def build_app(
    settings: Any,
    *,
    lifetime: timedelta | None = None,
    heartbeat: timedelta | None = None,
) -> FastAPI:
    from app.main import create_app

    app = create_app(settings)
    store = OperationStore()
    app.state.operations = store

    @app.post(BASE, status_code=202, include_in_schema=False)
    async def start(request: Request) -> dict[str, Any]:
        from app.core.ids import new_id

        task_id = new_id()
        store.start(task_id, caller_of(request))
        return accepted(task_id, BASE).model_dump(mode="json")

    @app.get(f"{BASE}/{{task_id}}", include_in_schema=False)
    async def status(request: Request, task_id: str) -> dict[str, Any]:
        state = store.get(task_id, caller_of(request))
        if state is None:
            # `02-auth-and-account.md` §6: 404, never 403. A 403 would confirm
            # that someone else's task exists.
            raise NotFound()
        return state.snapshot()

    @app.get(f"{BASE}/{{task_id}}/events", include_in_schema=False)
    async def events(request: Request, task_id: str) -> Any:
        state = store.get(task_id, caller_of(request))
        if state is None:
            raise NotFound()
        queue = store.subscribe(task_id)
        # `is_disconnected` is deliberately not wired here. Starlette's
        # `TestClient` drives ASGI through a portal that never delivers a
        # `http.disconnect`, so asking the transport whether the client is still
        # there blocks the test rather than answering it. Disconnect handling is
        # asserted directly against `event_stream` in
        # `tests/integration/test_sse_lifecycle.py`, where the transport can be
        # made to answer.
        return sse_response(
            event_stream(
                state,
                queue,
                # `is None`, not `or`: `timedelta(0)` is falsy, so `lifetime or
                # default` silently turns "expire immediately" into "expire in
                # ten minutes" - and the test that asked for zero then hangs for
                # ten. The same shape bit `SenderBase`'s bounce registry.
                heartbeat=timedelta(seconds=15) if heartbeat is None else heartbeat,
                lifetime=timedelta(minutes=10) if lifetime is None else lifetime,
            )
        )

    return app


async def run_pipeline(store: OperationStore, task_id: str, *, fail_at: str = "") -> None:
    """Move an operation through its stages, as a worker would."""
    for stage in PACK_STAGES.names:
        await asyncio.sleep(0)
        if stage == fail_at:
            store.advance(task_id, stage, PACK_STAGES.progress(stage), Status.FAILED, "boom")
            return
        terminal = stage == PACK_STAGES.names[-1]
        store.advance(
            task_id,
            stage,
            100 if terminal else PACK_STAGES.progress(stage),
            Status.SUCCEEDED if terminal else Status.RUNNING,
        )


__all__ = [
    "BASE",
    "OWNER",
    "PACK_STAGES",
    "STRANGER",
    "build_app",
    "run_pipeline",
]
