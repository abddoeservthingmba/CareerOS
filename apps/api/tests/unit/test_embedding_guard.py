"""T-DATA-02.6 - a vector never travels without the model that made it.

`AC-DATA-02.6`: "`profiles.embedding` and every other embedding carry `model`
and `dims`; a comparison between vectors of differing `model` raises
`EmbeddingModelMismatch`."

**Why this is a raise and not a warning.** Cosine similarity between vectors
from two different models is not a less accurate number. It is a number with no
meaning at all, in the same range as a meaningful one, and it will usually land
somewhere plausible - around 0.3 to 0.6, which reads as "somewhat related". So a
cross-model comparison does not look like a bug. It looks like a mediocre match,
and the whole feed quietly fills up with them.

**When it actually happens.** Not through carelessness - through a migration.
`AI_EMBEDDING_MIGRATION` exists (`AC-AI-02.4`) precisely because re-embedding
50,000 jobs is not atomic: for however long it takes, the collection holds two
generations at once and every query compares across them. That is the window
this guard covers, and it is a window the product will be inside on purpose.

`dims` is asserted alongside `model` because two models can share a dimension
count - 768 is extremely common - so a length check would pass for exactly the
pairs most likely to be confused.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.documents import StoredEmbedding
from app.modules.apply.models import AnswerBankEntry
from app.modules.jobs.models import Job
from app.modules.profile.models import Profile
from app.shared.embedding import EmbeddingModelMismatch, cosine, quantize

MODEL = "gemini-embedding-001"
OTHER = "nomic-embed-text"

#: Every document §2 gives an embedding, with the field path. Parametrised so a
#: fourth one added later is either registered here or fails
#: `test_every_embedding_field_is_covered`.
EMBEDDING_FIELDS = (
    (Profile, "embedding"),
    (Job, "embedding"),
    (AnswerBankEntry, "embedding"),
)


# -- the criterion ------------------------------------------------------------


def test_comparing_across_models_raises():
    """AC-DATA-02.6, second clause."""
    left = quantize([0.1, 0.2, 0.3], MODEL)
    right = quantize([0.1, 0.2, 0.3], OTHER)

    with pytest.raises(EmbeddingModelMismatch):
        cosine(left, right)


def test_comparing_within_one_model_is_fine():
    """So the guard is not simply refusing everything."""
    left = quantize([0.1, 0.2, 0.3], MODEL)
    right = quantize([0.1, 0.2, 0.4], MODEL)

    assert 0.0 <= abs(cosine(left, right)) <= 1.0


def test_identical_vectors_from_the_same_model_are_similar():
    vector = quantize([0.5, 0.4, 0.3], MODEL)

    assert cosine(vector, vector) == pytest.approx(1.0, abs=1e-6)


def test_the_mismatch_message_names_both_models():
    """A raise reading "model mismatch" leaves the reader to find which two
    rows disagreed, across 50,000 documents mid-migration."""
    with pytest.raises(EmbeddingModelMismatch) as caught:
        cosine(quantize([0.1], MODEL), quantize([0.1], OTHER))

    message = str(caught.value)
    assert MODEL in message
    assert OTHER in message


def test_the_same_dimension_count_does_not_make_two_models_comparable():
    """The pairs most likely to be confused are the ones a length check
    accepts: 768 dimensions is the common default, so `len(a) == len(b)` is
    true for exactly the vectors that must not be compared."""
    left = quantize([0.1] * 768, MODEL)
    right = quantize([0.1] * 768, OTHER)

    assert left.dims == right.dims
    with pytest.raises(EmbeddingModelMismatch):
        cosine(left, right)


# -- every stored embedding carries the pair ----------------------------------


@pytest.mark.parametrize(
    ("document", "field"), EMBEDDING_FIELDS, ids=[d.__name__ for d, _ in EMBEDDING_FIELDS]
)
def test_every_embedding_field_uses_the_shared_shape(document, field: str):
    """`AC-DATA-02.6`, first clause - and via one type, so it cannot be true of
    two collections and false of the third."""
    annotation = document.model_fields[field].annotation

    assert StoredEmbedding in getattr(annotation, "__args__", (annotation,))


def test_a_stored_embedding_without_a_model_is_refused():
    """The field is required, and blank is refused too: an empty string would
    satisfy a `str` annotation and defeat every comparison guard downstream."""
    with pytest.raises(ValueError, match="must carry the model"):
        StoredEmbedding(model="   ", dims=768)

    with pytest.raises(ValueError):
        StoredEmbedding(dims=768)  # type: ignore[call-arg]


def test_a_stored_embedding_without_dims_is_refused():
    with pytest.raises(ValueError):
        StoredEmbedding(model=MODEL)  # type: ignore[call-arg]


@pytest.mark.parametrize("dims", [0, -1])
def test_non_positive_dims_are_refused(dims: int):
    with pytest.raises(ValueError, match="dims must be positive"):
        StoredEmbedding(model=MODEL, dims=dims)


def test_a_naive_computed_at_is_refused():
    """HR-10, on this field like every other. A naive timestamp here would make
    "which generation is newer" answerable only by luck of the deploy's zone."""
    with pytest.raises(ValueError):
        StoredEmbedding(model=MODEL, dims=3, computed_at=datetime(2026, 9, 8, 12, 0))  # noqa: DTZ001


