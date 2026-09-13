from __future__ import annotations

import asyncio
import io
import os
from typing import Any

import aiofiles
import pandas as pd

from sci_etl_core._atomic_io import atomic_write_text
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.processors.normalization import KeyNormalizer


class AsyncCsvUpsertExporter(AsyncExporter):
    """Concurrency-safe, crash-safe CSV upsert exporter.

    All read-modify-write cycles are serialized through a single
    :class:`asyncio.Lock`, so concurrent ``export`` calls can never overwrite
    one another. Each call renders the full merged snapshot and publishes it
    with an atomic rename, and the in-memory buffer is only advanced once the
    rename succeeds, keeping memory and disk consistent after a failure.
    """

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
        self._lock: asyncio.Lock | None = None
        self._frame: pd.DataFrame = pd.DataFrame(columns=[key_column, *value_columns])
        self._loaded = False

    async def export(self, data: list[dict[str, Any]], destination: str) -> None:
        if not data:
            return
        async with self._get_lock():
            await self._ensure_loaded(destination)
            merged, output_text = await asyncio.to_thread(self._apply, data)
            await asyncio.to_thread(atomic_write_text, destination, output_text)
            self._frame = merged

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def _ensure_loaded(self, destination: str) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not (os.path.isfile(destination) and os.path.getsize(destination) > 0):
            return
        async with aiofiles.open(destination, "r", encoding="utf-8") as handle:
            existing_text = await handle.read()
        self._frame = await asyncio.to_thread(self._init_frame, existing_text)

    def _init_frame(self, existing_text: str) -> pd.DataFrame:
        # The key column is read as text so that pandas cannot rewrite it on the
        # way back in. Left to infer, a key like "007" reloads as the integer 7,
        # and a key spelled "NA" or "NaN" reloads as a missing value -- either
        # one corrupts the stored key and stops the next record carrying that
        # key from matching it, silently duplicating the row on restart.
        # Suppressing the default NA vocabulary keeps those spellings intact,
        # while an empty field still reads as missing so that a blank value
        # column stays fillable.
        frame = pd.read_csv(
            io.StringIO(existing_text),
            dtype={self._key_column: str},
            keep_default_na=False,
            na_values=[""],
        )
        for column in (self._key_column, *self._value_columns):
            if column not in frame.columns:
                frame[column] = None
        return frame

    def _apply(self, data: list[dict[str, Any]]) -> tuple[pd.DataFrame, str]:
        frame = self._frame.reset_index(drop=True)
        frame["_norm_key"] = frame[self._key_column].apply(self._normalizer.normalize)
        new_rows: dict[str, dict[str, Any]] = {}

        for record in data:
            raw_key = record.get(self._key_column)
            norm_key = self._normalizer.normalize(raw_key) if raw_key else ""
            if not norm_key:
                continue

            match_mask = frame["_norm_key"] == norm_key
            if match_mask.any():
                self._fill_missing(frame, match_mask.idxmax(), record)
            elif norm_key in new_rows:
                # Rows pending from this same batch are not in ``frame`` yet, so
                # they cannot be found by the mask above. Filling the pending row
                # keeps one row per key; appending again would duplicate the key
                # that the whole upsert exists to keep unique.
                self._fill_pending(new_rows[norm_key], record)
            else:
                new_rows[norm_key] = self._build_row(raw_key, norm_key, record)

        if new_rows:
            frame = pd.concat(
                [frame, pd.DataFrame(list(new_rows.values()))], ignore_index=True
            )

        return frame, frame.drop(columns=["_norm_key"]).to_csv(index=False)

    def _fill_pending(self, row: dict[str, Any], record: dict[str, Any]) -> None:
        """Fill a not-yet-appended row's gaps, leaving settled values alone."""
        for column in self._value_columns:
            if row.get(column) is not None:
                continue
            coerced = self._coerce(column, record.get(column))
            if coerced is not None:
                row[column] = coerced

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
