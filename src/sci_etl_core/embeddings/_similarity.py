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
    """Scale each row to unit length, leaving zero-length rows untouched."""
    if matrix.size == 0:
        return matrix
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return matrix / norms


def unit_vector(vector: Sequence[float], dtype: Any = np.float32) -> np.ndarray:
    """Return ``vector`` scaled to unit length, leaving a zero vector untouched."""
    array = np.asarray(vector, dtype=dtype)
    if array.size == 0:
        return array
    norm = float(np.linalg.norm(array))
    if norm == 0.0:
        return array
    return array / norm


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
    if norm == 0.0:
        return -1.0
    similarities = normalized_references @ (vector / norm)
    return float(similarities.max())
