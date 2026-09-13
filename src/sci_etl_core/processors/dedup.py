from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd

from sci_etl_core.processors.base import Processor


class NeighborMatcher(ABC):
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
    """

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

        grouped = self._collapse_keys(frame)
        if self._matcher is None:
            return grouped

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
            dropped.add(drop_idx)
            absorbed_by[drop_idx] = keeper

        return grouped.drop(index=list(dropped)).reset_index(drop=True)

    def _collapse_keys(self, frame: pd.DataFrame) -> pd.DataFrame:
        keys = frame[self._norm_key_column]
        keyed = (keys.notna() & (keys != "")).to_numpy()
        codes, uniques = pd.factorize(keys.where(keyed), sort=True)
        labels = np.where(keyed, codes, len(uniques) + np.arange(len(frame)))
        grouped = frame.groupby(labels, sort=True).first().reset_index(drop=True)
        ordered = [self._norm_key_column, *(column for column in grouped.columns if column != self._norm_key_column)]
        return grouped[ordered]

    @staticmethod
    def _surviving_row(index: int, absorbed_by: dict[int, int]) -> int:
        while index in absorbed_by:
            index = absorbed_by[index]
        return index
