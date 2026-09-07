"""T-AI-03.5 - the same call twice contacts the provider once.

`AC-AI-03.5`: "A repeated identical `complete_json` within the TTL contacts the
provider once and writes two `ai_usage` rows, the second with `outcome:
cache_hit` and `est_cost_usd: 0`."

`05-ai-layer.md` §3.3: "Job enrichment and match rationale are the highest-value
cache targets: one enrichment serves every user who sees the job, which is the
economics that makes the feature affordable at all."

That sentence is the reason this exists. A job listing is enriched once and read
by everyone whose feed contains it; without a cache the same enrichment is paid
for once per viewer, and the feature's cost scales with users rather than with
listings. At a $2 daily cap that is the difference between working and not.

**Two rows, not one.** The cache hit still writes an `ai_usage` row, because
"this call happened and cost nothing" and "this call did not happen" are
different facts, and only the first one explains why a user got a result while
the spend counter did not move.

**The key is over canonicalized input** (§3.3): `sha256(provider | model |
prompt_version | canonicalized_input)`. Canonical, because two JSON encodings of
one object are one input - and a cache keyed on raw bytes would miss on every
re-serialisation, which is every process restart.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.ai.base import Feature
from app.ai.budget import ResponseCache, cache_key
from app.ai.usage import Outcome, UsageRecorder, build_row
from app.core import clock

PROVIDER = "gemini"
MODEL = "gemini-3.5-flash-lite"
VERSION = "job_enrich/v1"
PAYLOAD = {"title": "Backend Engineer", "text": "We are looking for..."}


class CountingProvider:
    def __init__(self) -> None:
        self.invocations = 0

    async def complete_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.invocations += 1
        return {"skills": ["python", "postgres"]}


async def enrich(
    cache: ResponseCache,
    provider: CountingProvider,
    recorder: UsageRecorder,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """The shape §3.3 prescribes: look, then call, then store, always record."""
    key = cache_key(PROVIDER, MODEL, VERSION, payload)

    cached: dict[str, Any] | None = await cache.get(key)
    if cached is not None:
        recorder.record(
            build_row(
                provider=PROVIDER,
                model=MODEL,
                feature=Feature.JOB_ENRICH,
                outcome=Outcome.CACHE_HIT,
                est_cost_usd=Decimal(0),
                prompt_version=VERSION,
            )
        )
        return cached

    result: dict[str, Any] = await provider.complete_json(payload)
    await cache.set(key, result)
    recorder.record(
        build_row(
            provider=PROVIDER,
            model=MODEL,
            feature=Feature.JOB_ENRICH,
            outcome=Outcome.OK,
            input_tokens=800,
            output_tokens=60,
            est_cost_usd=Decimal("0.000465"),
            prompt_version=VERSION,
        )
    )
    return result


# -- the criterion -----------------------------------------------------------


async def test_the_same_call_twice_contacts_the_provider_once():
    """AC-AI-03.5, first half."""
    cache, provider, recorder = ResponseCache(), CountingProvider(), UsageRecorder()

    first = await enrich(cache, provider, recorder, PAYLOAD)
    second = await enrich(cache, provider, recorder, PAYLOAD)

    assert provider.invocations == 1
    assert first == second


async def test_it_writes_two_rows_the_second_a_cache_hit():
    """AC-AI-03.5, second half.

    Two rows, because "this call happened and cost nothing" and "this call did
    not happen" are different facts - and only the first explains why a user got
    a result while the spend counter stayed still.
    """
    cache, provider, recorder = ResponseCache(), CountingProvider(), UsageRecorder()

    await enrich(cache, provider, recorder, PAYLOAD)
    await enrich(cache, provider, recorder, PAYLOAD)

    rows = recorder.drain()
    assert len(rows) == 2
    assert rows[0]["outcome"] is Outcome.OK
    assert rows[1]["outcome"] is Outcome.CACHE_HIT


async def test_the_cache_hit_row_records_zero_cost():
    """Zero, not null. A cache hit genuinely cost nothing, which is a different
    statement from "we do not know what it cost"."""
    cache, provider, recorder = ResponseCache(), CountingProvider(), UsageRecorder()

    await enrich(cache, provider, recorder, PAYLOAD)
    await enrich(cache, provider, recorder, PAYLOAD)

    assert recorder.drain()[1]["est_cost_usd"] == 0.0


async def test_a_different_input_is_a_different_call():
    """The control. A cache that returned the same answer for everything would
    satisfy every assertion above and enrich every job identically."""
    cache, provider, recorder = ResponseCache(), CountingProvider(), UsageRecorder()

    await enrich(cache, provider, recorder, PAYLOAD)
    await enrich(cache, provider, recorder, {**PAYLOAD, "title": "Frontend Engineer"})

    assert provider.invocations == 2


# -- the key -----------------------------------------------------------------


def test_the_key_is_over_canonicalized_input():
    """Two JSON encodings of one object are one input. A key over raw bytes
    would miss on every re-serialisation, which is every process restart."""
    reordered = {"text": PAYLOAD["text"], "title": PAYLOAD["title"]}

    assert cache_key(PROVIDER, MODEL, VERSION, PAYLOAD) == cache_key(
        PROVIDER, MODEL, VERSION, reordered
    )


@pytest.mark.parametrize(
    ("provider", "model", "version"),
    [
        ("openai", MODEL, VERSION),
        (PROVIDER, "gemini-3.8-flash", VERSION),
        (PROVIDER, MODEL, "job_enrich/v2"),
    ],
    ids=["provider", "model", "prompt_version"],
)
def test_each_part_of_the_key_changes_it(provider: str, model: str, version: str):
    """§3.3 names all four parts.

    The prompt version matters most: a rewritten prompt produces different
    output from the same input, and a cache that ignored it would serve v1's
    answers to v2 for a week.
    """
    assert cache_key(provider, model, version, PAYLOAD) != cache_key(
        PROVIDER, MODEL, VERSION, PAYLOAD
    )


def test_the_key_is_a_hash_not_the_input():
    """A key containing the prompt would put resume text in Redis' keyspace,
    which is visible to anything that can run `KEYS`."""
    key = cache_key(PROVIDER, MODEL, VERSION, {"resume": "Senior engineer at Acme"})

    assert "Senior engineer" not in key
    assert "Acme" not in key
    assert key.startswith("ai:cache:")
    assert len(key) == len("ai:cache:") + 64


# -- the TTL -----------------------------------------------------------------


async def test_an_entry_expires():
    """§3.3: TTL from `AI_CACHE_TTL_DAYS`, default 7. A cache with no expiry
    would keep serving an enrichment from a model that has since been
    replaced."""
    cache = ResponseCache(ttl=timedelta(days=7))
    start = clock.now()
    key = cache_key(PROVIDER, MODEL, VERSION, PAYLOAD)

    with clock.freeze(start):
        await cache.set(key, {"skills": ["python"]})

    with clock.freeze(start + timedelta(days=6, hours=23)):
        assert await cache.get(key) is not None

    with clock.freeze(start + timedelta(days=7, seconds=1)):
        assert await cache.get(key) is None


async def test_an_expired_entry_is_a_miss_not_an_error():
    """The caller re-calls the provider. An exception here would turn a cold
    cache into an outage."""
    cache = ResponseCache(ttl=timedelta(seconds=0))
    key = cache_key(PROVIDER, MODEL, VERSION, PAYLOAD)
    await cache.set(key, {"skills": []})

    assert await cache.get(key) is None
    assert cache.misses == 1


async def test_hits_and_misses_are_counted():
    """The cache's own hit rate is what tells you whether the economics are
    working - one enrichment per listing, or one per viewer."""
    cache = ResponseCache()
    key = cache_key(PROVIDER, MODEL, VERSION, PAYLOAD)

    assert await cache.get(key) is None
    await cache.set(key, {"skills": []})
    assert await cache.get(key) is not None

    assert (cache.hits, cache.misses) == (1, 1)


# -- against a real Redis ----------------------------------------------------


async def test_the_same_behaviour_against_redis():
    """§3.3 puts the cache in Redis. The in-process one is a stand-in, and a
    stand-in that behaved differently would make every test above a statement
    about the wrong thing."""
    from fakeredis import FakeAsyncRedis

    cache = ResponseCache(FakeAsyncRedis(), ttl=timedelta(days=7))
    provider, recorder = CountingProvider(), UsageRecorder()

    first = await enrich(cache, provider, recorder, PAYLOAD)
    second = await enrich(cache, provider, recorder, PAYLOAD)

    assert provider.invocations == 1
    assert first == second
    assert [row["outcome"] for row in recorder.drain()] == [Outcome.OK, Outcome.CACHE_HIT]


async def test_redis_entries_carry_a_ttl():
    """An entry with no expiry is a leak that shows up as a memory graph six
    months later."""
    from fakeredis import FakeAsyncRedis

    client = FakeAsyncRedis()
    cache = ResponseCache(client, ttl=timedelta(days=7))
    key = cache_key(PROVIDER, MODEL, VERSION, PAYLOAD)

    await cache.set(key, {"skills": []})

    remaining = await client.pttl(key)
    assert 0 < remaining <= timedelta(days=7).total_seconds() * 1000
