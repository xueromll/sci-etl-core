"""The stable public surface of sci-etl-core, rendered as text.

``STABLE`` lists the stable tier of ``release-plan.md`` §7.2 by the module a
caller imports each name from, plus every name a known consumer imports or
subclasses (``consumer_surface.txt``). :func:`render_surface` writes one line
per class, dataclass field list, method, property, function, and constant, so
a diff of ``public_surface.txt`` shows every change to that surface.
"""

from __future__ import annotations

import dataclasses
import enum
import importlib
import inspect
import re
import types
import typing
from collections.abc import Callable, Iterator
from importlib.metadata import version
from pathlib import Path
from typing import Any

SNAPSHOT = Path(__file__).with_name("public_surface.txt")
CONSUMER_SURFACE = Path(__file__).with_name("consumer_surface.txt")
PACKAGE = "sci_etl_core"

STABLE: dict[str, tuple[str, ...]] = {
    "sci_etl_core": (
        "AsyncArxivExtractor",
        "AsyncCompositeIngestor",
        "AsyncCsvUpsertExporter",
        "AsyncETLPipeline",
        "AsyncEmbeddingRelevanceFilter",
        "AsyncEntityExtractor",
        "AsyncExporter",
        "AsyncExtractor",
        "AsyncFileStateManager",
        "AsyncLLMClient",
        "AsyncLLMEntityExtractor",
        "AsyncLLMRelevanceFilter",
        "AsyncLLMResponseCache",
        "AsyncOpenAICompatibleClient",
        "AsyncOpenAlexExtractor",
        "AsyncRelevanceFilter",
        "AsyncSqliteLLMResponseCache",
        "AsyncSqliteStateManager",
        "AsyncStateManager",
        "BaseAppConfig",
        "CachingLLMClient",
        "ConfigurationError",
        "EmbeddingError",
        "EmbeddingStoreError",
        "ExtractionError",
        "HttpConfig",
        "InMemoryLLMResponseCache",
        "LLMCacheError",
        "LLMConfig",
        "LLMError",
        "MEMORY_FAULTS",
        "MalformedResponseError",
        "MemoryIngestor",
        "ParsingError",
        "Parser",
        "PipelineAborted",
        "PipelineConfig",
        "PipelineInterrupted",
        "PipelineMetadata",
        "Processor",
        "ProcessorChain",
        "RateLimitConfig",
        "RawRecord",
        "RunMetrics",
        "SciEtlError",
        "SearchConfig",
        "SearchError",
        "SearchQueryError",
        "SearchStoreError",
        "ShutdownSignal",
        "TableParser",
        "TokenUsage",
        "UpstreamError",
        "configure_logging",
        "load_config",
    ),
    "sci_etl_core.config": (
        "BM25WeightsConfig",
        "FusionConfig",
        "GraphConfig",
        "HybridConfig",
        "apply_api_key",
        "load_yaml",
        "validate_config",
    ),
    "sci_etl_core.discovery": ("DiscoveryResult", "Facet"),
    "sci_etl_core.embeddings": (
        "AsyncChunkIngestor",
        "AsyncEmbedder",
        "AsyncEmbeddingStore",
        "AsyncOpenAIEmbedder",
        "AsyncSentenceTransformerEmbedder",
        "AsyncSimilarArticleFinder",
        "AsyncSqliteEmbeddingStore",
        "SlidingWindowChunker",
    ),
    "sci_etl_core.http_async": ("build_async_client",),
    "sci_etl_core.llm": ("CacheStats", "response_cache_key"),
    "sci_etl_core.observability": (
        "PageFetched",
        "PageFinished",
        "PipelineEvent",
        "RecordFinished",
        "RecordOutcome",
        "RunFinished",
        "RunStarted",
    ),
    "sci_etl_core.parsers": (
        "HtmlTextParser",
        "JatsArticle",
        "JatsSection",
        "JatsXmlParser",
        "LatexTarballParser",
        "PdfPlumberParser",
        "trim_after_references",
    ),
    "sci_etl_core.processors": (
        "ClusteringStep",
        "CompletenessStep",
        "DeduplicationStep",
        "DefaultKeyNormalizer",
        "FeatureExtractor",
        "KeyNormalizer",
        "KeywordExclusionValidator",
        "NeighborMatcher",
        "NormalizationStep",
        "QualityFlagStep",
        "RecordValidator",
        "TableLayoutStep",
        "ValueClipStep",
    ),
    "sci_etl_core.search": (
        "AsyncEdgeSource",
        "AsyncHybridSearcher",
        "AsyncSearchIndexer",
        "AsyncSqliteFts5Store",
        "AsyncTextSearchStore",
        "DiscoveryGraph",
        "EmbeddingEdgeSource",
        "FusedHit",
        "GraphEdge",
        "GraphNode",
        "MetadataEdgeSource",
        "MetadataFilter",
        "QueryChip",
        "RangeFilter",
        "SearchDocument",
        "SearchFilter",
        "SearchMode",
        "Snippet",
        "build_discovery_graph",
        "describe",
        "filter_graph",
        "parse_query",
    ),
}

