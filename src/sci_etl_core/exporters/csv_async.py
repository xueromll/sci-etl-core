from __future__ import annotations

import asyncio
import csv
import io
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sci_etl_core._atomic_io import atomic_write_text
from sci_etl_core.exceptions import ExportError
from sci_etl_core.exporters._entities import entity_to_dict
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.models import RawRecord

RECORD_COLUMN = "record_id"
EXTRA_COLUMN = "extra"

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_ESCAPE = "'"

Row = tuple[str, ...]


def _escape_cell(value: str) -> str:
    """Prefix text a spreadsheet would evaluate as a formula with an apostrophe.

    A value that already starts with an apostrophe is escaped as well, so that
    :func:`_unescape_cell` restores every written cell exactly.
    """
    if value.startswith((*_FORMULA_PREFIXES, _ESCAPE)):
        return _ESCAPE + value
    return value


def _unescape_cell(value: str) -> str:
    return value[1:] if value.startswith(_ESCAPE) else value


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class AsyncCsvExporter(AsyncExporter[Any]):
    """Write every entity as one CSV row, tagged with the record it came from.

    The table is long: the first column is ``record_id``, then ``columns`` in
    order, then ``extra``, which holds any other keys of the entity as a JSON
    object, so no extracted value is dropped. Values are written as text,
    unchanged: nothing is clipped, coerced to a number, or merged across
    records, so two papers that report one object give two rows and a
    conflict stays visible. Merge or deduplicate after the run, for example
    with :class:`~sci_etl_core.processors.dedup.DeduplicationStep`.

    Writing a record replaces all of its rows, so the last write for a record
    wins, and a record written with no entities has no rows. A repeated write
    is idempotent.

    The CSV file is rendered once per run, when the run closes the exporter.
    During the run, each :meth:`flush` appends the page's records to
    ``<path>.journal`` and calls ``fsync``, so ``durable_writes`` is
    ``False``. A reader mid-run sees the previous run's table. A run that
    crashed leaves the journal behind, and the next :meth:`open` replays it
    into the table before anything else happens. Total work per run is linear
    in the number of rows.

    Cells a spreadsheet would read as a formula are written with a leading
    apostrophe and restored when the file is read back, unless
    ``escape_formulas`` is ``False``. Entities may be dicts, Pydantic models,
    dataclass instances, or claims.
    """

    durable_writes = False

    def __init__(self, path: str | Path, columns: Sequence[str], *, escape_formulas: bool = True) -> None:
        """Configure the exporter.

        Raises:
            ValueError: ``columns`` is empty, repeats a name, or names
                ``record_id`` or ``extra``.
        """
        names = list(columns)
        if not names:
            raise ValueError("columns must name at least one entity key")
        if len(set(names)) != len(names):
            raise ValueError("columns must not repeat a name")
        if {RECORD_COLUMN, EXTRA_COLUMN} & set(names):
            raise ValueError(f"columns must not include {RECORD_COLUMN!r} or {EXTRA_COLUMN!r}")
        self._path = Path(path)
        self._journal = self._path.with_name(self._path.name + ".journal")
        self._columns = tuple(names)
        self._header: Row = (RECORD_COLUMN, *self._columns, EXTRA_COLUMN)
        self._escape_formulas = escape_formulas
        self._rows: dict[str, list[Row]] = {}
        self._pending: list[str] = []
        self._opened = False
        self._lock: asyncio.Lock | None = None

    @property
    def path(self) -> Path:
        """The CSV file."""
        return self._path

    @property
    def journal_path(self) -> Path:
        """The journal each flush appends to, deleted once the run's table is rendered."""
        return self._journal

    @property
    def header(self) -> Row:
        """The CSV header: ``record_id``, the configured columns, and ``extra``."""
        return self._header

    async def open(self) -> None:
        """Load the existing table and replay a journal a crashed run left behind.

        Raises:
            ExportError: The CSV file or journal cannot be read, or the CSV's
                header differs from :attr:`header`.
        """
        async with self._get_lock():
            if self._opened:
                return
            await asyncio.to_thread(self._load)
            self._opened = True

    async def write(self, record: RawRecord, entities: Sequence[Any]) -> None:
        """Replace the record's rows and queue them for the next :meth:`flush`.

        Raises:
            TypeError: An entity is of a type that cannot be exported.
        """
        rows = [self._row(record.record_id, entity_to_dict(entity)) for entity in entities]
        self._rows[record.record_id] = rows
        self._pending.append(
            json.dumps({"record_id": record.record_id, "rows": [list(row) for row in rows]}, ensure_ascii=False)
            + "\n"
        )

    async def flush(self) -> None:
        """Append the queued records to the journal and ``fsync`` it.

        Raises:
            ExportError: The journal could not be written; the records stay
                queued.
        """
        async with self._get_lock():
            if not self._pending:
                return
            payload = "".join(self._pending)
            await asyncio.to_thread(self._append_journal, payload)
            self._pending.clear()

    async def aclose(self) -> None:
        """Render the table, replace the CSV atomically, and delete the journal.

        Queued records are journaled first. After a fault the journal stays,
        and the next :meth:`open` replays it.

        Raises:
            ExportError: The journal or the CSV file could not be written.
        """
        await self.flush()
        async with self._get_lock():
            if not self._opened:
                return
            await asyncio.to_thread(self._publish)
            self._opened = False
            self._rows = {}

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _row(self, record_id: str, entity: dict[str, Any]) -> Row:
        extra = {key: value for key, value in entity.items() if key not in self._columns}
        cells = [_cell(entity.get(column)) for column in self._columns]
        extra_cell = json.dumps(extra, ensure_ascii=False, sort_keys=True, default=str) if extra else ""
        return (record_id, *cells, extra_cell)

    def _load(self) -> None:
        self._rows = {}
        try:
            if self._path.is_file() and self._path.stat().st_size > 0:
                self._read_table()
            if self._journal.is_file():
                self._replay_journal()
                self._publish()
        except OSError as error:
            raise ExportError(f"Cannot read {self._path}: {error}") from error

    def _read_table(self) -> None:
        with self._path.open(encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            header = tuple(next(reader, ()))
            if header != self._header:
                raise ExportError(f"{self._path} has the header {list(header)}, not {list(self._header)}")
            for number, cells in enumerate(reader, start=2):
                if len(cells) != len(self._header):
                    raise ExportError(f"{self._path}:{number} has {len(cells)} cells, not {len(self._header)}")
                row = tuple(_unescape_cell(cell) for cell in cells) if self._escape_formulas else tuple(cells)
                self._rows.setdefault(row[0], []).append(row)

    def _replay_journal(self) -> None:
        with self._journal.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.endswith("\n"):
                    break
                try:
                    entry = json.loads(line)
                    self._rows[entry["record_id"]] = [tuple(row) for row in entry["rows"]]
                except (ValueError, KeyError, TypeError) as error:
                    raise ExportError(f"{self._journal}:{number} is not a journal entry") from error

    def _append_journal(self, payload: str) -> None:
        try:
            self._journal.parent.mkdir(parents=True, exist_ok=True)
            with self._journal.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as error:
            raise ExportError(f"Cannot append to {self._journal}: {error}") from error

    def _publish(self) -> None:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(self._header)
        for rows in self._rows.values():
            for row in rows:
                writer.writerow([_escape_cell(cell) for cell in row] if self._escape_formulas else row)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(self._path, buffer.getvalue())
            self._journal.unlink(missing_ok=True)
        except OSError as error:
            raise ExportError(f"Cannot write {self._path}: {error}") from error
