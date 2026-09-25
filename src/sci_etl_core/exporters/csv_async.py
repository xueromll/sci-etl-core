from __future__ import annotations

import asyncio
import io
import os
from typing import Any

import aiofiles
import numpy as np
import pandas as pd

from sci_etl_core._atomic_io import atomic_write_text
from sci_etl_core._deprecation import warn_deprecated
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.processors.normalization import KeyNormalizer

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_ESCAPE = "'"
_NORM_KEY = "_norm_key"


def _escape_cell(value: Any) -> Any:
    """Prefix text a spreadsheet would evaluate as a formula with an apostrophe.

    A value that already starts with an apostrophe is escaped as well, so that
    :func:`_unescape_cell` restores every written key exactly.
    """
    if isinstance(value, str) and value.startswith((*_FORMULA_PREFIXES, _ESCAPE)):
        return _ESCAPE + value
    return value


def _unescape_cell(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(_ESCAPE):
        return value[1:]
    return value


class AsyncCsvUpsertExporter(AsyncExporter):
    """Concurrency-safe, crash-safe CSV upsert exporter.

    All read-modify-write cycles are serialized through a single
    :class:`asyncio.Lock`, so concurrent ``export`` calls can never overwrite
    one another. Each call renders the full merged snapshot and publishes it
    with an atomic rename, and the in-memory buffer is only advanced once the
    rename succeeds, keeping memory and disk consistent after a failure.

    The existing file is read before the first write to each destination, and
    the snapshot is adopted only once that read succeeds. A file that cannot be
    read (a foreign encoding, a malformed row, a lock held by another program)
    fails the export instead of letting a later call overwrite the file with
    only the new rows.

    Keys come from LLM output, so by default any key a spreadsheet would treat
    as a formula is written with a leading apostrophe and restored on reload.
    Value columns are numeric and need no escaping.

    .. deprecated:: 0.5.0
        Constructing it emits a :class:`DeprecationWarning`. It will be
        removed in 0.6.0, which adds its replacement, ``AsyncCsvExporter``;
        keep using it until then.
    """

    def __init__(
        self,
        key_column: str,
        value_columns: list[str],
        normalizer: KeyNormalizer,
        numeric_clip: dict[str, tuple[float, float]] | None = None,
        escape_formulas: bool = True,
    ) -> None:
        warn_deprecated(
            "AsyncCsvUpsertExporter", "its replacement is AsyncCsvExporter (0.6.0), so keep using it until you upgrade"
        )
        self._key_column = key_column
        self._value_columns = value_columns
        self._normalizer = normalizer
        self._numeric_clip = numeric_clip or {}
        self._escape_formulas = escape_formulas
        self._lock: asyncio.Lock | None = None
        self._frame: pd.DataFrame = self._empty_frame()
        self._loaded_destination: str | None = None

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

    def _empty_frame(self) -> pd.DataFrame:
        columns: dict[str, pd.Series] = {self._key_column: pd.Series(dtype=object)}
        for column in self._value_columns:
            columns[column] = pd.Series(dtype="float64")
        return pd.DataFrame(columns)

    @staticmethod
    def _has_content(destination: str) -> bool:
        return os.path.isfile(destination) and os.path.getsize(destination) > 0

    async def _ensure_loaded(self, destination: str) -> None:
        if self._loaded_destination == destination:
            return
        frame = self._empty_frame()
        if await asyncio.to_thread(self._has_content, destination):
            async with aiofiles.open(destination, encoding="utf-8") as handle:
                existing_text = await handle.read()
            frame = await asyncio.to_thread(self._init_frame, existing_text)
        self._frame = frame
        self._loaded_destination = destination

    def _init_frame(self, existing_text: str) -> pd.DataFrame:
        """Parse the existing file without letting pandas rewrite its keys.

        The key column is read as text: left to infer, a key like ``"007"``
        reloads as the integer 7 and a key spelled ``"NA"`` reloads as missing,
        either of which stops the next record with that key from matching and
        silently duplicates the row. The default NA vocabulary is suppressed for
        the same reason, while an empty field still reads as missing so that a
        blank value column stays fillable.
        """
        frame = pd.read_csv(
            io.StringIO(existing_text),
            dtype={self._key_column: str},
            keep_default_na=False,
            na_values=[""],
        )
        if self._key_column not in frame.columns:
            frame[self._key_column] = None
        for column in self._value_columns:
            if column not in frame.columns:
                frame[column] = np.nan
        if frame.empty:
            frame = frame.astype({column: "float64" for column in self._value_columns})
        if self._escape_formulas:
            frame[self._key_column] = frame[self._key_column].map(_unescape_cell)
        return frame

    def _apply(self, data: list[dict[str, Any]]) -> tuple[pd.DataFrame, str]:
        """Merge a batch into a copy of the snapshot, keeping one row per key.

        Rows first seen in this batch are held in ``new_rows`` until the end, so
        a key repeated within the batch fills its pending row instead of being
        appended twice.
        """
        frame = self._frame.reset_index(drop=True)
        frame[_NORM_KEY] = frame[self._key_column].apply(self._normalizer.normalize)
        new_rows: dict[str, dict[str, Any]] = {}

        for record in data:
            if not isinstance(record, dict):
                continue
            raw_key = record.get(self._key_column)
            norm_key = self._normalizer.normalize(raw_key)
            if not norm_key:
                continue

            match_mask = frame[_NORM_KEY] == norm_key
            if match_mask.any():
                self._fill_missing(frame, match_mask.idxmax(), record)
            elif norm_key in new_rows:
                self._fill_pending(new_rows[norm_key], record)
            else:
                new_rows[norm_key] = self._build_row(raw_key, norm_key, record)

        if new_rows:
            additions = pd.DataFrame(list(new_rows.values()), columns=list(frame.columns))
            additions = additions.astype({column: "float64" for column in self._value_columns})
            frame = pd.concat([frame, additions], ignore_index=True)

        return frame, self._render(frame)

    def _render(self, frame: pd.DataFrame) -> str:
        output = frame.drop(columns=[_NORM_KEY])
        if self._escape_formulas:
            output[self._key_column] = output[self._key_column].map(_escape_cell)
        return output.to_csv(index=False)

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
        row: dict[str, Any] = {self._key_column: raw_key, _NORM_KEY: norm_key}
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
