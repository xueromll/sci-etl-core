from __future__ import annotations

import unicodedata
from abc import ABC, abstractmethod
from itertools import groupby
from typing import Any


class RecordValidator(ABC):
    """Contract for a domain rule that decides whether an extracted entity is kept."""

    @abstractmethod
    def is_valid(self, record: dict[str, Any]) -> bool:
        """Return whether a raw extracted record should be kept."""


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
        value = str(record.get(self._key_field, "")).strip().lower()
        if value in _NULL_LIKE_VALUES:
            return False
        tokens = self._tokenize(value)
        return not any(
            tokens[start : start + length] in self._forbidden_phrases
            for length in self._phrase_lengths
            for start in range(len(tokens) - length + 1)
        )

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
        for field_name, (low, high) in self._field_ranges.items():
            value = record.get(field_name)
            if value is None:
                continue
            try:
                if not (low <= float(value) <= high):
                    return False
            except (TypeError, ValueError):
                return False
        return True


class CompositeValidator(RecordValidator):
    """Keep an entity only when every validator keeps it."""

    def __init__(self, validators: list[RecordValidator]) -> None:
        self._validators = validators

    def is_valid(self, record: dict[str, Any]) -> bool:
        """Return whether all validators accept ``record``, stopping at the first rejection."""
        return all(validator.is_valid(record) for validator in self._validators)
