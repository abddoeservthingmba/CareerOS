"""T-DATA-04.3 - an upload is streamed, not buffered.

`AC-DATA-04.3`: "Uploading a 5 MB file peaks under 32 MB of API process RSS
growth."

`17-data-model.md` §4: "Uploads are streamed to R2; the API never buffers a
whole file in memory."

**Why 32 MB for a 5 MB file is a real ceiling and not a generous one.** A single
`await file.read()` costs 5 MB, and then the copy handed to the client library
costs another, and a base64 or multipart re-encoding on the way costs a third.
One user is fine. `AC-OPS-04.2`'s capacity target is concurrent users on a
container with a few hundred megabytes; ten simultaneous uploads at 3x buffering
is 150 MB of transient allocation, which on a small container is an OOM kill -
and an OOM kill takes out every other request in flight, so one user's upload
becomes everyone's outage.

**The ceiling is measured, and the shape is also asserted.** RSS is noisy: the
allocator does not return freed pages promptly, the garbage collector runs when
it chooses, and a 32 MB headroom on a process that starts at 90 MB is inside
the noise band on some platforms. So this file does both - it measures growth
*and* asserts that nothing in the path ever held more than one chunk, which is
the property the number is a proxy for. If the two ever disagree, the structural
assertion is the one to believe.

`tracemalloc` rather than `resource.getrusage`: it measures Python allocations
directly, it works on Windows (where this is developed and `getrusage` does not
exist), and it attributes a peak to the block being measured rather than to the
process's whole history.
"""

from __future__ import annotations

import tracemalloc
from collections.abc import AsyncIterator

import pytest

from app.core.ids import new_id
from app.infra.storage import CHUNK_BYTES, MemoryStore, from_upload
from app.shared.object_keys import resume_key

#: `AC-DATA-04.3`'s two numbers.
UPLOAD_BYTES = 5 * 1024 * 1024
CEILING_BYTES = 32 * 1024 * 1024

OWNER = new_id()


class FakeUpload:
    """A Starlette-shaped `UploadFile.read(size)`.

    Generates its chunks rather than holding the body, so the *fixture* cannot
    be what allocates 5 MB - which would make the measurement meaningless
    whatever the code under test did.
    """

    def __init__(self, total: int, chunk: int = 64 * 1024) -> None:
        self.total = total
        self.chunk = chunk
        self.served = 0
        self.largest_read = 0

    async def read(self, size: int = -1) -> bytes:
        if size == -1:
            # What a careless caller does. Recorded rather than refused, so
            # `test_reading_the_whole_body_is_visible` can prove the detector
            # would notice.
            self.largest_read = max(self.largest_read, self.total - self.served)
            remaining = self.total - self.served
            self.served = self.total
            return b"a" * remaining
        take = min(size, self.total - self.served, self.chunk)
        self.served += take
        self.largest_read = max(self.largest_read, take)
        return b"a" * take


class CountingStore(MemoryStore):
    """A store that discards each chunk after counting it.

    `chunk_count` is declared as a field rather than set ad hoc, so mypy sees
    it and a typo in the attribute name is an error rather than a second
    attribute nobody reads.

    `MemoryStore` keeps the bytes so a test can read the object back; that is
    the right trade for every other suite and the wrong one here, because
    keeping 5 MB is indistinguishable from buffering 5 MB. This one keeps only
    the totals.
    """

    async def put_stream(
        self, key: str, chunks: AsyncIterator[bytes], *, content_type: str
    ):
        from app.infra.storage import StoredObject, check_key

        check_key(key)
        total = 0
        largest = 0
        count = 0
        async for chunk in chunks:
            total += len(chunk)
            largest = max(largest, len(chunk))
            count += 1
        self.peak_chunk_bytes = largest
        self.chunk_count = count
        return StoredObject(key=key, size_bytes=total, content_type=content_type)


# -- the criterion ------------------------------------------------------------


