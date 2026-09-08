"""Embedding storage and comparison - `DATA-06`, and `AI-01`'s `Vector`.

`17-data-model.md` §6: at 768 float32 dimensions an embedding is ~3 KB, and
50,000 jobs plus 100,000 scores do not fit in Atlas M0's 512 MB. The first and
largest of the three mitigations: "**Embeddings are stored quantized.** `int8`
with a stored scale factor: 768 bytes instead of 3 KB, cosine similarity error
under 1% - irrelevant at the precision the score uses. Saves ~110 MB on jobs."

`18-dependency-closure.md` §5.2 (violation V2) puts this codec in **P0** rather
than P4: `PROF-01` stores `profiles.embedding` in P2, and storing float32 then
quantizing later would be a migration over every profile and job for no reason.

`05-ai-layer.md` §1: "Vectors carry their model: `Vector = tuple[str, int,
bytes]` - `(model, dims, quantized)` ... or an equivalent frozen dataclass. A
bare `list[float]` never crosses the boundary, which is what makes
`EmbeddingModelMismatch` possible to enforce."

The quantization is symmetric per-vector: one scale, `max(abs(v)) / 127`, so the
largest component maps to ±127 and the error is bounded by half a step. Cosine
similarity is scale-invariant, which is why a per-vector scale costs nothing in
accuracy and why `AC-DATA-06.1`'s "<0.01" is comfortable rather than tight.
"""

from __future__ import annotations

import base64
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

INT8_MAX = 127


class EmbeddingModelMismatch(ValueError):
    """Two vectors from different models, or of different dimension, were compared.

    `05-ai-layer.md` §2: changing the embedding model is a migration, not a
    config flip. Comparing across models silently produces plausible nonsense,
    so it raises.
    """


class UnquantizedVector(TypeError):
    """A raw `list[float]` reached something that stores or compares vectors.

    `AC-DEP-05.4`: "No embedding is ever stored unquantized; a float32 vector
    reaching the persistence layer raises."
    """


@dataclass(frozen=True, slots=True)
class Vector:
    """A quantized embedding, carrying the model that produced it."""

    model: str
    dims: int
    scale: float
    data: bytes

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("a vector must carry the model that produced it")
        if self.dims <= 0:
            raise ValueError(f"dims must be positive, got {self.dims}")
        if len(self.data) != self.dims:
            raise ValueError(
                f"{self.model} declares {self.dims} dims but carries {len(self.data)} bytes"
            )
        if self.scale < 0 or math.isnan(self.scale) or math.isinf(self.scale):
            raise ValueError(f"scale must be finite and non-negative, got {self.scale}")

    @property
    def nbytes(self) -> int:
        return len(self.data)

    def to_document(self) -> dict[str, Any]:
        """The persisted shape (`17-data-model.md` §2.5, §2.6)."""
        return {
            "model": self.model,
            "dims": self.dims,
            "scale": self.scale,
            "vector": base64.b64encode(self.data).decode("ascii"),
        }

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> Vector:
        raw = document["vector"]
        data = base64.b64decode(raw) if isinstance(raw, str) else bytes(raw)
        return cls(
            model=str(document["model"]),
            dims=int(document["dims"]),
            scale=float(document["scale"]),
            data=data,
        )


def _as_signed(byte: int) -> int:
    return byte - 256 if byte > 127 else byte


def quantize(values: Sequence[float], model: str) -> Vector:
    """Compress a float embedding to one signed byte per dimension."""
    if not values:
        raise ValueError("cannot quantize an empty vector")
    largest = max(abs(float(v)) for v in values)
    if math.isnan(largest) or math.isinf(largest):
        raise ValueError("embedding contains a non-finite component")

    if largest == 0:
        # An all-zero embedding is degenerate but storable; a zero scale keeps
        # dequantize() exact and cosine() honest about it having no direction.
        return Vector(model=model, dims=len(values), scale=0.0, data=bytes(len(values)))

    scale = largest / INT8_MAX
    out = bytearray(len(values))
    for i, value in enumerate(values):
        step = int(round(float(value) / scale))
        step = max(-INT8_MAX, min(INT8_MAX, step))
        out[i] = step & 0xFF
    return Vector(model=model, dims=len(values), scale=scale, data=bytes(out))


def dequantize(vector: Vector) -> list[float]:
    """Recover the approximate float embedding. For diagnostics and tests."""
    return [_as_signed(b) * vector.scale for b in vector.data]


def cosine(left: Vector, right: Vector) -> float:
    """Cosine similarity, computed from the quantized form.

    Raises rather than comparing vectors from different models
    (`AC-MATCH-05.8`, `AC-DATA-02.6`). The per-vector scales cancel, so this is
    computed on the integer components directly - no dequantization, no
    floating-point accumulation over 768 terms.
    """
    if isinstance(left, list | tuple) or isinstance(right, list | tuple):
        raise UnquantizedVector(
            "cosine takes quantized Vectors; quantize() before storing or comparing"
        )
    if left.model != right.model:
        raise EmbeddingModelMismatch(
            f"{left.model} and {right.model} are different models; "
            "re-embed both sides before comparing (05-ai-layer.md §2)"
        )
    if left.dims != right.dims:
        raise EmbeddingModelMismatch(
            f"{left.model} vectors differ in dimension: {left.dims} and {right.dims}"
        )

    dot = 0
    left_square = 0
    right_square = 0
    for a_byte, b_byte in zip(left.data, right.data, strict=True):
        a = _as_signed(a_byte)
        b = _as_signed(b_byte)
        dot += a * b
        left_square += a * a
        right_square += b * b
    if left_square == 0 or right_square == 0:
        return 0.0
    return dot / math.sqrt(left_square * right_square)


def cosine_float(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine on raw floats - the reference `AC-DATA-06.1` measures against."""
    dot = sum(float(a) * float(b) for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(float(a) * float(a) for a in left))
    right_norm = math.sqrt(sum(float(b) * float(b) for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