PUBLIC_DUNDERS = frozenset(
    {
        "__init__",
        "__call__",
        "__aenter__",
        "__aexit__",
        "__aiter__",
        "__anext__",
        "__enter__",
        "__exit__",
        "__add__",
        "__sub__",
        "__iter__",
        "__len__",
        "__contains__",
        "__getitem__",
    }
)
_ADDRESS = re.compile(r" at 0x[0-9A-Fa-f]+")


def stable_objects() -> Iterator[tuple[str, Any]]:
    for module_name, names in STABLE.items():
        module = importlib.import_module(module_name)
        for name in names:
            yield f"{module_name}.{name}", getattr(module, name)


def resolve(dotted: str) -> Any:
    parts = dotted.split(".")
    for split in range(len(parts) - 1, 0, -1):
        try:
            value: Any = importlib.import_module(".".join(parts[:split]))
        except ModuleNotFoundError:
            continue
        for attribute in parts[split:]:
            value = getattr(value, attribute)
        return value
    raise ModuleNotFoundError(dotted)


def consumer_names() -> list[str]:
    lines = CONSUMER_SURFACE.read_text(encoding="utf-8").splitlines()
    return [line.split("\t", 1)[0] for line in lines if line.strip()]


def _qualified(value: Any) -> str:
    module = getattr(value, "__module__", "")
    name = getattr(value, "__qualname__", getattr(value, "__name__", repr(value)))
    return name if module in ("builtins", "") else f"{module}.{name}"


def describe_value(value: Any) -> str:
    if isinstance(value, str):
        return repr(value.replace(version("sci-etl-core"), "<version>"))
    if isinstance(value, enum.Enum):
        return f"{type(value).__name__}.{value.name}"
    if isinstance(value, (bool, int, float, complex, bytes)) or value is None:
        return repr(value)
    if isinstance(value, (set, frozenset)):
        items = ", ".join(sorted(describe_value(item) for item in value))
        return f"{type(value).__name__}({{{items}}})"
    if isinstance(value, tuple):
        items = ", ".join(describe_value(item) for item in value)
        return f"({items},)" if len(value) == 1 else f"({items})"
    if isinstance(value, list):
        return "[" + ", ".join(describe_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{describe_value(k)}: {describe_value(v)}" for k, v in value.items()) + "}"
    origin = typing.get_origin(value)
    if origin is typing.Union or origin is types.UnionType:
        return " | ".join(describe_annotation(argument) for argument in typing.get_args(value))
    if origin is typing.Literal:
        return "Literal[" + ", ".join(describe_value(argument) for argument in typing.get_args(value)) + "]"
    if inspect.isclass(value) or inspect.isroutine(value):
        return _qualified(value)
    return _ADDRESS.sub("", repr(value))


def describe_annotation(annotation: Any) -> str:
    if isinstance(annotation, str):
        return annotation
    if annotation is type(None):
        return "None"
    if inspect.isclass(annotation) and typing.get_origin(annotation) is None:
        return _qualified(annotation)
    return describe_value(annotation)


def describe_signature(function: Callable[..., Any]) -> str:
    signature = inspect.signature(function)
    rendered: list[str] = []
    marked_keyword_only = False
    for parameter in signature.parameters.values():
        if parameter.kind is parameter.KEYWORD_ONLY and not marked_keyword_only:
            rendered.append("*")
            marked_keyword_only = True
        text = parameter.name
        if parameter.kind is parameter.VAR_POSITIONAL:
            text = f"*{text}"
            marked_keyword_only = True
        elif parameter.kind is parameter.VAR_KEYWORD:
            text = f"**{text}"
        if parameter.annotation is not parameter.empty:
            text += f": {describe_annotation(parameter.annotation)}"
        if parameter.default is not parameter.empty:
            text += f" = {describe_value(parameter.default)}"
        rendered.append(text)
        if parameter.kind is parameter.POSITIONAL_ONLY:
            following = list(signature.parameters.values())
            index = following.index(parameter)
            if index + 1 == len(following) or following[index + 1].kind is not parameter.POSITIONAL_ONLY:
                rendered.append("/")
    result = f"({', '.join(rendered)})"
    if signature.return_annotation is not signature.empty:
        result += f" -> {describe_annotation(signature.return_annotation)}"
    return result


def _annotations(cls: type) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for klass in reversed(cls.__mro__):
        merged.update(inspect.get_annotations(klass))
    return merged


def _field_list(fields: list[tuple[str, Any, str | None]]) -> str:
    rendered = []
    for name, annotation, default in fields:
        text = f"{name}: {describe_annotation(annotation)}"
        rendered.append(text if default is None else f"{text} = {default}")
    return ", ".join(rendered)


