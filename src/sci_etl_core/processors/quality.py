from __future__ import annotations

import pandas as pd

from sci_etl_core.processors.base import Processor


class CompletenessStep(Processor):
    """Add ``output_column`` with the percentage of ``tracked_fields`` each row fills."""

    def __init__(self, tracked_fields: list[str], output_column: str = "completeness_pct") -> None:
        self._tracked_fields = tracked_fields
        self._output_column = output_column

    def process(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return a copy of ``frame`` with the percentage, rounded to one decimal place.

        Tracked fields missing from ``frame`` are ignored. When none is present,
        every row scores ``0.0``.
        """
        frame = frame.copy()
        existing = [field for field in self._tracked_fields if field in frame.columns]
        if not existing:
            frame[self._output_column] = 0.0
            return frame
        filled = frame[existing].notna().sum(axis=1)
        frame[self._output_column] = (filled / len(existing) * 100).round(1)
        return frame


class QualityFlagStep(Processor):
    """Label each row from its completeness, as computed by :class:`CompletenessStep`."""

    def __init__(
        self,
        completeness_column: str = "completeness_pct",
        output_column: str = "quality_flag",
        review_threshold: float = 50.0,
    ) -> None:
        self._completeness_column = completeness_column
        self._output_column = output_column
        self._review_threshold = review_threshold

    def process(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return a copy of ``frame`` with the label column added.

        A row at 100% is ``"Confirmed"``, one at or above ``review_threshold``
        is ``"Needs Review"``, and any other row, including one without a
        completeness value, is ``"Low Confidence"``.

        Raises:
            KeyError: ``frame`` has no ``completeness_column``.
        """
        frame = frame.copy()

        def classify(pct: float) -> str:
            if pd.isna(pct):
                return "Low Confidence"
            if pct == 100.0:
                return "Confirmed"
            if pct >= self._review_threshold:
                return "Needs Review"
            return "Low Confidence"

        frame[self._output_column] = frame[self._completeness_column].apply(classify)
        return frame
