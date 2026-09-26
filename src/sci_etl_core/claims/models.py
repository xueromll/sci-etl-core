from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from sci_etl_core.claims.drafts import ClaimDraft

ClaimKind = Literal["measurement", "assertion"]
Modality = Literal["asserted", "hedged", "speculative"]
Qualifier = Literal["=", "<", "<=", ">", ">=", "~"]
UncertaintyKind = Literal["sd", "se", "ci95", "iqr", "range", "unknown"]

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True, kw_only=True)
class ExtractionStamp:
    """What produced an extracted value: enough to find every value a fix must redo.

    ``model`` is the LLM's name, empty when the client does not report one.
    ``prompt_hash`` and ``schema_hash`` are :func:`content_hash` digests of the
    system prompt and of the JSON Schema the answer had to match, empty when
    there was no schema. ``extractor_version`` names the library release,
    such as ``"sci-etl-core/0.6.0"``.
    """

    model: str
    prompt_hash: str
    schema_hash: str
    extractor_version: str

    def to_dict(self) -> dict[str, str]:
        """Return the stamp as a JSON-friendly mapping."""
        return {
            "model": self.model,
            "prompt_hash": self.prompt_hash,
            "schema_hash": self.schema_hash,
            "extractor_version": self.extractor_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ExtractionStamp:
        """Rebuild a stamp from :meth:`to_dict` output."""
        return cls(
            model=str(data["model"]),
            prompt_hash=str(data["prompt_hash"]),
            schema_hash=str(data["schema_hash"]),
            extractor_version=str(data["extractor_version"]),
        )


def content_hash(value: Any) -> str:
    """Return the SHA-256 hex digest of ``value`` serialized as compact JSON with sorted keys.

    A string is hashed as its JSON string. Equal mappings give equal digests
    whatever their key order, so one schema always has one hash.
    """
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceSpan:
    """The sentence or sentences a claim was read from.

    ``start`` and ``end`` are half-open character offsets into the text the
    model was sent, computed by
    :func:`~sci_etl_core.claims.locate.locate_quote` and snapped to sentence
    boundaries. ``quote`` is the model's exact quote, kept for grounding
    checks.
    """

    record_id: str
    start: int
    end: int
    quote: str

    def __post_init__(self) -> None:
        if not 0 <= self.start <= self.end:
            raise ValueError("EvidenceSpan needs 0 <= start <= end")


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalValue:
    """A normalized value that a downstream engine computed; sci-etl-core stores it and never converts."""

    value: float
    uncertainty: float | None
    unit: str
    dimension: tuple[tuple[str, int], ...]
    kind: str
    conversion_path: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class Quantity:
    """A number as the paper reports it.

    ``verbatim`` is the text the value was read from, such as ``"2.9 ± 0.3
    kpc"``. ``value`` is ``None`` when the text holds no single number.
    """

    verbatim: str
    value: float | None
    unit_text: str
    qualifier: Qualifier = "="
    uncertainty: float | None = None
    uncertainty_kind: UncertaintyKind | None = None
    scale_note: str = ""
    canonical: CanonicalValue | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Statistics:
    """The statistics a paper reports with a claim, each optional."""

    effect_metric: str | None = None
    effect_value: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    p_value: float | None = None
    p_qualifier: Qualifier | None = None
    test_statistic: float | None = None
    test_kind: str | None = None
    degrees_of_freedom: float | None = None
    group_sizes: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ClaimContext:
    """Domain-specific conditions as sorted ``(key, value)`` pairs; sci-etl-core gives keys no meaning."""

    attributes: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_mapping(cls, attributes: Mapping[str, str]) -> ClaimContext:
        """Build a context from a mapping, sorting its pairs."""
        return cls(attributes=tuple(sorted((str(key), str(value)) for key, value in attributes.items())))

    def to_dict(self) -> dict[str, str]:
        """Return the attributes as a mapping."""
        return dict(self.attributes)


@dataclass(frozen=True, slots=True, kw_only=True)
class Claim:
    """One value or statement extracted from a paper, with its evidence and provenance.

    A ``"measurement"`` needs a ``quantity`` and an ``"assertion"`` an
    ``object``. ``polarity`` is ``1`` for a positive statement, ``-1`` for a
    negated one, and ``0`` when it has no direction. ``claim_id`` is
    :func:`make_claim_id` of the identifying fields: the same claim extracted by
    another model has the same id and a different ``stamp``.
    """

    claim_id: str
    kind: ClaimKind
    subject: str
    predicate: str
    span: EvidenceSpan
    stamp: ExtractionStamp
    object: str = ""
    polarity: Literal[-1, 0, 1] = 0
    modality: Modality = "asserted"
    quantity: Quantity | None = None
    statistics: Statistics | None = None
    context: ClaimContext = field(default_factory=ClaimContext)
    confidence: float | None = None

    def __post_init__(self) -> None:
        if self.kind == "measurement" and self.quantity is None:
            raise ValueError("A measurement claim needs a quantity")
        if self.kind == "assertion" and not self.object:
            raise ValueError("An assertion claim needs an object")

    @property
    def record_id(self) -> str:
        """The record the claim was read from."""
        return self.span.record_id

    @classmethod
    def from_draft(cls, draft: ClaimDraft, *, span: EvidenceSpan, stamp: ExtractionStamp) -> Claim:
        """Build a trusted claim from a validated draft, the evidence span code located, and a stamp.

        Raises:
            ValueError: The draft is a measurement without a quantity or an
                assertion without an object.
        """
        quantity = None
        if draft.quantity is not None:
            quantity = Quantity(**draft.quantity.model_dump())
        statistics = None
        if draft.statistics is not None:
            values = draft.statistics.model_dump()
            values["group_sizes"] = tuple(values["group_sizes"])
            statistics = Statistics(**values)
        context = ClaimContext.from_mapping(draft.context)
        identity = make_claim_id(
            record_id=span.record_id,
            kind=draft.kind,
            subject=draft.subject,
            predicate=draft.predicate,
            object=draft.object,
            polarity=draft.polarity,
            context=context,
            quantity=quantity,
            span=span,
            schema_hash=stamp.schema_hash,
        )
        return cls(
            claim_id=identity,
            kind=draft.kind,
            subject=draft.subject,
            predicate=draft.predicate,
            object=draft.object,
            polarity=draft.polarity,
            modality=draft.modality,
            quantity=quantity,
            statistics=statistics,
            context=context,
            confidence=draft.confidence,
            span=span,
            stamp=stamp,
        )

    def to_row(self) -> dict[str, Any]:
        """Return the claim as one flat, JSON-friendly mapping, the shape every store and table uses."""
        return {
            "claim_id": self.claim_id,
            "record_id": self.span.record_id,
            "kind": self.kind,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "polarity": self.polarity,
            "modality": self.modality,
            "confidence": self.confidence,
            "quantity": None if self.quantity is None else _quantity_dict(self.quantity),
            "statistics": None if self.statistics is None else _statistics_dict(self.statistics),
            "context": self.context.to_dict(),
            "span_start": self.span.start,
            "span_end": self.span.end,
            "quote": self.span.quote,
            "stamp": self.stamp.to_dict(),
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Claim:
        """Rebuild a claim from :meth:`to_row` output."""
        quantity = None if row["quantity"] is None else _quantity(row["quantity"])
        statistics = None
        if row["statistics"] is not None:
            values = dict(row["statistics"])
            values["group_sizes"] = tuple(values.get("group_sizes", ()))
            statistics = Statistics(**values)
        return cls(
            claim_id=row["claim_id"],
            kind=row["kind"],
            subject=row["subject"],
            predicate=row["predicate"],
            object=row["object"],
            polarity=row["polarity"],
            modality=row["modality"],
            confidence=row["confidence"],
            quantity=quantity,
            statistics=statistics,
            context=ClaimContext.from_mapping(row["context"]),
            span=EvidenceSpan(
                record_id=row["record_id"], start=row["span_start"], end=row["span_end"], quote=row["quote"]
            ),
            stamp=ExtractionStamp.from_dict(row["stamp"]),
        )


def make_claim_id(
    *,
    record_id: str,
    kind: str,
    subject: str,
    predicate: str,
    object: str,
    polarity: int,
    context: ClaimContext,
    quantity: Quantity | None,
    span: EvidenceSpan,
    schema_hash: str,
) -> str:
    """Return a claim's id: a digest of the fields that make it one claim.

    The id covers the record, kind, subject, predicate, object, polarity,
    context, the quantity's verbatim text with whitespace removed, the span
    offsets, and the schema hash. It leaves out the model, prompt, and library
    version, so re-extracting a paper with another model keeps every id whose
    fields match. Mentions are compared exactly: ``"DF44"`` and ``"DF 44"`` are
    different subjects.
    """
    verbatim = None if quantity is None else _WHITESPACE.sub("", quantity.verbatim)
    return content_hash(
        [
            record_id,
            kind,
            subject,
            predicate,
            object,
            polarity,
            [list(pair) for pair in context.attributes],
            verbatim,
            span.start,
            span.end,
            schema_hash,
        ]
    )


def _quantity_dict(quantity: Quantity) -> dict[str, Any]:
    values = asdict(quantity)
    if quantity.canonical is not None:
        values["canonical"]["dimension"] = [list(pair) for pair in quantity.canonical.dimension]
        values["canonical"]["conversion_path"] = list(quantity.canonical.conversion_path)
    return values


def _quantity(values: Mapping[str, Any]) -> Quantity:
    data = dict(values)
    canonical = data.pop("canonical", None)
    if canonical is not None:
        canonical = CanonicalValue(
            value=canonical["value"],
            uncertainty=canonical["uncertainty"],
            unit=canonical["unit"],
            dimension=tuple((str(name), int(power)) for name, power in canonical["dimension"]),
            kind=canonical["kind"],
            conversion_path=tuple(canonical["conversion_path"]),
        )
    return Quantity(**data, canonical=canonical)


def _statistics_dict(statistics: Statistics) -> dict[str, Any]:
    values = asdict(statistics)
    values["group_sizes"] = list(statistics.group_sizes)
    return values
