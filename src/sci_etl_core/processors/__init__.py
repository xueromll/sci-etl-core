from __future__ import annotations

from typing import TYPE_CHECKING

from sci_etl_core._lazy import lazy_exports

_EXPORTS: dict[str, str] = {
    "ClusteringStep": "sci_etl_core.processors.clustering",
    "CompletenessStep": "sci_etl_core.processors.quality",
    "CompositeValidator": "sci_etl_core.processors.validation",
    "DeduplicationStep": "sci_etl_core.processors.dedup",
    "DefaultKeyNormalizer": "sci_etl_core.processors.normalization",
    "FeatureExtractor": "sci_etl_core.processors.clustering",
    "KeyNormalizer": "sci_etl_core.processors.normalization",
    "KeywordExclusionValidator": "sci_etl_core.processors.validation",
    "NeighborMatcher": "sci_etl_core.processors.dedup",
    "NormalizationStep": "sci_etl_core.processors.normalization",
    "NumericRangeValidator": "sci_etl_core.processors.validation",
    "Processor": "sci_etl_core.processors.base",
    "ProcessorChain": "sci_etl_core.processors.base",
    "QualityFlagStep": "sci_etl_core.processors.quality",
    "RecordValidator": "sci_etl_core.processors.validation",
}

__all__ = list(_EXPORTS)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _EXPORTS)

if TYPE_CHECKING:
    from sci_etl_core.processors.clustering import ClusteringStep
    from sci_etl_core.processors.quality import CompletenessStep
    from sci_etl_core.processors.validation import CompositeValidator
    from sci_etl_core.processors.dedup import DeduplicationStep
    from sci_etl_core.processors.normalization import DefaultKeyNormalizer
    from sci_etl_core.processors.clustering import FeatureExtractor
    from sci_etl_core.processors.normalization import KeyNormalizer
    from sci_etl_core.processors.validation import KeywordExclusionValidator
    from sci_etl_core.processors.dedup import NeighborMatcher
    from sci_etl_core.processors.normalization import NormalizationStep
    from sci_etl_core.processors.validation import NumericRangeValidator
    from sci_etl_core.processors.base import Processor
    from sci_etl_core.processors.base import ProcessorChain
    from sci_etl_core.processors.quality import QualityFlagStep
    from sci_etl_core.processors.validation import RecordValidator
