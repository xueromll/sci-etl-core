from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class QuantityDraft(BaseModel):
    """A number as the model reads it from the paper."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verbatim: str = Field(description="The value exactly as the paper writes it, with its unit")
    value: float | None = Field(default=None, description="The number, or null when the text holds no single number")
    unit_text: str = Field(default="", description="The unit exactly as the paper writes it")
    qualifier: Literal["=", "<", "<=", ">", ">=", "~"] = "="
    uncertainty: float | None = None
    uncertainty_kind: Literal["sd", "se", "ci95", "iqr", "range", "unknown"] | None = None
    scale_note: str = Field(default="", description="A factor the paper applies, such as 'x 10^8'")


class StatisticsDraft(BaseModel):
    """Statistics the model reads next to a claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    effect_metric: str | None = None
    effect_value: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    p_value: float | None = None
    p_qualifier: Literal["=", "<", "<=", ">", ">=", "~"] | None = None
    test_statistic: float | None = None
    test_kind: str | None = None
    degrees_of_freedom: float | None = None
    group_sizes: list[int] = Field(default_factory=list)


class ClaimDraft(BaseModel):
    """What the model returns for one claim; validated once, then turned into a claim.

    :meth:`~sci_etl_core.claims.models.Claim.from_draft` builds the claim.
    ``quote`` is the sentence the claim was read from, copied from the paper.
    The model never supplies ids, offsets, or provenance; code computes them.
    Subclass it to narrow ``predicate`` or the context keys for a field of
    science, and pass the subclass as the claim extractor's ``schema``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["measurement", "assertion"]
    subject: str = Field(description="What the claim is about, as the paper names it")
    predicate: str = Field(description="The property measured or the relation asserted")
    object: str = Field(default="", description="For an assertion, what the subject is related to")
    polarity: Literal[-1, 0, 1] = 0
    modality: Literal["asserted", "hedged", "speculative"] = "asserted"
    quantity: QuantityDraft | None = None
    statistics: StatisticsDraft | None = None
    context: dict[str, str] = Field(default_factory=dict, description="Conditions such as band or sample")
    quote: str = Field(description="The sentence the claim was read from, copied exactly")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
