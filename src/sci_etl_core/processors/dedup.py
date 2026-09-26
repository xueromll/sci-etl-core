from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd

from sci_etl_core.processors.base import Processor


class NeighborMatcher(ABC):
    """Contract for finding near-duplicate rows that do not share a normalized key."""

    @abstractmethod
    def find_matches(self, frame: pd.DataFrame, threshold: float) -> list[tuple[int, int]]:
        """Return (keep_index, drop_index) pairs for rows considered duplicates."""


class DeduplicationStep(Processor):
    """Collapse rows sharing a normalized key, then merge matched neighbors.

    Rows with the same key become one row holding the first non-missing value
    of each column, ordered by key. Rows whose key is missing or empty carry no
    identity to match on, so each passes through as its own row, after the
    keyed rows, instead of being merged with every other keyless row.

    Matched pairs only fill the kept row's gaps. When a pair names a row that
    was already merged away as the one to keep, its values flow into the row
    that absorbed it, so a chain of matches never discards data.

    With ``source_column``, such as the ``record_id`` column an exporter
    writes, each output row gains ``sources_column``: the distinct non-empty
    ``source_column`` values of every input row merged into it, sorted and
    joined with ``"; "``. The column says which papers a merged row came from,
    though each value in the row is still the first one found.
    """

    def __init__(
        self,
        norm_key_column: str,
        matcher: NeighborMatcher | None = None,
        match_threshold: float = 0.0,
        mergeable_columns: list[str] | None = None,
        *,
        source_column: str | None = None,
        sources_column: str = "sources",
    ) -> None:
        self._norm_key_column = norm_key_column
        self._matcher = matcher
        self._match_threshold = match_threshold
        self._mergeable_columns = mergeable_columns
        self._source_column = source_column
        self._sources_column = sources_column

    def process(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame

        grouped = self._collapse_keys(frame)
        sources = self._group_sources(frame)
        if self._matcher is None:
            return self._with_sources(grouped, sources)

        requested = self._mergeable_columns or list(frame.columns)
        merge_columns = [
            column for column in requested if column in frame.columns and column != self._norm_key_column
        ]
        dropped: set[int] = set()
        absorbed_by: dict[int, int] = {}
        for keep_idx, drop_idx in self._matcher.find_matches(grouped, self._match_threshold):
            keeper = self._surviving_row(keep_idx, absorbed_by)
            if drop_idx in dropped or keeper == drop_idx:
                continue
            for column in merge_columns:
                if pd.isna(grouped.at[keeper, column]) and pd.notna(grouped.at[drop_idx, column]):
                    grouped.at[keeper, column] = grouped.at[drop_idx, column]
            if sources is not None:
                sources[keeper] |= sources[drop_idx]
            dropped.add(drop_idx)
            absorbed_by[drop_idx] = keeper

        return self._with_sources(grouped, sources).drop(index=list(dropped)).reset_index(drop=True)

    def _labels(self, frame: pd.DataFrame) -> np.ndarray:
        keys = frame[self._norm_key_column]
        keyed = (keys.notna() & (keys != "")).to_numpy()
        codes, uniques = pd.factorize(keys.where(keyed), sort=True)
        labels: np.ndarray = np.where(keyed, codes, len(uniques) + np.arange(len(frame)))
        return labels

    def _group_sources(self, frame: pd.DataFrame) -> list[set[str]] | None:
        if self._source_column is None:
            return None
        values = frame[self._source_column]
        return [
            {str(value) for value in group if pd.notna(value) and str(value) != ""}
            for _label, group in values.groupby(self._labels(frame), sort=True)
        ]

    def _with_sources(self, grouped: pd.DataFrame, sources: list[set[str]] | None) -> pd.DataFrame:
        if sources is None:
            return grouped
        grouped[self._sources_column] = ["; ".join(sorted(found)) for found in sources]
        return grouped

    def _collapse_keys(self, frame: pd.DataFrame) -> pd.DataFrame:
        grouped = frame.groupby(self._labels(frame), sort=True).first().reset_index(drop=True)
        ordered = [self._norm_key_column, *(column for column in grouped.columns if column != self._norm_key_column)]
        return grouped[ordered]

    @staticmethod
    def _surviving_row(index: int, absorbed_by: dict[int, int]) -> int:
        while index in absorbed_by:
            index = absorbed_by[index]
        return index
