"""The contract suite for exporters.

Subclass :class:`ExporterContract` in a test module under a name pytest
collects, such as ``TestMyExporter``, and give it a ``make_exporter`` fixture
and a ``read_exported`` fixture:

```python
import json

import pytest

from sci_etl_core.testing import ExporterContract

from my_package import MyExporter


class TestMyExporter(ExporterContract):
    @pytest.fixture
    def make_exporter(self, tmp_path):
        return lambda: MyExporter(tmp_path / "out.json")

    @pytest.fixture
    def read_exported(self, tmp_path):
        async def read(record_id):
            exported = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
            return exported.get(record_id, [])

        return read
```

The tests are plain functions that run each scenario with :func:`asyncio.run`,
so pytest-asyncio is not needed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import pytest

from sci_etl_core.exceptions import SciEtlError
from sci_etl_core.exporters.async_base import AsyncExporter
from sci_etl_core.models import RawRecord


def _record(record_id: str) -> RawRecord:
    return RawRecord(record_id=record_id, title=f"Title of {record_id}", abstract=f"Abstract of {record_id}.")


def _dict_entities(record: RawRecord, count: int) -> list[dict[str, Any]]:
    return [{"name": f"{record.record_id}-{index}", "value": index} for index in range(count)]


async def _run(exporter: AsyncExporter[Any], *writes: tuple[RawRecord, Sequence[Any]]) -> None:
    await exporter.open()
    for record, entities in writes:
        await exporter.write(record, entities)
    await exporter.flush()
    await exporter.aclose()


async def _open_and_write(exporter: AsyncExporter[Any], record: RawRecord, entities: Sequence[Any]) -> None:
    await exporter.open()
    await exporter.write(record, entities)


class ExporterContract:
    """Tests every :class:`~sci_etl_core.exporters.async_base.AsyncExporter` must pass.

    A subclass provides two fixtures:

    - ``make_exporter`` returns a callable that takes no argument and returns
      a new exporter over the same destination each time it is called, as
      each run of a pipeline would build it. The destination starts empty in
      every test, and the suite calls the callable inside a running event
      loop.
    - ``read_exported`` returns an async callable that takes a record id and
      returns the entities the destination holds for that record, in a form
      that compares equal when the content is the same, and an empty sequence
      when it holds none. The suite awaits it after the exporter has closed,
      and before, for an exporter with ``durable_writes = True``.

    A subclass may also override the ``make_entities`` fixture when the
    exporter takes entities other than dicts, and the ``write_newer_schema``
    fixture to check that a destination from a newer release is refused.

    Each run follows the pipeline's lifecycle: ``open()``, ``write()`` for
    each record, ``flush()``, then ``aclose()``. Some tests check an optional
    capability and skip when the implementation lacks it: reading a write
    before ``flush()``, when ``durable_writes`` is ``False``, and the
    schema-version test, when ``write_newer_schema`` returns ``None``.
    """

    @pytest.fixture
    def make_entities(self) -> Callable[[RawRecord, int], Sequence[Any]]:
        """Return a callable that builds ``count`` distinct entities for ``record``.

        The default builds dicts with a ``name`` and a ``value`` key.
        """
        return _dict_entities

    @pytest.fixture
    def write_newer_schema(self) -> Callable[[], None] | None:
        """Return a callable that writes a destination from a newer schema version, or ``None``.

        The suite calls it before it creates an exporter. The default returns
        ``None``, which skips the schema-version test; override it when the
        destination records a schema version.
        """
        return None

    def test_written_entities_are_exported(
        self,
        make_exporter: Callable[[], AsyncExporter[Any]],
        read_exported: Callable[[str], Awaitable[Sequence[Any]]],
        make_entities: Callable[[RawRecord, int], Sequence[Any]],
    ) -> None:
        """After a run, the destination holds every record's entities."""
        first, second = _record("record-1"), _record("record-2")

        async def scenario() -> None:
            await _run(make_exporter(), (first, make_entities(first, 2)), (second, make_entities(second, 1)))
            assert len(await read_exported("record-1")) == 2
            assert len(await read_exported("record-2")) == 1

        asyncio.run(scenario())

    def test_a_repeated_write_is_idempotent(
        self,
        make_exporter: Callable[[], AsyncExporter[Any]],
        read_exported: Callable[[str], Awaitable[Sequence[Any]]],
        make_entities: Callable[[RawRecord, int], Sequence[Any]],
    ) -> None:
        """Repeating a write, in the same run or a later one, leaves what a single write left."""
        record = _record("record-1")
        entities = make_entities(record, 2)

        async def scenario() -> None:
            await _run(make_exporter(), (record, entities))
            once = list(await read_exported("record-1"))
            assert len(once) == 2
            exporter = make_exporter()
            await exporter.open()
            await asyncio.gather(exporter.write(record, entities), exporter.write(record, entities))
            await exporter.write(record, entities)
            await exporter.flush()
            await exporter.aclose()
            assert list(await read_exported("record-1")) == once

        asyncio.run(scenario())

    def test_a_write_with_no_entities_exports_none(
        self,
        make_exporter: Callable[[], AsyncExporter[Any]],
        read_exported: Callable[[str], Awaitable[Sequence[Any]]],
        make_entities: Callable[[RawRecord, int], Sequence[Any]],
    ) -> None:
        """A record written with no entities holds none, and the other records keep theirs."""
        empty, full = _record("record-empty"), _record("record-1")

        async def scenario() -> None:
            await _run(make_exporter(), (empty, []), (full, make_entities(full, 1)))
            assert len(await read_exported("record-empty")) == 0
            assert len(await read_exported("record-1")) == 1

        asyncio.run(scenario())

    def test_a_run_without_writes_succeeds(
        self,
        make_exporter: Callable[[], AsyncExporter[Any]],
        read_exported: Callable[[str], Awaitable[Sequence[Any]]],
    ) -> None:
        """A run that writes nothing, flushing twice, completes and exports nothing."""

        async def scenario() -> None:
            exporter = make_exporter()
            await exporter.open()
            await exporter.flush()
            await exporter.flush()
            await exporter.aclose()
            assert len(await read_exported("record-1")) == 0

        asyncio.run(scenario())

    def test_aclose_then_reuse(
        self,
        make_exporter: Callable[[], AsyncExporter[Any]],
        read_exported: Callable[[str], Awaitable[Sequence[Any]]],
        make_entities: Callable[[RawRecord, int], Sequence[Any]],
    ) -> None:
        """An exporter runs again after ``aclose()``, keeping what the earlier run exported."""
        first, second = _record("record-1"), _record("record-2")

        async def scenario() -> None:
            exporter = make_exporter()
            await _run(exporter, (first, make_entities(first, 1)))
            await _run(exporter, (second, make_entities(second, 2)))
            assert len(await read_exported("record-1")) == 1
            assert len(await read_exported("record-2")) == 2

        asyncio.run(scenario())

    def test_a_durable_write_is_exported_before_flush(
        self,
        make_exporter: Callable[[], AsyncExporter[Any]],
        read_exported: Callable[[str], Awaitable[Sequence[Any]]],
        make_entities: Callable[[RawRecord, int], Sequence[Any]],
    ) -> None:
        """With ``durable_writes = True``, ``write`` returns only once the entities are exported."""
        record = _record("record-1")

        async def scenario() -> None:
            exporter = make_exporter()
            if not exporter.durable_writes:
                pytest.skip(f"{type(exporter).__name__} buffers writes until flush")
            await _open_and_write(exporter, record, make_entities(record, 2))
            assert len(await read_exported("record-1")) == 2
            await exporter.flush()
            await exporter.aclose()

        asyncio.run(scenario())

    def test_a_newer_schema_version_is_refused(
        self,
        make_exporter: Callable[[], AsyncExporter[Any]],
        make_entities: Callable[[RawRecord, int], Sequence[Any]],
        write_newer_schema: Callable[[], None] | None,
    ) -> None:
        """A destination from a newer schema version raises a ``SciEtlError`` from ``open`` or ``write``."""
        if write_newer_schema is None:
            pytest.skip("write_newer_schema is not provided")
        write_newer_schema()
        record = _record("record-1")

        async def scenario() -> None:
            with pytest.raises(SciEtlError):
                await _open_and_write(make_exporter(), record, make_entities(record, 1))

        asyncio.run(scenario())
