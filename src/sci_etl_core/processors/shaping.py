from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence

import pandas as pd

from sci_etl_core.processors.base import Processor


class ValueClipStep(Processor):
    """Clamp numeric columns into closed ranges during post-processing.

    Each column named in ``bounds`` is converted to numbers, with values that
    are not numeric becoming ``NaN``, and then clipped to ``(low, high)``. This
    is the post-processing counterpart of the CSV exporter's ``numeric_clip``.
    Columns missing from the frame are skipped, and the input frame is never
    modified.
    """

    def __init__(self, bounds: Mapping[str, tuple[float, float]]) -> None:
        """Store the bounds to apply.

        Raises:
            ValueError: A bound is ``NaN``, or its low end exceeds its high end.
        """
        for column, (low, high) in bounds.items():
            if math.isnan(low) or math.isnan(high):
                raise ValueError(f"Bounds for {column!r} must not be NaN")
            if low > high:
                raise ValueError(f"Lower bound for {column!r} exceeds its upper bound")
        self._bounds = dict(bounds)

    def process(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        for column, (low, high) in self._bounds.items():
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce").clip(low, high)
        return frame


class TableLayoutStep(Processor):
    """Sort rows and arrange columns for a published table.

    Rows are sorted by the ``sort_by`` columns that exist in the frame, each
    ascending or descending as paired, with missing values last and ties kept
    in their input order. Columns whose name starts with any of
    ``hidden_prefixes`` are dropped, then the ``leading_columns`` that exist
    come first in the given order, followed by the rest in their input order.
    The input frame is never modified.
    """

    def __init__(
        self,
        sort_by: Sequence[tuple[str, bool]] = (),
        leading_columns: Sequence[str] = (),
        hidden_prefixes: Iterable[str] = (),
        reset_index: bool = False,
    ) -> None:
        """Store the layout.

        ``sort_by`` pairs each column with ``True`` for ascending order.
        ``reset_index`` renumbers the rows from 0 after sorting.

        Raises:
            ValueError: A column appears twice in ``sort_by`` or in
                ``leading_columns``, or a hidden prefix is empty, which would
                hide every column.
        """
        sort_columns = [column for column, _ in sort_by]
        if len(set(sort_columns)) != len(sort_columns):
            raise ValueError("sort_by names a column more than once")
        if len(set(leading_columns)) != len(leading_columns):
            raise ValueError("leading_columns names a column more than once")
        prefixes = tuple(hidden_prefixes)
        if any(not prefix for prefix in prefixes):
            raise ValueError("hidden_prefixes must not contain an empty prefix")
        self._sort_by = [(column, bool(ascending)) for column, ascending in sort_by]
        self._leading_columns = list(leading_columns)
        self._hidden_prefixes = prefixes
        self._reset_index = reset_index

    def process(self, frame: pd.DataFrame) -> pd.DataFrame:
        sort_keys = [(column, ascending) for column, ascending in self._sort_by if column in frame.columns]
        if sort_keys:
            frame = frame.sort_values(
                by=[column for column, _ in sort_keys],
                ascending=[ascending for _, ascending in sort_keys],
                na_position="last",
                kind="stable",
            )
        visible = [
            column
            for column in frame.columns
            if not (isinstance(column, str) and column.startswith(self._hidden_prefixes))
        ]
        leading = [column for column in self._leading_columns if column in visible]
        arranged = frame[leading + [column for column in visible if column not in leading]]
        if self._reset_index:
            return arranged.reset_index(drop=True)
        return arranged.copy()
