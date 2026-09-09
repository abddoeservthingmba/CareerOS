"""The Redis client - `FOUND-01`, `FOUND-10`, `AUTH-09`.

`01-foundations.md` §1 names `infra/redis.py` in the layout and §4 says what it
is allowed to be: "`infra` is dumb. It knows how to open a connection and
nothing about what the collections mean." So this module opens a connection and
answers whether it is alive. The token bucket lives in `core/ratelimit.py` and
the idempotency claim in `core/idempotency.py`; neither constructs its own
client, because §2 forbids a module reading the environment.

Two settings are deliberate.

* **`decode_responses=False`.** The bytes-or-str question is answered once, at
  the consumer: `idempotency._text` already normalises both. Turning decoding
  on here would change the type that `RedisStore` has been tested against
  without changing the tests, which is the worst combination.
* **A connect *and* socket timeout.** The default is no timeout at all, and an
  auth route that fails closed on a Redis outage (`AC-AUTH-09.5`) only fails
  closed if the call actually returns. Without this, a black-holed connection
  hangs the request until the client gives up, which is a worse outage than the
  503 the criterion asks for.

`ARQ` does not use this module: it takes a `RedisSettings` DSN of its own in
`worker.py`, because the queue owns its connection pool and its retry policy.
"""

from __future__ import annotations

from typing import Any, cast

from redis.asyncio import Redis

#: Matched to `mongo.CONNECT_TIMEOUT_MS` so a container that cannot reach its
#: dependencies reports unready in a bounded, predictable time rather than in
#: whichever order the two libraries happen to give up.
CONNECT_TIMEOUT_SECONDS = 20.0


def build_client(url: str) -> Redis:
    # `from_url` is annotated as returning `Any` by redis-py, so the cast is
    # what tells mypy what this function actually hands back rather than
    # letting `Any` leak into every caller.
    client: Redis = cast(
        Redis,
        Redis.from_url(
            url,
            decode_responses=False,
            socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
            socket_timeout=CONNECT_TIMEOUT_SECONDS,
        ),
    )
    return client


async def ping(client: Any) -> bool:
    """Cheapest possible liveness check, for `/readyz`.

    Mirrors `mongo.ping`. Returns rather than raises so the readiness handler
    can report which dependency is down without an exception per check -
    `AC-OPS-01.3` wants a 503 that names the reason, not a 500.
    """
    return bool(await client.ping())
