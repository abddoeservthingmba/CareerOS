"""The MongoDB client - `FOUND-01`, `DATA-01`.

`01-foundations.md` §4: `infra` is dumb. It knows how to open a connection and
nothing about what the collections mean.

Two settings are not optional and are the reason this is a module rather than
one line in the app factory:

* **`tz_aware=True`.** BSON stores a datetime as UTC milliseconds with no zone,
  so without this every timestamp read back is naive and HR-10's "every stored
  datetime is timezone-aware UTC" fails on the way *out*. The integration suite
  caught this the first time it ran against a real database.
* **`uuidRepresentation="standard"`**, so a UUID written by one driver version
  reads back the same from another.

Beanie 2.x uses PyMongo's native async driver; Motor is deprecated and
`init_beanie` will not accept a Motor database.
"""

from __future__ import annotations

from typing import Any

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

CONNECT_TIMEOUT_MS = 20_000


def build_client(uri: str) -> AsyncMongoClient[Any]:
    return AsyncMongoClient(
        uri,
        serverSelectionTimeoutMS=CONNECT_TIMEOUT_MS,
        uuidRepresentation="standard",
        tz_aware=True,
    )


async def ping(database: AsyncDatabase[Any]) -> bool:
    """Cheapest possible liveness check, for `/readyz`."""
    result = await database.command("ping")
    return bool(result.get("ok"))
