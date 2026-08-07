from __future__ import annotations

import os
from typing import Any

import pandas as pd

from sci_etl_core.exporters.base import Exporter
from sci_etl_core.processors.normalization import KeyNormalizer


class CsvUpsertExporter(Exporter):
    def __init__(
        self,
        key_column: str,
        value_columns: list[str],
        normalizer: KeyNormalizer,
        numeric_clip: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        self._key_column = key_column
        self._value_columns = value_columns
        self._normalizer = normalizer
        self._numeric_clip = numeric_clip or {}

    def export(self, data: list[dict[str, Any]], destination: str) -> None:
        if not data:
            return

        fieldnames = [self._key_column] + self._value_columns
        frame = (
            pd.read_csv(destination)
            if os.path.isfile(destination) and os.path.getsize(destination) > 0
            else pd.DataFrame(columns=fieldnames)
        )
        for column in fieldnames:
            if column not in frame.columns:
                frame[column] = None

        frame["_norm_key"] = frame[self._key_column].apply(self._normalizer.normalize)
        new_rows: list[dict[str, Any]] = []

        for record in data:
            raw_key = record.get(self._key_column)
            norm_key = self._normalizer.normalize(raw_key) if raw_key else ""
            if not norm_key:
                continue

            match_mask = frame["_norm_key"] == norm_key
            if match_mask.any():
                self._fill_missing(frame, match_mask.idxmax(), record)
            else:
                new_rows.append(self._build_row(raw_key, norm_key, record))

        if new_rows:
            frame = pd.concat([frame, pd.DataFrame(new_rows)], ignore_index=True)

        frame.drop(columns=["_norm_key"]).to_csv(destination, index=False, encoding="utf-8")

    def _fill_missing(self, frame: pd.DataFrame, index: int, record: dict[str, Any]) -> None:
        for column in self._value_columns:
            new_value = record.get(column)
            if new_value is None or pd.notna(frame.at[index, column]):
                continue
            coerced = self._coerce(column, new_value)
            if coerced is not None:
                frame.at[index, column] = coerced

    def _build_row(self, raw_key: Any, norm_key: str, record: dict[str, Any]) -> dict[str, Any]:
        row: dict[str, Any] = {self._key_column: raw_key, "_norm_key": norm_key}
        for column in self._value_columns:
            row[column] = self._coerce(column, record.get(column))
        return row

    def _coerce(self, column: str, value: Any) -> float | None:
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if column in self._numeric_clip:
            low, high = self._numeric_clip[column]
            numeric = min(max(numeric, low), high)
        return numeric
