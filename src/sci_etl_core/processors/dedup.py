from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from sci_etl_core.processors.base import Processor


class NeighborMatcher(ABC):
    @abstractmethod
    def find_matches(self, frame: pd.DataFrame, threshold: float) -> list[tuple[int, int]]:
        """Return (keep_index, drop_index) pairs for rows considered duplicates."""


class DeduplicationStep(Processor):
    def __init__(
        self,
        norm_key_column: str,
        matcher: NeighborMatcher | None = None,
        match_threshold: float = 0.0,
        mergeable_columns: list[str] | None = None,
    ) -> None:
        self._norm_key_column = norm_key_column
        self._matcher = matcher
        self._match_threshold = match_threshold
        self._mergeable_columns = mergeable_columns

    def process(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame

        merge_columns = self._mergeable_columns or [
            column for column in frame.columns if column != self._norm_key_column
        ]

        first_by_key = frame.groupby(self._norm_key_column)
        grouped = first_by_key.first().reset_index()
        for column in merge_columns:
            if column in frame.columns:
                grouped[column] = grouped[self._norm_key_column].map(first_by_key[column].first())

        if self._matcher is None:
            return grouped

        drop_indices: set[int] = set()
        for keep_idx, drop_idx in self._matcher.find_matches(grouped, self._match_threshold):
            if drop_idx in drop_indices:
                continue
            for column in merge_columns:
                if pd.isna(grouped.at[keep_idx, column]) and pd.notna(grouped.at[drop_idx, column]):
                    grouped.at[keep_idx, column] = grouped.at[drop_idx, column]
            drop_indices.add(drop_idx)

        return grouped.drop(index=list(drop_indices)).reset_index(drop=True)
