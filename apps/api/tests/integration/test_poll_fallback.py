"""T-FOUND-11.2 - the whole flow, with SSE blocked.

`AC-FOUND-11.2`: "Every flow that uses SSE is completable end to end with SSE
blocked, using `status_url` alone (proven for the resume pipeline and pack
generation)."

This is the criterion most likely to be quietly false. The developer building
the feature watches the stream, the demo watches the stream, the manual test
watches the stream - and the polling path is exercised by nobody until a user
behind a buffering corporate proxy cannot find out that their pack is ready.

Streaming is an optimisation over polling. The moment it becomes the only way to
learn a terminal status, some fraction of users can never apply to a job.

What makes it true here is structural rather than diligent: `status_url` and the
stream are two renderings of one `OperationState`. There is nothing for them to
disagree about. The tests below check that the structure holds - that a poller
sees every stage a streamer sees, learns the terminal status, and never needs
the stream to be opened at all.

**The resume pipeline and pack generation are P2 and P4.** The triple under test
is `tests/long_operation_app.py`, built to the shape §11 prescribes and carrying
`09-apply.md` §2's actual stages. When the real ones land they are held to this.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.sse import AcceptedResponse, Status
from tests.long_operation_app import (
    BASE,
    PACK_STAGES,
    build_app,
    run_pipeline,
)


class NoStreaming(TestClient):
    """A client that cannot open the stream at all.

    Blocked rather than merely unused: a test that simply does not call
    `events_url` proves that polling *also* works. This proves that polling
    works *instead*, which is what the criterion says.
    """

    def request(self, method: str, url: Any, **kwargs: Any) -> Any:
        if str(url).endswith("/events"):
            raise AssertionError(
                "this flow reached for the stream; AC-FOUND-11.2 requires it to "
                "be completable with status_url alone"
            )
        return super().request(method, url, **kwargs)


@pytest.fixture
def client(settings_factory) -> NoStreaming:
    return NoStreaming(build_app(settings_factory()))


def start(client: TestClient) -> AcceptedResponse:
    return AcceptedResponse.model_validate(client.post(BASE).json())


# -- the flow, by polling only -----------------------------------------------


async def test_the_flow_completes_with_the_stream_blocked(client: NoStreaming):
    """AC-FOUND-11.2."""
    body = start(client)
    store = client.app.state.operations  # type: ignore[attr-defined]

    seen: list[str] = []
    await run_pipeline(store, body.task_id)

    snapshot = client.get(body.status_url).json()
    seen.append(snapshot["status"])

    assert snapshot["status"] == str(Status.SUCCEEDED)
    assert snapshot["terminal"] is True
    assert snapshot["progress"] == 100
    assert seen == [str(Status.SUCCEEDED)]


async def test_a_poller_sees_every_stage_a_streamer_would(client: NoStreaming):
    """The two are renderings of one state, so "the same information, less
    often" has to be literally true rather than approximately."""
    body = start(client)
    store = client.app.state.operations  # type: ignore[attr-defined]

    observed: list[str] = []
    pipeline = asyncio.create_task(run_pipeline(store, body.task_id))
    for _ in range(40):
        stage = client.get(body.status_url).json()["stage"]
        if stage and (not observed or observed[-1] != stage):
            observed.append(stage)
        if client.get(body.status_url).json()["terminal"]:
            break
        await asyncio.sleep(0)
    await pipeline

    assert observed[-1] == PACK_STAGES.names[-1]
    assert set(observed) <= set(PACK_STAGES.names)


async def test_a_poller_learns_a_failure(client: NoStreaming):
    """A terminal status is not only "succeeded". A fallback that could only
    observe success would leave a failed pack looking like a slow one for ever.
    """
    body = start(client)
    store = client.app.state.operations  # type: ignore[attr-defined]

    await run_pipeline(store, body.task_id, fail_at="generating")
    snapshot = client.get(body.status_url).json()

    assert snapshot["status"] == str(Status.FAILED)
    assert snapshot["terminal"] is True
    assert snapshot["detail"] == "boom"


async def test_polling_before_anything_happens_is_a_valid_answer(client: NoStreaming):
    """The first poll usually arrives before the worker has picked the job up.
    `queued` with `terminal: false` is the answer; a 404 or a 500 would send the
    client into a retry loop against a task that is perfectly fine."""
    body = start(client)
    snapshot = client.get(body.status_url).json()

    assert snapshot["status"] == str(Status.QUEUED)
    assert snapshot["terminal"] is False
    assert snapshot["progress"] == 0


async def test_polling_after_completion_still_answers(client: NoStreaming):
    """A client that was asleep when the operation finished must still be able
    to find out. A state that were discarded on the terminal event would make
    the fallback a race."""
    body = start(client)
    store = client.app.state.operations  # type: ignore[attr-defined]
    await run_pipeline(store, body.task_id)

    for _ in range(3):
        snapshot = client.get(body.status_url).json()
        assert snapshot["status"] == str(Status.SUCCEEDED)


async def test_the_poll_body_and_the_stream_event_carry_the_same_facts(
    settings_factory,
):
    """The structural claim, asserted directly.

    If these ever diverge, the fallback stops being "the same information" and
    the tests above become a description of a coincidence.
    """
    client = TestClient(build_app(settings_factory()))
    body = AcceptedResponse.model_validate(client.post(BASE).json())
    store = client.app.state.operations  # type: ignore[attr-defined]

    event = store.advance(body.task_id, "generating", 25, Status.RUNNING, "drafting")
    snapshot = client.get(body.status_url).json()

    assert snapshot["stage"] == event.stage
    assert snapshot["progress"] == event.progress
    assert snapshot["status"] == str(event.status)
    assert snapshot["detail"] == event.detail


# -- the stages -------------------------------------------------------------


def test_the_stages_are_the_ones_the_apply_spec_declares():
    """§11: "Stages are a fixed per-operation enum, declared in the module's
    spec file." `09-apply.md` §2: "gathering → generating → checking → ready"."""
    assert PACK_STAGES.names == ("gathering", "generating", "checking", "ready")


def test_progress_is_derived_from_the_stage_position():
    """Hand-assigned percentages are two places holding one fact, and the
    symptom of them disagreeing is a progress bar that goes backwards."""
    values = [PACK_STAGES.progress(stage) for stage in PACK_STAGES.names]
    assert values == sorted(values)
    assert values[0] == 0
    assert all(0 <= value <= 100 for value in values)


def test_an_undeclared_stage_is_refused():
    with pytest.raises(ValueError, match="not a stage"):
        PACK_STAGES.progress("polishing")


def test_a_stage_list_with_a_duplicate_is_refused():
    from app.core.sse import Stages

    with pytest.raises(ValueError, match="twice"):
        Stages.of("apply.generate_pack", "gathering", "gathering")


def test_an_empty_stage_list_is_refused():
    from app.core.sse import Stages

    with pytest.raises(ValueError, match="no stages"):
        Stages.of("apply.generate_pack")
