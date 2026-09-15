from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

ScoredList = Sequence[tuple[str, float]]


@dataclass(frozen=True, slots=True)
class FusedHit:
    """One record of a fused result list, with where each retrieval leg ranked it.

    ``lexical_rank`` and ``semantic_rank`` are 1-based, and ``None`` when that
    leg did not return the record. A record found only by the semantic leg has
    no snippet and no highlights, so a UI shows its abstract instead, read with
    the text store's ``get_documents``. ``score``
    comes from the fusion strategy and is comparable only within one result
    list; render the rank, never the score as a percentage.
    """

    record_id: str
    score: float
    lexical_rank: int | None = None
    semantic_rank: int | None = None
    snippet: str = ""
    highlights: tuple[tuple[int, int], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    title: str = ""


@dataclass(frozen=True, slots=True)
class FusionParams:
    """How ranked lists are fused.

    ``k`` damps reciprocal rank fusion: a larger ``k`` flattens the difference
    between neighbouring ranks. ``weights`` holds one weight per fused list, in
    list order, and ``None`` weighs every list equally. A list of weights is
    stored as a tuple.

    Raises:
        ValueError: ``k`` is less than 1, or a weight is negative or not finite.
    """

    k: int = 60
    weights: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        if self.k < 1:
            raise ValueError(f"k must be at least 1, not {self.k!r}")
        if self.weights is not None:
            object.__setattr__(self, "weights", tuple(self.weights))
            for weight in self.weights:
                if not math.isfinite(weight) or weight < 0:
                    raise ValueError(f"Fusion weights must be finite and not negative, not {weight!r}")


class FusionStrategy(Protocol):
    """Fuses ranked lists of ``(record_id, score)`` pairs into one ranking.

    The result holds each record of the input lists once, as a
    ``(record_id, fused_score)`` pair, best first.
    """

    def __call__(self, ranked_lists: Sequence[ScoredList], params: FusionParams) -> list[tuple[str, float]]:
        """Return the fused ranking of ``ranked_lists``, best first."""


def reciprocal_rank_fusion(
    ranked_lists: Sequence[ScoredList], params: FusionParams | None = None
) -> list[tuple[str, float]]:
    """Fuse ranked lists by ``1 / (k + rank)``, the rank-only fusion of Cormack et al.

    Only the order of each list is read; its scores are ignored. That makes the
    fusion scale-free. BM25 scores are unbounded and depend on the corpus, while
    cosine similarity lies in [-1, 1], so any weighted sum of the two would make
    the effective blend drift as the corpus grows; RRF needs no calibration.

    A record's rank in a list is its 1-based position among the list's distinct
    records, so a repeated record counts once, at its first position. Its fused
    score is the sum over lists of ``weight / (k + rank)``, rounded exactly, so
    the result does not depend on the order of the lists. The result is best
    first, and equal fused scores are ordered by ``record_id``.

    Raises:
        ValueError: ``params.weights`` does not hold one weight per list.
    """
    active = FusionParams() if params is None else params
    contributions: dict[str, list[float]] = {}
    for ranked, weight in zip(ranked_lists, _weights(ranked_lists, active), strict=True):
        for rank, record_id in enumerate(dict.fromkeys(record_id for record_id, _score in ranked), start=1):
            contributions.setdefault(record_id, []).append(weight / (active.k + rank))
    return _best_first(contributions)


def normalized_score_fusion(
    ranked_lists: Sequence[ScoredList], params: FusionParams | None = None
) -> list[tuple[str, float]]:
    """Fuse ranked lists by min-max normalizing each list's scores, then adding them with weights.

    Unlike :func:`reciprocal_rank_fusion`, score mass matters: a record far
    ahead of the next one keeps that lead. The price is calibration. Raw BM25
    scores depend on the corpus, so how much the lexical list counts drifts as
    the corpus changes. ``params.k`` is not used.

    Within a list, the best score becomes 1 and the worst 0, and a list whose
    scores are all equal gives every record 1. A repeated record keeps the
    score of its first occurrence. The result is best first, and equal fused
    scores are ordered by ``record_id``.

    Raises:
        ValueError: ``params.weights`` does not hold one weight per list, or a
            score is not finite.
    """
    active = FusionParams() if params is None else params
    contributions: dict[str, list[float]] = {}
    for ranked, weight in zip(ranked_lists, _weights(ranked_lists, active), strict=True):
        scores: dict[str, float] = {}
        for record_id, score in ranked:
            if not math.isfinite(score):
                raise ValueError(f"The score of {record_id!r} is not finite: {score!r}")
            scores.setdefault(record_id, score)
        if scores:
            low, high = min(scores.values()), max(scores.values())
            for record_id, score in scores.items():
                normalized = (score - low) / (high - low) if high > low else 1.0
                contributions.setdefault(record_id, []).append(weight * normalized)
    return _best_first(contributions)


def _weights(ranked_lists: Sequence[ScoredList], params: FusionParams) -> tuple[float, ...]:
    if params.weights is None:
        return (1.0,) * len(ranked_lists)
    if len(params.weights) != len(ranked_lists):
        raise ValueError(
            f"Expected {len(ranked_lists)} fusion weights, one per ranked list, not {len(params.weights)}"
        )
    return params.weights


def _best_first(contributions: dict[str, list[float]]) -> list[tuple[str, float]]:
    fused = [(record_id, math.fsum(parts)) for record_id, parts in contributions.items()]
    fused.sort(key=lambda item: (-item[1], item[0]))
    return fused
