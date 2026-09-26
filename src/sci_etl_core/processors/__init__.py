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
    "Plotly3DSink": "sci_etl_core.processors.sinks",
    "SqlTableSink": "sci_etl_core.processors.sinks",
    "TableSink": "sci_etl_core.processors.sinks",
    "QualityFlagStep": "sci_etl_core.processors.quality",
    "ScatterPlotConfig": "sci_etl_core.processors.sinks",
    "RecordValidator": "sci_etl_core.processors.validation",
    "TableLayoutStep": "sci_etl_core.processors.shaping",
    "ValidationResult": "sci_etl_core.processors.validation",
    "ValueClipStep": "sci_etl_core.processors.shaping",
    "Violation": "sci_etl_core.processors.validation",
}

__all__ = list(_EXPORTS)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _EXPORTS)

if TYPE_CHECKING:
    from sci_etl_core.processors.base import Processor, ProcessorChain
    from sci_etl_core.processors.clustering import ClusteringStep, FeatureExtractor
    from sci_etl_core.processors.dedup import DeduplicationStep, NeighborMatcher
    from sci_etl_core.processors.normalization import DefaultKeyNormalizer, KeyNormalizer, NormalizationStep
    from sci_etl_core.processors.quality import CompletenessStep, QualityFlagStep
    from sci_etl_core.processors.shaping import TableLayoutStep, ValueClipStep
    from sci_etl_core.processors.sinks import Plotly3DSink, ScatterPlotConfig, SqlTableSink, TableSink
    from sci_etl_core.processors.validation import (
        CompositeValidator,
        KeywordExclusionValidator,
        NumericRangeValidator,
        RecordValidator,
        ValidationResult,
        Violation,
    )
