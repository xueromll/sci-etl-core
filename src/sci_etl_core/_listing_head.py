from __future__ import annotations

from collections.abc import Sequence
from enum import Enum

from sci_etl_core.models import PipelineMetadata

HEAD_ID_LIMIT = 25


class _Mode(Enum):
    RESCAN = "rescan"
    SCANNING = "scanning"
    PROBING = "probing"
    BACKLOG = "backlog"


class NewestFirstCursor:
    """Resume a newest-first listing whose entries shift down as submissions arrive.

    The metadata describes one listing snapshot: ``head_ids`` were seen from
    position ``head_offset``, every entry before ``last_start_index`` was
    settled, and ``tail_ids`` are the last entries before that offset.

    A run pages from offset 0 until one of the head ids turns up. Its new
    position gives the shift, the number of submissions that arrived since, so
    the backlog now starts at ``last_start_index + shift``. The head scan goes
    on until it has passed every saved head id, and then the run jumps to
    the page just before that offset and checks that the tail ids are on it.
    If they are, everything between the head and that page was settled by
    earlier runs, and paging continues from there. If they are not, entries
    were removed from the listing or moved, and the run pages on from the head
    instead, skipping nothing.

    When every head page settled, the head ids are refreshed from this run's
    first page. Otherwise they are taken from the last head page that did not
    settle, so the next run's head scan reaches every record left unsettled
    near the top, which lies at or before those ids. Without saved head ids, or
    when none turns up before the listing ends, the run is a plain scan from
    offset 0 and the metadata is rebuilt from it.
    """

    def __init__(self, metadata: PipelineMetadata, page_size: int) -> None:
        self._metadata = metadata
        self._page_size = page_size
        self._saved_ids = list(metadata.head_ids)
        self._saved_offset = metadata.head_offset
        self._saved_backlog = metadata.last_start_index
        self._saved_tail = set(metadata.tail_ids)
        self._mode = _Mode.SCANNING if self._saved_ids else _Mode.RESCAN
        self._unsettled_head: tuple[int, list[str]] | None = None
        self._fresh_ids: list[str] = []
        self._scan_settled = True
        self._scan_offset = 0
        self._scan_tail: list[str] = []
        self._backlog_settled = True
        self._head_end = 0
        self._head_end_tail: list[str] = []
        self.shift: int | None = None
        self.realigned = False

    @property
    def scanning(self) -> bool:
        """Whether the run is still looking for the ids saved at the head."""
        return self._mode is _Mode.SCANNING

    def observe_page(self, page_start: int, listed_ids: Sequence[str], entries: int, complete: bool) -> int:
        """Account for a processed page and return the offset to fetch next.

        ``listed_ids`` are every id on the page in listing order, processed or
        not, and ``entries`` is how many entries the page held.
        """
        next_offset = page_start + entries
        tail = list(listed_ids[-HEAD_ID_LIMIT:])
        if page_start == 0:
            self._fresh_ids = list(listed_ids[:HEAD_ID_LIMIT])
        self._scan_settled = self._scan_settled and complete
        if self._scan_settled:
            self._scan_offset, self._scan_tail = next_offset, tail
        if self._mode is _Mode.RESCAN:
            self._adopt_scan()
            return next_offset
        if self._mode is _Mode.SCANNING:
            return self._observe_head(page_start, listed_ids, next_offset, tail, complete)
        if self._mode is _Mode.PROBING:
            return self._observe_probe(page_start, listed_ids, next_offset, tail, complete)
        self._settle_backlog(next_offset, tail, complete)
        return next_offset

    def listing_ended(self) -> int | None:
        """Account for an empty page and return the offset to continue from, or ``None`` to stop."""
        if self._mode is _Mode.SCANNING:
            self._adopt_scan()
            return None
        if self._mode is _Mode.PROBING:
            return self._fall_back()
        return None

    def _observe_head(
        self, page_start: int, listed_ids: Sequence[str], next_offset: int, tail: list[str], complete: bool
    ) -> int:
        if not complete:
            self._unsettled_head = (page_start + len(listed_ids) - len(tail), tail)
        if self.shift is None:
            self.shift = self._locate(page_start, listed_ids)
            if self.shift is None:
                return next_offset
        if next_offset < self._saved_offset + len(self._saved_ids) + self.shift:
            return next_offset
        if self._unsettled_head is None:
            self._metadata.head_ids = list(self._fresh_ids)
            self._metadata.head_offset = 0
        else:
            self._metadata.head_offset, self._metadata.head_ids = self._unsettled_head
        self._head_end, self._head_end_tail = next_offset, tail
        probe = self._saved_backlog + self.shift - self._page_size
        if self._saved_tail and probe > next_offset:
            self._mode = _Mode.PROBING
            self._metadata.last_start_index = self._saved_backlog + self.shift
            return probe
        self._mode = _Mode.BACKLOG
        self._metadata.last_start_index, self._metadata.tail_ids = next_offset, tail
        return next_offset

    def _observe_probe(
        self, page_start: int, listed_ids: Sequence[str], next_offset: int, tail: list[str], complete: bool
    ) -> int:
        if self._saved_tail.isdisjoint(listed_ids):
            return self._fall_back()
        self._mode = _Mode.BACKLOG
        if complete:
            self._metadata.last_start_index, self._metadata.tail_ids = next_offset, tail
        else:
            self._backlog_settled = False
            self._metadata.last_start_index, self._metadata.tail_ids = page_start, []
        return next_offset

    def _fall_back(self) -> int:
        self.realigned = True
        self._mode = _Mode.BACKLOG
        self._metadata.last_start_index, self._metadata.tail_ids = self._head_end, self._head_end_tail
        return self._head_end

    def _settle_backlog(self, next_offset: int, tail: list[str], complete: bool) -> None:
        self._backlog_settled = self._backlog_settled and complete
        if self._backlog_settled:
            self._metadata.last_start_index, self._metadata.tail_ids = next_offset, tail

    def _adopt_scan(self) -> None:
        self._mode = _Mode.RESCAN
        self._metadata.head_ids = list(self._fresh_ids)
        self._metadata.head_offset = 0
        self._metadata.last_start_index = self._scan_offset
        self._metadata.tail_ids = list(self._scan_tail)

    def _locate(self, page_start: int, listed_ids: Sequence[str]) -> int | None:
        saved_positions = {record_id: self._saved_offset + index for index, record_id in enumerate(self._saved_ids)}
        for index, record_id in enumerate(listed_ids):
            saved_position = saved_positions.get(record_id)
            if saved_position is not None:
                return page_start + index - saved_position
        return None
