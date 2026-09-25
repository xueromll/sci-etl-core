from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sci_etl_core._deprecation import is_bundled, warn_deprecated
from sci_etl_core.models import RawRecord


class Extractor(ABC):
    """Blocking counterpart of :class:`~sci_etl_core.extractors.async_base.AsyncExtractor`.

    Wrap an implementation in
    :class:`~sci_etl_core._adapters.SyncExtractorAdapter` to use it in a
    pipeline.

    .. deprecated:: 0.5.0
        Subclassing it outside sci-etl-core emits a
        :class:`DeprecationWarning`. The blocking contracts will be removed in
        0.6.0; implement :class:`AsyncExtractor` instead.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not is_bundled(cls):
            warn_deprecated("The blocking Extractor contract", "implement AsyncExtractor instead", stacklevel=3)

    @abstractmethod
    def search(self, query: str, max_results: int, start_index: int) -> bytes | None:
        """Fetch a raw listing page from the source.

        Raises:
            UpstreamError: The source could not be reached or answered with a
                server-side failure.
        """

    @abstractmethod
    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        """Parse a raw listing into records, skipping already-seen ids.

        Raises:
            MalformedResponseError: The payload could not be interpreted.
        """

    @abstractmethod
    def fetch_full_text(self, record: RawRecord) -> str:
        """Retrieve the best-available full text for a record."""
