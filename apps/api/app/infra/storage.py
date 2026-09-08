"""The object store - `DATA-04`.

`17-data-model.md` §4. Cloudflare R2 in every environment; MinIO in the
integration environment, which speaks the same S3 API.

Four constraints from §4 shape this module, and each one is a decision that is
easy to reverse by accident:

**Uploads are streamed.** "the API never buffers a whole file in memory."
`put_stream` takes an async iterator of chunks and never joins them.
`AC-DATA-04.3` puts a number on it - a 5 MB upload peaks under 32 MB of RSS
growth - which is only achievable if nothing in the path calls `.read()` on the
whole body. The signature is the enforcement: there is no `bytes` parameter to
pass a whole file to.

**Every read is a presigned GET with a 5-minute TTL, issued only after an
ownership check.** `presign_get` takes a `user_id` and refuses a key that does
not belong to it. Not "the caller should check first": the check is inside the
signer, because a signer that trusted its caller is one endpoint away from being
an open bucket.

**Ownership failures answer 404, not 403** (`02` §6, `01-foundations.md`). A 403
confirms the object exists, which tells an attacker enumerating ULIDs that they
found a real one. `NotFound` is the only thing raised.

**Deletion is a prefix sweep, verified by re-listing.** `delete_prefix` returns
what it deleted and `AC-DATA-04.5` requires a re-list to return zero objects
*including noncurrent versions* - because versioning is on, and a delete on a
versioned bucket writes a delete marker rather than removing anything.

The protocol has an in-memory implementation (`MemoryStore`) so every assertion
about ownership, key shape, streaming and sweeping can run without a bucket -
which matters here because this machine has no Docker, so MinIO exists only in
CI. The MinIO variants are marked and run there.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol, runtime_checkable
from urllib.parse import quote, urlencode

from app.core import clock
from app.shared.object_keys import PRESIGNED_TTL_SECONDS, is_valid, owner_of, user_prefix

#: The chunk size `put_stream` reads. 1 MiB: large enough that a 5 MB upload is
#: five round trips rather than five thousand, small enough that five concurrent
#: uploads are 5 MiB of buffers rather than 25 MB.
CHUNK_BYTES = 1024 * 1024


class StorageError(Exception):
    """Anything the object store refuses. Never a provider exception type."""


class NotFound(StorageError):
    """The object does not exist, or does not belong to the caller.

    **One exception for both**, deliberately. `01-foundations.md`: ownership
    failures answer 404, not 403. Two exception types would mean two response
    codes, and the 403 would confirm that a ULID an attacker guessed names a
    real object.
    """


class KeyNotAllowed(StorageError):
    """A key that `object_keys` would not have produced.

    Checked here as well as at construction, because a key can also arrive from
    the database - and a row written before a validation rule tightened is
    exactly the row that would slip past a check that only ran on new uploads.
    """


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size_bytes: int
    content_type: str
    #: Set when versioning is on, which §4 requires. `None` from a store that
    #: does not version - the memory one, and MinIO unless configured.
    version_id: str | None = None


@runtime_checkable
class ObjectStore(Protocol):
    """What the product needs from an object store, and nothing more.

    No `get_bytes`, and that is the point: a method that returned a whole
    object's bytes would be the one somebody used for a résumé, and HR-8 keeps
    file bytes inside our infrastructure by making the download a presigned URL
    the browser fetches directly.
    """

    async def put_stream(
        self,
        key: str,
        chunks: AsyncIterator[bytes],
        *,
        content_type: str,
    ) -> StoredObject: ...

    async def head(self, key: str) -> StoredObject | None: ...

    async def presign_get(self, key: str, *, user_id: str, filename: str | None = None) -> str: ...

    async def list_prefix(self, prefix: str, *, include_versions: bool = False) -> list[str]: ...

    async def delete_prefix(self, prefix: str) -> list[str]: ...


def check_key(key: str) -> str:
    if not is_valid(key):
        from app.shared.object_keys import rejection_reason

        raise KeyNotAllowed(f"{key!r} {rejection_reason(key)}")
    return key


def sanitize_filename(name: str) -> str:
    """§4: the user's filename appears "only in the `Content-Disposition` of a
    presigned download, sanitized".

    A header value, not a path. Two things it must not contain: a newline or a
    `"`, either of which ends the header and starts an attacker-chosen one -
    header injection through a filename is the oldest trick there is - and a
    path separator, which some clients will honour when saving.
    """
    cleaned = "".join(
        character for character in name if character.isprintable() and character not in '"\\/\r\n\t'
    ).strip()
    return cleaned[:200] or "download"


def content_disposition(filename: str | None) -> str | None:
    """RFC 6266, with both forms.

    `filename*` carries UTF-8 percent-encoded so an accented name survives;
    plain `filename` is the ASCII fallback for clients that ignore the first.
    Sending only the plain form turns `Ingénieur.pdf` into mojibake in the save
    dialog; sending only the extended form loses the name on old clients.
    """
    if filename is None:
        return None
    safe = sanitize_filename(filename)
    ascii_fallback = safe.encode("ascii", "replace").decode("ascii")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(safe)}"


# -- the in-memory implementation ---------------------------------------------


@dataclass
class _Version:
    data: bytes
    content_type: str
    version_id: str
    current: bool = True


@dataclass
class MemoryStore:
    """An `ObjectStore` with no network, for tests and local development.

    **Versioned**, because §4 requires versioning on and `AC-DATA-04.5` is
    specifically about noncurrent versions. A memory store that kept one copy
    per key would let the deletion-sweep test pass while the real bucket
    retained every previous upload for thirty days - which is the failure the
    criterion exists to catch.
    """

    secret: str = "memory"
    objects: dict[str, list[_Version]] = field(default_factory=dict)
    #: Every `presign_get` issued, so a test can assert the TTL and the
    #: ownership check without parsing a URL.
    signed: list[tuple[str, str, datetime]] = field(default_factory=list)
    #: Peak bytes held at once, for `AC-DATA-04.3`'s memory assertion.
    peak_chunk_bytes: int = 0

    async def put_stream(
        self, key: str, chunks: AsyncIterator[bytes], *, content_type: str
    ) -> StoredObject:
        check_key(key)
        pieces: list[bytes] = []
        total = 0
        async for chunk in chunks:
            # A real store forwards each chunk to the network and keeps none.
            # Here they are kept, because a test has to read the object back -
            # but the *peak single chunk* is recorded so a caller that joined
            # the body before calling is visible.
            self.peak_chunk_bytes = max(self.peak_chunk_bytes, len(chunk))
            pieces.append(chunk)
            total += len(chunk)

        versions = self.objects.setdefault(key, [])
        for version in versions:
            version.current = False
        version_id = hashlib.sha256(f"{key}:{len(versions)}".encode()).hexdigest()[:16]
        versions.append(
            _Version(data=b"".join(pieces), content_type=content_type, version_id=version_id)
        )
        return StoredObject(
            key=key, size_bytes=total, content_type=content_type, version_id=version_id
        )

    async def head(self, key: str) -> StoredObject | None:
        versions = [v for v in self.objects.get(key, []) if v.current]
        if not versions:
            return None
        version = versions[-1]
        return StoredObject(
            key=key,
            size_bytes=len(version.data),
            content_type=version.content_type,
            version_id=version.version_id,
        )

    async def presign_get(self, key: str, *, user_id: str, filename: str | None = None) -> str:
        check_key(key)
        # `AC-DATA-04.2`: ownership checked before signing, 404 otherwise. The
        # order matters - checking ownership *after* confirming existence would
        # let a 404-vs-403 timing difference distinguish the two.
        if owner_of(key) != user_id:
            raise NotFound(f"{key} not found")
        if await self.head(key) is None:
            raise NotFound(f"{key} not found")

        expires = clock.now() + timedelta(seconds=PRESIGNED_TTL_SECONDS)
        self.signed.append((key, user_id, expires))
        query: dict[str, str] = {
            "X-Amz-Expires": str(PRESIGNED_TTL_SECONDS),
            "X-Amz-Date": expires.strftime("%Y%m%dT%H%M%SZ"),
        }
        disposition = content_disposition(filename)
        if disposition:
            query["response-content-disposition"] = disposition
        payload = f"{key}?{urlencode(sorted(query.items()))}"
        signature = hmac.new(self.secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return f"memory://{key}?{urlencode(sorted(query.items()))}&X-Amz-Signature={signature}"

    async def list_prefix(self, prefix: str, *, include_versions: bool = False) -> list[str]:
        found: list[str] = []
        for key, versions in self.objects.items():
            if not key.startswith(prefix):
                continue
            live = [v for v in versions if v.current or include_versions]
            found += [key] * len(live)
        return sorted(found)

    async def delete_prefix(self, prefix: str) -> list[str]:
        """`AUTH-07`'s sweep. Removes noncurrent versions too.

        A delete on a versioned bucket writes a delete marker and keeps the
        object, so a sweep that only issued deletes would leave every previous
        upload retrievable for thirty days - after telling the user their data
        was gone.
        """
        removed = [key for key in self.objects if key.startswith(prefix)]
        for key in removed:
            del self.objects[key]
        return sorted(removed)


def prefix_for(user_id: str) -> str:
    """What `AUTH-07` sweeps, from one place."""
    return user_prefix(user_id)


async def chunked(source: Iterable[bytes]) -> AsyncIterator[bytes]:
    """Adapt a synchronous iterable for `put_stream`, for tests and scripts."""
    for chunk in source:
        yield chunk


async def from_upload(read: Any, chunk_bytes: int = CHUNK_BYTES) -> AsyncIterator[bytes]:
    """A Starlette `UploadFile.read` as a chunk stream.

    Reads a bounded amount at a time and yields it, so nothing holds more than
    one chunk. `AC-DATA-04.3`'s ceiling is reachable only if every layer does
    this; the router calls it and never touches `await file.read()` with no
    argument, which reads the whole body.
    """
    while True:
        chunk = await read(chunk_bytes)
        if not chunk:
            return
        yield chunk


__all__ = [
    "CHUNK_BYTES",
    "KeyNotAllowed",
    "MemoryStore",
    "NotFound",
    "ObjectStore",
    "StorageError",
    "StoredObject",
    "check_key",
    "chunked",
    "content_disposition",
    "from_upload",
    "prefix_for",
    "sanitize_filename",
]
