"""T-AI-03.6 - a burst drains; it does not fail.

`AC-AI-03.6`: "200 enrichment calls against a 15-per-minute limiter all
complete, none raise, and elapsed time matches the limiter."

`05-ai-layer.md` §3.1: "Rate limits are separate from cost caps. A per-provider
token bucket at the provider's requests-per-minute limit queues and retries
rather than rejecting: a burst of 200 enrichments drains slowly, it does not
fail."

The separation is the point. A cost cap says "this is more than we will spend";
a rate limit says "this is faster than they will answer". The right response to
the first is to degrade the feature per §3.2. The right response to the second
is to wait, because the caller is a background enrichment task with nothing
better to do and the work is still worth doing a minute from now.

Rejecting would turn the provider's throttle into our outage - and worse, it
would do so at exactly the moment a large ingestion succeeded, so a good day for
the connectors would look like a bad day for enrichment.

**Elapsed time is asserted against a frozen clock**, not a real one. A test that
actually waited thirteen minutes for 200 calls at 15/min would never be run.

**Every bucket is constructed inside the frozen window, and that is
load-bearing rather than tidy.** `TokenBucket.__init__` captures `clock.now()`
as its refill baseline. Built before `clock.freeze(start)`, that baseline sits a
few microseconds *after* `start` - so the refill arithmetic sees 3.9999 seconds
elapsed against a 4-second interval, which is 0.99997 tokens rather than 1, and
the bucket sleeps when the test says it should not.

Whether it does depends on the platform's clock granularity. On Windows both
`clock.now()` calls land inside one timer tick, `elapsed` is exactly 4.0, and
the test passes. On Linux they do not, and it fails.
`test_tokens_refill_over_time` passed on this machine through the entire build
and failed on the first CI run that ever reached pytest - `assert 1 == 0`, the
sleep that should not have happened.

A tolerance would have hidden it. The boundary is the assertion.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from app.ai.budget import TokenBucket
from app.core import clock


class Ticker:
    """A sleep that advances the frozen clock instead of the wall clock.

    This is what makes "elapsed time matches the limiter" assertable in
    milliseconds: the bucket's own arithmetic is exercised exactly as it would
    be in production, and the only thing faked is the passage of time.
    """

    def __init__(self) -> None:
        self.total = 0.0
        self.calls = 0
        self._offset = timedelta(0)
        self._base = clock.now()

    async def __call__(self, seconds: float) -> None:
        self.total += seconds
        self.calls += 1
        self._offset += timedelta(seconds=seconds)

    @property
    def now(self):
        return self._base + self._offset


# -- the criterion -----------------------------------------------------------


async def test_two_hundred_calls_at_fifteen_a_minute_all_complete():
    """AC-AI-03.6, all three clauses: none raise, all complete, and the elapsed
    time is the limiter's."""
    ticker = Ticker()
    start = clock.now()

    # Constructed inside the frozen window - see the module docstring.
    with clock.freeze(start):
        bucket = TokenBucket(15, sleep=ticker, burst=1)
        for _ in range(200):
            await bucket.acquire()

    # 200 calls at 15/min is 199 intervals of 4 s after the first token.
    expected = 199 * (60 / 15)
    assert ticker.total == pytest.approx(expected, rel=0.01)


async def test_no_call_raises():
    """ "none raise". A limiter that rejected would make a successful ingestion
    look like a broken enrichment."""
    bucket = TokenBucket(15, sleep=Ticker(), burst=1)

    for _ in range(50):
        await bucket.acquire()  # would raise if it rejected


async def test_a_burst_within_the_allowance_does_not_wait():
    """The bucket holds a minute's worth of tokens, so a burst that fits inside
    the allowance is served immediately. Waiting there would make every call
    slower to protect a limit nobody was near."""
    ticker = Ticker()
    bucket = TokenBucket(15, sleep=ticker)

    for _ in range(15):
        await bucket.acquire()

    assert ticker.calls == 0


async def test_the_sixteenth_call_in_a_minute_waits():
    """The control for the test above. A bucket that never waited would satisfy
    it and provide no limiting at all."""
    ticker = Ticker()
    start = clock.now()

    # Constructed inside the frozen window - see the module docstring.
    with clock.freeze(start):
        bucket = TokenBucket(15, sleep=ticker)
        for _ in range(16):
            await bucket.acquire()

    assert ticker.calls == 1
    assert ticker.total == pytest.approx(4.0, rel=0.01)


async def test_tokens_refill_over_time():
    """A bucket that only ever drained would stop the worker permanently after
    the first burst."""
    ticker = Ticker()
    start = clock.now()

    # Constructed inside the frozen window - see the module docstring.
    with clock.freeze(start):
        bucket = TokenBucket(15, sleep=ticker, burst=1)
        await bucket.acquire()

    # Four seconds later, one token is back.
    with clock.freeze(start + timedelta(seconds=4)):
        await bucket.acquire()

    assert ticker.calls == 0


async def test_the_rate_is_the_configured_one():
    """`AI_PROVIDER_RPM`. A limiter hard-coded to one provider's limit would be
    wrong the moment a second provider is configured (`AI-02`)."""
    ticker = Ticker()
    start = clock.now()

    # Constructed inside the frozen window - see the module docstring.
    with clock.freeze(start):
        bucket = TokenBucket(60, sleep=ticker, burst=1)
        for _ in range(10):
            await bucket.acquire()

    # 60/min is one per second.
    assert ticker.total == pytest.approx(9.0, rel=0.01)


def test_a_rate_of_zero_is_refused():
    """A limit of zero would queue every call for ever, which is an outage
    written as a configuration value."""
    with pytest.raises(ValueError, match="forever"):
        TokenBucket(0)


# -- concurrency -------------------------------------------------------------


async def test_concurrent_callers_share_one_bucket():
    """The worker runs enrichments concurrently. A bucket that was not
    serialised would let N coroutines each see the same token and all take it,
    which is the exact burst the provider is throttling."""
    ticker = Ticker()
    start = clock.now()

    # Constructed inside the frozen window - see the module docstring.
    with clock.freeze(start):
        bucket = TokenBucket(15, sleep=ticker, burst=1)
        await asyncio.gather(*(bucket.acquire() for _ in range(10)))

    # Nine of the ten had to wait, whatever order they arrived in.
    assert ticker.calls == 9


async def test_the_limiter_is_not_a_cost_cap():
    """§3.1: "Rate limits are separate from cost caps."

    Different questions, different answers: too expensive degrades the feature
    per §3.2; too fast waits. Conflating them would either make a slow provider
    look like an exhausted budget, or let a runaway spend at the provider's full
    rate.
    """
    bucket = TokenBucket(15, sleep=Ticker())

    assert not hasattr(bucket, "cap")
    assert not hasattr(bucket, "spend")
    assert bucket.per_minute == 15


async def test_waiting_is_observable():
    """An operator seeing enrichment fall behind needs to know whether it is the
    provider's limit or something else. A limiter that waited silently would
    make those two look identical."""
    ticker = Ticker()
    start = clock.now()

    # Constructed inside the frozen window - see the module docstring.
    with clock.freeze(start):
        bucket = TokenBucket(15, sleep=ticker, burst=1)
        for _ in range(5):
            await bucket.acquire()

    assert bucket.waits == 4
    assert bucket.waited_seconds > 0