async def test_a_five_megabyte_upload_stays_under_the_ceiling():
    """AC-DATA-04.3, measured.

    `tracemalloc` peaks over the block, so what is measured is the allocation
    the upload path caused rather than whatever the process was already holding.
    """
    store = CountingStore()
    upload = FakeUpload(UPLOAD_BYTES)
    key = resume_key(OWNER, new_id(), "pdf")

    tracemalloc.start()
    try:
        result = await store.put_stream(
            key, from_upload(upload.read), content_type="application/pdf"
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert result.size_bytes == UPLOAD_BYTES
    assert peak < CEILING_BYTES, (
        f"the upload path peaked at {peak / 1024 / 1024:.1f} MB for a "
        f"{UPLOAD_BYTES / 1024 / 1024:.0f} MB file, over the "
        f"{CEILING_BYTES / 1024 / 1024:.0f} MB ceiling. Ten concurrent uploads "
        "at this rate is an OOM kill, and an OOM kill takes out every request "
        "in flight."
    )


async def test_nothing_in_the_path_ever_holds_more_than_one_chunk():
    """The structural assertion the number is a proxy for.

    RSS and even `tracemalloc` are noisy - the allocator does not return freed
    pages promptly and the collector runs when it chooses. This does not
    measure; it asserts that the largest single buffer was one chunk, which is
    what "streamed" means. If this and the measurement above ever disagree,
    believe this one.
    """
    store = CountingStore()
    upload = FakeUpload(UPLOAD_BYTES)

    await store.put_stream(
        resume_key(OWNER, new_id(), "pdf"),
        from_upload(upload.read),
        content_type="application/pdf",
    )

    assert store.peak_chunk_bytes <= CHUNK_BYTES
    assert upload.largest_read <= CHUNK_BYTES
    assert store.chunk_count > 1, "the body arrived in one piece, which is not streaming"


async def test_the_stream_is_read_in_bounded_pieces():
    """`from_upload` passes a size to every `read`.

    `await file.read()` with no argument returns the whole body - it is one
    character shorter to write and it is the mistake this exists to prevent.
    """
    upload = FakeUpload(UPLOAD_BYTES)

    chunks = [chunk async for chunk in from_upload(upload.read)]

    assert len(chunks) == UPLOAD_BYTES // (64 * 1024)
    assert all(len(chunk) <= CHUNK_BYTES for chunk in chunks)
    assert sum(len(chunk) for chunk in chunks) == UPLOAD_BYTES


async def test_reading_the_whole_body_is_visible():
    """The negative control.

    Without it, both assertions above could be passing because `FakeUpload`
    never serves more than 64 KB whatever it is asked for - and then a real
    `UploadFile.read()` with no argument would sail through. This proves the
    fixture reports a whole-body read when one happens.
    """
    upload = FakeUpload(UPLOAD_BYTES)

    body = await upload.read()

    assert len(body) == UPLOAD_BYTES
    assert upload.largest_read == UPLOAD_BYTES


async def test_the_signature_offers_no_way_to_pass_a_whole_file():
    """The enforcement, and the reason it is a signature rather than a rule.

    `put_stream` takes an async iterator. There is no `bytes` parameter, so
    "upload this file" cannot be written as a single call with 5 MB in it -
    which is what a `put_object(key, data: bytes)` would invite.
    """
    import inspect

    from app.infra.storage import ObjectStore

    signature = inspect.signature(ObjectStore.put_stream)

    assert list(signature.parameters) == ["self", "key", "chunks", "content_type"]
    # `AsyncIterator[bytes]`, not `bytes`. Checked as the outer type rather
    # than by substring, because `bytes` appears inside the parameter of the
    # correct annotation too.
    chunks = str(signature.parameters["chunks"].annotation)
    assert chunks.startswith("AsyncIterator[")
    assert chunks != "bytes"


async def test_an_empty_upload_streams_zero_chunks():
    """A zero-byte file is a real upload - a truncated one, or a form submitted
    with no file - and the stream has to terminate rather than hang waiting for
    a first chunk that never comes."""
    store = CountingStore()
    upload = FakeUpload(0)

    result = await store.put_stream(
        resume_key(OWNER, new_id(), "pdf"), from_upload(upload.read), content_type="text/plain"
    )

    assert result.size_bytes == 0


def test_the_chunk_size_is_a_deliberate_number():
    """1 MiB.

    Large enough that a 5 MB upload is five round trips rather than five
    thousand; small enough that ten concurrent uploads are 10 MiB of buffers
    rather than 250. Both halves matter, so the number is a constant with a
    reason rather than a literal in a loop.
    """
    assert CHUNK_BYTES == 1024 * 1024
    assert CHUNK_BYTES < CEILING_BYTES // 8


@pytest.mark.parametrize("size", [1, 1023, CHUNK_BYTES - 1, CHUNK_BYTES, CHUNK_BYTES + 1])
async def test_a_body_around_the_chunk_boundary_is_complete(size: int):
    """Off-by-one at the chunk boundary loses or duplicates bytes, and a résumé
    missing its last kilobyte parses fine - it just has no final job."""
    store = CountingStore()
    upload = FakeUpload(size, chunk=CHUNK_BYTES)

    result = await store.put_stream(
        resume_key(OWNER, new_id(), "pdf"), from_upload(upload.read), content_type="text/plain"
    )

    assert result.size_bytes == size