def _dataclass_fields(cls: type) -> str:
    fields = []
    for field in dataclasses.fields(cls):
        if field.default is not dataclasses.MISSING:
            default: str | None = describe_value(field.default)
        elif field.default_factory is not dataclasses.MISSING:
            default = "..."
        else:
            default = None
        name = field.name if field.init else f"{field.name} (not in __init__)"
        fields.append((name, field.type, default))
    return _field_list(fields)


def _pydantic_fields(cls: type) -> str:
    annotations = _annotations(cls)
    fields = []
    for name, info in cls.model_fields.items():  # type: ignore[attr-defined]
        if not info.is_required() and info.default_factory is None:
            default: str | None = describe_value(info.default)
        elif info.default_factory is not None:
            default = "..."
        else:
            default = None
        fields.append((name, annotations.get(name, info.annotation), default))
    extra = cls.model_config.get("extra")  # type: ignore[attr-defined]
    suffix = f" [extra={extra}]" if extra else ""
    return _field_list(fields) + suffix


def _owner(cls: type, name: str) -> type | None:
    for klass in cls.__mro__:
        if name in klass.__dict__:
            return klass
    return None


def _is_core(value: Any) -> bool:
    module = getattr(value, "__module__", "") or ""
    return module == PACKAGE or module.startswith(f"{PACKAGE}.")


def _field_names(cls: type) -> set[str]:
    if dataclasses.is_dataclass(cls):
        return {field.name for field in dataclasses.fields(cls)}
    if hasattr(cls, "model_fields"):
        return {*cls.model_fields, "model_config"}  # type: ignore[attr-defined]
    return set(getattr(cls, "_fields", ()))


def _member_lines(path: str, cls: type, skip_init: bool) -> Iterator[str]:
    fields = _field_names(cls)
    for name in sorted(dir(cls)):
        if name.startswith("_") and name not in PUBLIC_DUNDERS:
            continue
        if (name == "__init__" and skip_init) or name in fields:
            continue
        owner = _owner(cls, name)
        if owner is None or not _is_core(owner):
            continue
        raw = owner.__dict__[name]
        member = f"{path}.{name}"
        if isinstance(raw, property):
            getter = raw.fget
            returned = inspect.signature(getter).return_annotation if getter else inspect.Signature.empty
            kind = "property" if raw.fset is None else "settable property"
            abstract = "abstract " if getattr(raw, "__isabstractmethod__", False) else ""
            annotation = "" if returned is inspect.Signature.empty else f" -> {describe_annotation(returned)}"
            yield f"{abstract}{kind} {member}{annotation}"
        elif isinstance(raw, (staticmethod, classmethod)):
            kind = "staticmethod" if isinstance(raw, staticmethod) else "classmethod"
            function = raw.__func__
            prefix = "async " if inspect.iscoroutinefunction(function) else ""
            yield f"{prefix}{kind} {member}{describe_signature(function)}"
        elif inspect.isfunction(raw):
            prefix = "abstract " if getattr(raw, "__isabstractmethod__", False) else ""
            prefix += "async " if inspect.iscoroutinefunction(raw) or inspect.isasyncgenfunction(raw) else ""
            yield f"{prefix}def {member}{describe_signature(raw)}"
        elif not callable(raw) and not inspect.ismemberdescriptor(raw) and not inspect.isgetsetdescriptor(raw):
            yield f"{member} = {describe_value(raw)}"


def _class_lines(path: str, cls: type) -> Iterator[str]:
    bases = ", ".join(_qualified(base) for base in cls.__bases__ if base is not object)
    abstract = "abstract " if inspect.isabstract(cls) else ""
    yield f"{abstract}class {path}({bases})"
    if dataclasses.is_dataclass(cls):
        yield f"{path}: {_dataclass_fields(cls)}"
        yield from _member_lines(path, cls, skip_init=True)
    elif hasattr(cls, "model_fields"):
        yield f"{path}: {_pydantic_fields(cls)}"
        yield from _member_lines(path, cls, skip_init=True)
    elif issubclass(cls, tuple) and hasattr(cls, "_fields"):
        defaults = cls._field_defaults  # type: ignore[attr-defined]
        annotations = _annotations(cls)
        fields = [
            (name, annotations.get(name, Any), describe_value(defaults[name]) if name in defaults else None)
            for name in cls._fields  # type: ignore[attr-defined]
        ]
        yield f"{path}: {_field_list(fields)}"
        yield from _member_lines(path, cls, skip_init=True)
    else:
        yield from _member_lines(path, cls, skip_init=False)


def describe(path: str, value: Any) -> Iterator[str]:
    if inspect.isclass(value):
        yield from _class_lines(path, value)
    elif inspect.isroutine(value):
        prefix = "async " if inspect.iscoroutinefunction(value) else ""
        yield f"{prefix}def {path}{describe_signature(value)}"
    else:
        yield f"{path} = {describe_value(value)}"


def render_surface() -> str:
    lines: list[str] = []
    for path, value in sorted(stable_objects()):
        lines.extend(describe(path, value))
    return "\n".join(lines) + "\n"
