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


def _to_unit_rows(array: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Scale each row along the last axis to unit length at any magnitude.

    Returns the scaled array and a mask of degenerate rows — all zero, or
    holding a non-finite value — which are returned unchanged. A plain norm
    squares every component first, so a component near ``1e-161`` rounds in
    the subnormal range (skewing the norm by a few tenths of a percent) and
    one near ``1e155`` overflows. Each row is therefore divided by its largest
    magnitude before the norm is taken, and the absolute norm is never rebuilt,
    since multiplying back would round again for subnormal components.
    """
    scale = np.max(np.abs(array), axis=-1, keepdims=True)
    degenerate = (scale == 0.0) | ~np.isfinite(scale)
    scaled = array / np.where(degenerate, 1.0, scale)
    norms = np.linalg.norm(scaled, axis=-1, keepdims=True)
    unit = scaled / np.where(degenerate, 1.0, norms)
    return np.where(degenerate, array, unit), degenerate


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    """Scale each row to unit length, leaving degenerate rows untouched.

    A row that is all zero or holds a non-finite value is passed through
    unchanged: there is no meaningful direction to scale it to, and dividing
    would replace the row with zeros or NaNs that would later read as a
    spurious score.
    """
    if matrix.size == 0:
        return matrix
    return _to_unit_rows(matrix)[0]


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
    unit, degenerate = _to_unit_rows(np.asarray(query, dtype=np.float64))
    if degenerate.any():
        return -1.0
    similarities = normalized_references @ unit
    best = float(similarities.max())
    return best if np.isfinite(best) else -1.0
