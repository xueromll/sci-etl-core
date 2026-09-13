from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np


def to_matrix(vectors: list[list[float]]) -> np.ndarray:
    """Stack embedding vectors into a 2-D float array.

    Returns an empty ``(0, 0)`` array when there is nothing to stack, so callers
    can treat "no references" uniformly without special-casing ``None``.
    """
    if not vectors:
        return np.empty((0, 0), dtype=np.float64)
    return np.asarray(vectors, dtype=np.float64)


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    """Scale each row to unit length, leaving degenerate rows untouched.

    A row whose norm is zero or non-finite is passed through unchanged: there
    is no meaningful direction to scale it to, and dividing would replace the
    row with zeros or NaNs that would later read as a spurious score.
    """
    if matrix.size == 0:
        return matrix
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[(norms == 0.0) | ~np.isfinite(norms)] = 1.0
    return matrix / norms


def unit_vector(vector: Sequence[float], dtype: Any = np.float32) -> np.ndarray:
    """Return ``vector`` scaled to unit length, leaving a zero vector untouched.

    The norm is computed in float64 even when ``dtype`` is narrower. Squaring
    happens inside the norm, so in the default float32 a component around
    ``1e20`` overflows to infinity and a component around ``1e-30`` underflows
    to zero -- either one would silently yield an unusable vector rather than a
    unit one. Widening for the measurement keeps both ends of the range exact.
    """
    array = np.asarray(vector, dtype=dtype)
    if array.size == 0:
        return array
    widened = array.astype(np.float64)
    norm = float(np.linalg.norm(widened))
    if norm == 0.0 or not np.isfinite(norm):
        return array
    return (widened / norm).astype(dtype)


def top_similarity(query: list[float], normalized_references: np.ndarray) -> float:
    """Cosine similarity of ``query`` to its nearest reference row.

    ``normalized_references`` is expected to be unit-normalized already. Returns
    ``-1.0`` (the lowest possible cosine value) when there is nothing to compare
    against, so an empty or degenerate input never reads as a match.
    """
    if normalized_references.size == 0 or not query:
        return -1.0
    vector = np.asarray(query, dtype=np.float64)
    norm = float(np.linalg.norm(vector))
    if norm == 0.0 or not np.isfinite(norm):
        return -1.0
    similarities = normalized_references @ (vector / norm)
    best = float(similarities.max())
    return best if np.isfinite(best) else -1.0
