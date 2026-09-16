from __future__ import annotations

from typing import TYPE_CHECKING

from sci_etl_core._lazy import lazy_exports

_EXPORTS: dict[str, str] = {
    "Extractor": "sci_etl_core.extractors.base",
    "AsyncExtractor": "sci_etl_core.extractors.async_base",
    "AsyncArxivExtractor": "sci_etl_core.extractors.arxiv_async",
    "AsyncOpenAlexExtractor": "sci_etl_core.extractors.openalex_async",
    "AsyncPubMedExtractor": "sci_etl_core.extractors.pubmed_async",
    "AsyncSemanticScholarExtractor": "sci_etl_core.extractors.semantic_scholar_async",
}

__all__ = list(_EXPORTS)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _EXPORTS)

if TYPE_CHECKING:
    from sci_etl_core.extractors.arxiv_async import AsyncArxivExtractor
    from sci_etl_core.extractors.async_base import AsyncExtractor
    from sci_etl_core.extractors.base import Extractor
    from sci_etl_core.extractors.openalex_async import AsyncOpenAlexExtractor
    from sci_etl_core.extractors.pubmed_async import AsyncPubMedExtractor
    from sci_etl_core.extractors.semantic_scholar_async import AsyncSemanticScholarExtractor
