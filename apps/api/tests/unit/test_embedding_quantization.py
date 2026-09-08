"""T-DATA-06.1 - the embedding quantization codec (`17-data-model.md` §6).

Shared with `T-DEP-05.4`, which asserts no embedding is ever stored unquantized.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.shared.embedding import (
    EmbeddingModelMismatch,
    UnquantizedVector,
    Vector,
    cosine,
    cosine_float,
    dequantize,
    quantize,
)

MODEL = "text-embedding-004"
DIMS = 768

component = st.floats(
    min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False, width=32
)


def _has_direction(values: list[float]) -> bool:
    return max(abs(x) for x in values) > 1e-3


# The properties below hold at any dimension, so they are generated small:
# hypothesis cannot shrink a 768-element base example usefully. The `DIMS`-sized
# case is covered by the deterministic tolerance test. Both vectors in a pair
# share a dimension, because comparing across dimensions is the separate
# criterion asserted by `test_comparing_different_dimensions_raises`.
@st.composite
def vector_pair(draw) -> tuple[list[float], list[float]]:
    size = draw(st.integers(min_value=8, max_value=64))
    values = st.lists(component, min_size=size, max_size=size).filter(_has_direction)
    return draw(values), draw(values)


def test_one_byte_per_dimension():
    """§6 - "768 bytes instead of 3 KB"."""
    values = [0.5] * DIMS
    quantized = quantize(values, MODEL)
    assert quantized.nbytes == DIMS
    assert quantized.dims == DIMS
    assert quantized.model == MODEL
    # float32 would be four times the size; that difference is ~110 MB on jobs.
    assert quantized.nbytes * 4 == DIMS * 4


@settings(max_examples=250, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(pair=vector_pair())
def test_cosine_is_a_similarity_whatever_the_input(pair):
    """Properties that hold for every input, adversarial ones included.

    The <0.01 tolerance in `AC-DATA-06.1` is asserted separately, over random
    vectors, because it is a claim about *embeddings* rather than about
    arbitrary float lists. A symmetric per-vector scale is set by the largest
    component, so a vector like `[1.0, 1e-9, 1e-9, ...]` quantizes every other
    component to zero and the similarity moves a long way. Real embeddings are
    roughly isotropic and have no such dynamic range - but the codec's
    guarantee is worth stating precisely rather than implying it is universal.
    """
    left, right = pair
    quantized = cosine(quantize(left, MODEL), quantize(right, MODEL))
    assert -1.0000001 <= quantized <= 1.0000001
    # Symmetric, and self-similarity is exactly one.
    assert quantized == pytest.approx(
        cosine(quantize(right, MODEL), quantize(left, MODEL)), abs=1e-12
    )
    assert cosine(quantize(left, MODEL), quantize(left, MODEL)) == pytest.approx(1.0, abs=1e-9)
    # The sign of the relationship survives quantization whenever the exact
    # similarity is not already near zero.
    exact = cosine_float(left, right)
    if abs(exact) > 0.05:
        assert (quantized > 0) == (exact > 0)


def test_a_thousand_pairs_stay_within_tolerance():
    """The criterion's own number, run deterministically as a regression."""
    import random

    rng = random.Random(20260906)
    worst = 0.0
    for _ in range(1000):
        left = [rng.uniform(-1, 1) for _ in range(DIMS)]
        right = [rng.uniform(-1, 1) for _ in range(DIMS)]
        error = abs(
            cosine_float(left, right) - cosine(quantize(left, MODEL), quantize(right, MODEL))
        )
        worst = max(worst, error)
    assert worst < 0.01, f"worst error over 1,000 pairs was {worst}"


def test_identical_vectors_have_similarity_one():
    values = [0.1 * i for i in range(DIMS)]
    quantized = quantize(values, MODEL)
    assert cosine(quantized, quantized) == pytest.approx(1.0, abs=1e-9)


def test_opposite_vectors_have_similarity_minus_one():
    values = [0.1 * (i + 1) for i in range(DIMS)]
    negated = [-v for v in values]
    assert cosine(quantize(values, MODEL), quantize(negated, MODEL)) == pytest.approx(
        -1.0, abs=1e-9
    )


def test_dequantize_recovers_the_scale():
    values = [1.0, -1.0, 0.5, 0.0]
    recovered = dequantize(quantize(values, MODEL))
    for original, back in zip(values, recovered, strict=True):
        assert abs(original - back) < 0.01


def test_comparing_across_models_raises():
    """AC-MATCH-05.8 / AC-DATA-02.6 - a mismatched embedding model raises rather
    than silently comparing incompatible vectors."""
    values = [0.5] * DIMS
    with pytest.raises(EmbeddingModelMismatch, match="different models"):
        cosine(quantize(values, MODEL), quantize(values, "some-other-model"))


def test_comparing_different_dimensions_raises():
    with pytest.raises(EmbeddingModelMismatch, match="dimension"):
        cosine(quantize([0.5] * 8, MODEL), quantize([0.5] * 16, MODEL))


def test_a_raw_float_list_cannot_be_compared():
    """AC-DEP-05.4 - a float32 vector reaching the layer raises."""
    quantized = quantize([0.5] * 8, MODEL)
    with pytest.raises(UnquantizedVector):
        cosine([0.5] * 8, quantized)  # type: ignore[arg-type]
    with pytest.raises(UnquantizedVector):
        cosine(quantized, [0.5] * 8)  # type: ignore[arg-type]


def test_a_vector_must_carry_its_model():
    with pytest.raises(ValueError, match="model"):
        Vector(model="", dims=1, scale=1.0, data=b"\x01")


def test_declared_dimension_must_match_the_payload():
    with pytest.raises(ValueError, match="dims|carries"):
        Vector(model=MODEL, dims=4, scale=1.0, data=b"\x01\x02")


def test_document_round_trip():
    """The persisted shape in `17-data-model.md` §2.5 / §2.6."""
    original = quantize([0.25, -0.5, 1.0], MODEL)
    restored = Vector.from_document(original.to_document())
    assert restored == original
    assert cosine(restored, original) == pytest.approx(1.0, abs=1e-9)


def test_an_all_zero_embedding_is_storable_and_has_no_direction():
    zero = quantize([0.0] * DIMS, MODEL)
    assert zero.scale == 0.0
    assert cosine(zero, quantize([0.5] * DIMS, MODEL)) == 0.0


def test_a_non_finite_component_is_refused():
    with pytest.raises(ValueError, match="non-finite"):
        quantize([0.5, math.inf], MODEL)


def test_an_empty_vector_is_refused():
    with pytest.raises(ValueError, match="empty"):
        quantize([], MODEL)
