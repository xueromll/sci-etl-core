from __future__ import annotations

import asyncio
import io
import os
from typing import Any

import aiofiles
import pandas as pd

from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.processors.normalization import KeyNormalizer


class AsyncCsvUpsertExporter(AsyncExporter):
    """Concurrency-safe CSV upsert exporter.

    All read-modify-write cycles are serialized through a single
    :class:`asyncio.Lock`, so concurrent ``export`` calls can never overwrite
    one another. Incoming records are merged into an in-memory buffer that is
    loaded from disk only once, and each call writes the full merged snapshot
    in a single write.
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
            output_text = await asyncio.to_thread(self._apply, data)
            async with aiofiles.open(destination, "w", encoding="utf-8") as handle:
                await handle.write(output_text)

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
        frame = pd.read_csv(io.StringIO(existing_text))
        for column in (self._key_column, *self._value_columns):
            if column not in frame.columns:
                frame[column] = None
        return frame

    def _apply(self, data: list[dict[str, Any]]) -> str:
        frame = self._frame.reset_index(drop=True)
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

        self._frame = frame
        return frame.drop(columns=["_norm_key"]).to_csv(index=False)

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
