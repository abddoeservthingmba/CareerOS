"""T-AI-04.4 - accounting never fails a feature.

`AC-AI-04.4`: "Failing the `ai_usage` write does not fail the feature call."

`05-ai-layer.md` §4: "The write of the usage row must not be able to fail the
feature. It is fire-and-forget with a bounded in-process buffer flushed by the
worker; a full buffer drops rows and increments a counter rather than blocking."

The order of harms is stated, not assumed. Losing an accounting row is bad: the
day's total is short, and the dashboard is wrong by that much. Failing a user's
pack generation because the accounting collection was briefly unavailable is
worse: they lose work, they see an error they cannot act on, and the thing that
broke had nothing to do with what they asked for.

So three properties, each separately testable:

* **`record` never raises.** Whatever is wrong - a full buffer, an unserialisable
  value, a metric that blew up - the caller returns normally.
* **The buffer is bounded.** An unbounded one in front of a database that has
  stopped answering is how an accounting problem becomes a memory limit during
  an incident.
* **A drop is counted.** `dropped` is what tells an operator the books are
  incomplete for a window, which is a far less alarming statement than "spend
  fell off a cliff" - and it is the only way to tell the two apart.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.ai.base import Feature
from app.ai.usage import Outcome, UsageRecorder, build_row


def a_row(**kwargs: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "provider": "gemini",
        "model": "gemini-3.5-flash-lite",
        "feature": Feature.PACK_GENERATE,
        "outcome": Outcome.OK,
        "input_tokens": 100,
        "output_tokens": 20,
        "est_cost_usd": Decimal("0.0004"),
    }
    defaults.update(kwargs)
    return build_row(**defaults)


# -- record never raises -----------------------------------------------------


def test_a_full_buffer_drops_rather_than_blocking():
    """§4, verbatim: "a full buffer drops rows and increments a counter rather
    than blocking"."""
    recorder = UsageRecorder(capacity=3)
    for _ in range(10):
        recorder.record(a_row())

    assert recorder.pending() == 3
    assert recorder.dropped == 7


def test_a_full_buffer_keeps_the_oldest_rows():
    """Deliberate, and worth stating: the buffer refuses new rows rather than
    evicting old ones.

    Either choice loses data. Refusing loses the newest, which the caller has
    just been told about through the `dropped` counter; evicting loses the
    oldest, which nothing would ever mention again.
    """
    recorder = UsageRecorder(capacity=2)
    recorder.record(a_row(feature=Feature.RESUME_EXTRACT))
    recorder.record(a_row(feature=Feature.JOB_ENRICH))
    recorder.record(a_row(feature=Feature.PACK_GENERATE))

    kept = [row["feature"] for row in recorder.drain()]
    assert kept == ["resume_extract", "job_enrich"]


def test_record_does_not_raise_on_a_malformed_row():
    """`record` takes whatever it is given.

    The caller is a feature in the middle of doing something for a user. It has
    no useful way to handle "the accounting object was unhappy", so it is never
    asked to.
    """
    recorder = UsageRecorder()

    recorder.record({"feature": object(), "input_tokens": "not a number"})

    assert recorder.dropped == 1


def test_record_does_not_raise_when_the_metric_write_fails(monkeypatch):
    """The metric families are written from the same row. A Prometheus client
    error must not become a failed pack generation."""
    from app.core import metrics

    class Exploding:
        def labels(self, **_: Any) -> Any:
            raise RuntimeError("the registry is unhappy")

    monkeypatch.setattr(metrics, "ai_tokens", Exploding())
    recorder = UsageRecorder()

    recorder.record(a_row())

    assert recorder.dropped == 1
    assert recorder.pending() == 0


def test_a_drop_is_counted_not_silent():
    """The counter is the whole difference between "the books are incomplete for
    this window" and "spend fell off a cliff"."""
    recorder = UsageRecorder(capacity=1)
    recorder.record(a_row())
    assert recorder.dropped == 0

    recorder.record(a_row())
    assert recorder.dropped == 1


# -- the flush ---------------------------------------------------------------


async def test_a_failing_flush_does_not_raise():
    """`AC-AI-04.4`, at the other end.

    The worker calls this. A raise here would fail the task, which would retry,
    which would try to flush again - a retry loop in front of a database that is
    already down.
    """
    recorder = UsageRecorder()
    recorder.record(a_row())

    written = await recorder.flush()

    # No Beanie initialisation in this suite, so the insert fails - which is
    # exactly the condition being asserted.
    assert written == 0
    assert recorder.dropped == 1


async def test_a_failed_flush_does_not_retry_forever():
    """Rows that could not be written are counted as dropped rather than put
    back. A buffer that retried would grow until the process died, and the
    accounting outage would become an application outage."""
    recorder = UsageRecorder()
    for _ in range(5):
        recorder.record(a_row())

    await recorder.flush()

    assert recorder.pending() == 0
    assert recorder.dropped == 5


async def test_flushing_an_empty_buffer_is_a_no_op():
    """The worker's cron calls this every minute whether or not anything
    happened. It must not cost a round trip to find that out."""
    recorder = UsageRecorder()

    assert await recorder.flush() == 0
    assert recorder.dropped == 0


def test_draining_empties_the_buffer():
    recorder = UsageRecorder()
    recorder.record(a_row())
    recorder.record(a_row())

    assert len(recorder.drain()) == 2
    assert recorder.pending() == 0
    assert recorder.drain() == []


# -- the control -------------------------------------------------------------


def test_a_working_recorder_keeps_everything():
    """Without this, an implementation that dropped every row would pass every
    assertion above."""
    recorder = UsageRecorder(capacity=100)
    for _ in range(50):
        recorder.record(a_row())

    assert recorder.pending() == 50
    assert recorder.dropped == 0


def test_the_default_capacity_is_bounded():
    """Bounded at all is the requirement. The number is a judgement: 10,000 rows
    is minutes of traffic at this product's scale, and a few megabytes."""
    recorder = UsageRecorder()

    assert recorder._capacity > 0  # noqa: SLF001
    assert recorder._capacity <= 100_000  # noqa: SLF001
