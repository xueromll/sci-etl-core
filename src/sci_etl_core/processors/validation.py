from __future__ import annotations

import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass
from itertools import groupby
from typing import Any, Literal


@dataclass(frozen=True, slots=True, kw_only=True)
class Violation:
    """One reason a validator gives for rejecting, or warning about, an entity.

    ``code`` is a short machine-readable rule name such as ``"out-of-range"``,
    ``field`` is the entity key it concerns, or ``None`` when it concerns the
    entity as a whole, and ``message`` is a sentence a reviewer can read.
    """

    code: str
    field: str | None
    severity: Literal["error", "warning"]
    message: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationResult:
    """Every violation a validator found in one entity."""

    violations: tuple[Violation, ...] = ()

    @property
    def ok(self) -> bool:
        """Whether no violation has ``severity == "error"``."""
        return not any(violation.severity == "error" for violation in self.violations)


class RecordValidator(ABC):
    """Contract for a domain rule that decides whether an extracted entity is kept.

    :meth:`is_valid` answers yes or no, and :meth:`validate` also says why.
    :class:`~sci_etl_core.llm.extraction_async.AsyncLLMEntityExtractor` calls
    :meth:`validate`. A validator that overrides only :meth:`is_valid` keeps
    working, because the default :meth:`validate` turns its rejection into one
    violation.
    """

    @abstractmethod
    def is_valid(self, record: dict[str, Any]) -> bool:
        """Return whether a raw extracted record should be kept."""

    def validate(self, record: dict[str, Any]) -> ValidationResult:
        """Return every reason ``record`` is rejected.

        The default wraps :meth:`is_valid`: a rejection becomes one
        :class:`Violation` with code ``"rejected"``, no field, and the
        validator's class name in the message. Override it to name the field
        and the rule. An override must reject exactly the records
        :meth:`is_valid` rejects.
        """
        if self.is_valid(record):
            return ValidationResult()
        return _rejected(code="rejected", field=None, message=f"Rejected by {type(self).__name__}")


def _rejected(*, code: str, field: str | None, message: str) -> ValidationResult:
    return ValidationResult(violations=(Violation(code=code, field=field, severity="error", message=message),))


_LETTER_CATEGORY_CLASSES = frozenset({"L", "M"})
_NUMBER_CATEGORY_CLASS = "N"
_NULL_LIKE_VALUES = frozenset({"null", "none", "unknown", "n/a", "nan", ""})


def _token_kind(character: str) -> str | None:
    category_class = unicodedata.category(character)[0]
    if category_class in _LETTER_CATEGORY_CLASSES:
        return "letter"
    if category_class == _NUMBER_CATEGORY_CLASS:
        return "number"
    return None


class KeywordExclusionValidator(RecordValidator):
    """Reject an entity whose ``key_field`` is null-like or contains a forbidden keyword as whole words."""

    def __init__(self, key_field: str, forbidden_keywords: list[str]) -> None:
        self._key_field = key_field
        self._forbidden_phrases = frozenset(
            phrase for phrase in map(self._tokenize, forbidden_keywords) if phrase
        )
        self._phrase_lengths = frozenset(len(phrase) for phrase in self._forbidden_phrases)

    def is_valid(self, record: dict[str, Any]) -> bool:
        """Return ``False`` for a missing, empty, or null-like key, or one containing a forbidden phrase.

        Null-like values are ``null``, ``none``, ``unknown``, ``n/a``, and
        ``nan``, in any case. Keys and keywords are split into runs of letters
        and runs of numbers after NFKC case folding, and a keyword matches only
        a contiguous sequence of whole runs, so ``"star"`` never matches
        ``"starburst"``.
        """
        return self.validate(record).ok

    def validate(self, record: dict[str, Any]) -> ValidationResult:
        """Name the rule a rejected key broke: ``"null-key"`` or ``"forbidden-keyword"``."""
        value = str(record.get(self._key_field, "")).strip().lower()
        if value in _NULL_LIKE_VALUES:
            return _rejected(
                code="null-key", field=self._key_field, message=f"{self._key_field} is missing, empty, or null-like"
            )
        tokens = self._tokenize(value)
        for length in sorted(self._phrase_lengths):
            for start in range(len(tokens) - length + 1):
                phrase = tokens[start : start + length]
                if phrase in self._forbidden_phrases:
                    return _rejected(
                        code="forbidden-keyword",
                        field=self._key_field,
                        message=f"{self._key_field} contains the forbidden keyword {' '.join(phrase)!r}",
                    )
        return ValidationResult()

    @staticmethod
    def _tokenize(text: str) -> tuple[str, ...]:
        folded = unicodedata.normalize("NFKC", str(text)).casefold()
        return tuple(
            "".join(run) for kind, run in groupby(folded, key=_token_kind) if kind is not None
        )


class NumericRangeValidator(RecordValidator):
    """Reject an entity whose value for a field lies outside that field's inclusive range."""

    def __init__(self, field_ranges: dict[str, tuple[float, float]]) -> None:
        self._field_ranges = field_ranges

    def is_valid(self, record: dict[str, Any]) -> bool:
        """Return ``False`` when a present value is out of range or cannot be read as a number.

        A missing or ``None`` value passes, so completeness is left to other
        steps.
        """
        return self.validate(record).ok

    def validate(self, record: dict[str, Any]) -> ValidationResult:
        """Report every field whose value is ``"not-a-number"`` or ``"out-of-range"``."""
        violations: list[Violation] = []
        for field_name, (low, high) in self._field_ranges.items():
            value = record.get(field_name)
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                violations.append(
                    Violation(
                        code="not-a-number", field=field_name, severity="error", message=f"{field_name} is not a number"
                    )
                )
                continue
            if not (low <= number <= high):
                violations.append(
                    Violation(
                        code="out-of-range",
                        field=field_name,
                        severity="error",
                        message=f"{field_name} is {number:g}, outside [{low:g}, {high:g}]",
                    )
                )
        return ValidationResult(violations=tuple(violations))


class CompositeValidator(RecordValidator):
    """Keep an entity only when every validator keeps it."""

    def __init__(self, validators: list[RecordValidator]) -> None:
        self._validators = validators

    def is_valid(self, record: dict[str, Any]) -> bool:
        """Return whether all validators accept ``record``, stopping at the first rejection."""
        return all(validator.is_valid(record) for validator in self._validators)

    def validate(self, record: dict[str, Any]) -> ValidationResult:
        """Collect every validator's violations, in order, without stopping at the first rejection."""
        return ValidationResult(
            violations=tuple(
                violation for validator in self._validators for violation in validator.validate(record).violations
            )
        )