def test_an_aware_computed_at_is_kept():
    moment = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)

    stored = StoredEmbedding(model=MODEL, dims=3, computed_at=moment)

    assert stored.computed_at == moment


# -- round-tripping, which is what makes the stored `model` load-bearing ------


def test_a_vector_round_trips_through_the_stored_shape():
    """Storing and reloading must not lose the model, or the guard above
    protects only vectors that never went to the database - which is none of
    them."""
    original = quantize([0.1, 0.2, 0.3], MODEL)

    stored = StoredEmbedding.from_vector(original, source_hash="abc")
    reloaded = stored.to_vector()

    assert reloaded == original
    assert stored.model == MODEL
    assert stored.dims == original.dims
    assert stored.source_hash == "abc"
    assert stored.computed_at is not None


def test_a_reloaded_vector_still_refuses_a_cross_model_comparison():
    """The whole point, end to end: through the document shape, not only
    between two freshly-quantized vectors."""
    ours = StoredEmbedding.from_vector(quantize([0.1, 0.2, 0.3], MODEL)).to_vector()
    theirs = StoredEmbedding.from_vector(quantize([0.1, 0.2, 0.3], OTHER)).to_vector()

    with pytest.raises(EmbeddingModelMismatch):
        cosine(ours, theirs)


def test_an_uncomputed_embedding_refuses_to_become_a_vector():
    """A document exists before its embedding does, and `vector` is empty until
    the task runs. Returning a zero vector instead would score every
    un-embedded job as equally similar to everything."""
    stored = StoredEmbedding(model=MODEL, dims=768)

    assert not stored.is_computed
    with pytest.raises(ValueError, match="not been computed"):
        stored.to_vector()


# -- the documents themselves -------------------------------------------------


@pytest.mark.parametrize(
    ("document", "field"), EMBEDDING_FIELDS, ids=[d.__name__ for d, _ in EMBEDDING_FIELDS]
)
def test_the_embedding_field_is_optional_and_defaults_to_absent(document, field: str):
    """A document exists before its embedding does.

    A required embedding would mean a job could not be stored until its vector
    was computed, which puts an AI call on the ingestion write path - and
    ingestion writes hundreds of rows per run under a budget cap.

    Asserted on the field rather than on an instance because a Beanie
    `Document` cannot be constructed before `init_beanie` has run
    (`CollectionWasNotInitialized`); that is why `core/documents.py` splits
    `DocumentFields` out in the first place. The instantiated path is covered
    by the integration suites.
    """
    model_field = document.model_fields[field]

    assert not model_field.is_required()
    assert model_field.get_default() is None


def test_every_embedding_field_is_covered():
    """A fourth collection given an embedding must appear in `EMBEDDING_FIELDS`.

    Discovered rather than trusted: the criterion says "and every other
    embedding", so a check over a hand-listed three would be exactly wrong about
    the fourth.
    """
    from app.documents import all_documents

    found = {
        (document, name)
        for document in all_documents()
        for name, field in document.model_fields.items()
        if StoredEmbedding in getattr(field.annotation, "__args__", (field.annotation,))
    }

    uncovered = sorted((d.__name__, f) for d, f in found - set(EMBEDDING_FIELDS))
    assert found == set(EMBEDDING_FIELDS), f"uncovered embedding field(s): {uncovered}"
