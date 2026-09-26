from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import ClassVar, Generic, TypeVar

from sci_etl_core.models import RawRecord

E = TypeVar("E", contravariant=True)


class AsyncExporter(ABC, Generic[E]):
    """A sink for one run's entities.

    :class:`~sci_etl_core.pipeline_async.AsyncETLPipeline` calls :meth:`open`
    once when a run starts, :meth:`write` once per processed record, possibly
    for several records concurrently, :meth:`flush` after each page, and
    :meth:`aclose` when the run ends, however it ends. An exporter takes its
    destination when it is constructed.

    Delivery is at least once: a crash can repeat a record, never lose one.
    With ``durable_writes = True``, :meth:`write` returns only once the
    entities are durable, and the pipeline marks the record processed right
    after it. With ``durable_writes = False``, :meth:`write` may buffer, and
    the pipeline marks the page's written records processed only after
    :meth:`flush` returns.
    """

    durable_writes: ClassVar[bool] = True

    async def open(self) -> None:
        """Prepare the sink before the run's first listing request; the default does nothing.

        A fault here aborts the run before any listing request.
        """

    @abstractmethod
    async def write(self, record: RawRecord, entities: Sequence[E]) -> None:
        """Store ``entities`` for ``record``.

        The pipeline calls it for every processed record, including one with
        no entities, so a sink can clear rows a re-extracted record no longer
        has. It must be idempotent: repeating a ``write`` with the same
        arguments, including after one that raised partway, leaves the sink as
        a single successful ``write`` would. Each sink documents which write
        wins when a repeat carries different entities.

        A fault here fails the record, which is retried on the next run and
        counts one failed attempt.
        """

    async def flush(self) -> None:
        """Make every earlier ``write`` durable; the default does nothing.

        A fault here leaves the records written since the last successful
        ``flush`` unsettled, counts no failed attempt against them, and makes
        the page a stalled page.
        """

    async def aclose(self) -> None:
        """Finish the run's output and release resources; the default does nothing.

        The pipeline calls :meth:`flush` first. A fault here is raised only
        when the run itself succeeded.
        """
