from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any


class RecordValidator(ABC):
    @abstractmethod
    def is_valid(self, record: dict[str, Any]) -> bool:
        """Return whether a raw extracted record should be kept."""


_TOKEN_SPLIT_PATTERN = re.compile(r"[^a-z]+")
_NULL_LIKE_VALUES = frozenset({"null", "none", "unknown", "n/a", "nan", ""})


class KeywordExclusionValidator(RecordValidator):
    def __init__(self, key_field: str, forbidden_keywords: list[str]) -> None:
        self._key_field = key_field
        self._forbidden = frozenset(
            token for keyword in forbidden_keywords for token in self._tokenize(keyword)
        )

    def is_valid(self, record: dict[str, Any]) -> bool:
        value = str(record.get(self._key_field, "")).strip().lower()
        if value in _NULL_LIKE_VALUES:
            return False
        return self._forbidden.isdisjoint(self._tokenize(value))

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return {token for token in _TOKEN_SPLIT_PATTERN.split(text.lower()) if token}


class NumericRangeValidator(RecordValidator):
    def __init__(self, field_ranges: dict[str, tuple[float, float]]) -> None:
        self._field_ranges = field_ranges

    def is_valid(self, record: dict[str, Any]) -> bool:
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
    def __init__(self, validators: list[RecordValidator]) -> None:
        self._validators = validators

    def is_valid(self, record: dict[str, Any]) -> bool:
        return all(validator.is_valid(record) for validator in self._validators)
