from __future__ import annotations

import unicodedata
from abc import ABC, abstractmethod
from typing import Any

import pandas as pd
from pandas.api.types import is_scalar

from sci_etl_core.processors.base import Processor

_KEY_CATEGORY_CLASSES = frozenset({"L", "M", "N", "S"})


class KeyNormalizer(ABC):
    """Contract for mapping an entity's name to the key its duplicates share."""

    @abstractmethod
    def normalize(self, raw_value: Any) -> str:
        """Produce a canonical key used to match duplicate records.

        Returns ``""`` when no key can be formed; callers treat an empty key as
        "no identity" and never match on it.
        """


class DefaultKeyNormalizer(KeyNormalizer):
    """Domain-agnostic key: case, width, spacing, and punctuation differences are ignored."""

    def normalize(self, raw_value: Any) -> str:
        """Casefold and NFKC-fold a value, keeping letters, marks, numbers and symbols.

        Missing values and containers such as lists or dicts cannot form a key
        and normalize to ``""``.
        """
        if raw_value is None or not is_scalar(raw_value) or pd.isna(raw_value):
            return ""
        folded = unicodedata.normalize(
            "NFKC", unicodedata.normalize("NFKC", str(raw_value)).casefold()
        )
        kept = "".join(
            character
            for character in folded
            if unicodedata.category(character)[0] in _KEY_CATEGORY_CLASSES
        )
        return unicodedata.normalize("NFC", kept)


class NormalizationStep(Processor):
    """Add ``output_column`` holding ``normalizer``'s key for each row's ``key_column`` value."""

    def __init__(self, key_column: str, normalizer: KeyNormalizer, output_column: str = "_norm_key") -> None:
        self._key_column = key_column
        self._normalizer = normalizer
        self._output_column = output_column

    def process(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return a copy of ``frame`` with the key column added.

        Raises:
            KeyError: ``frame`` has no ``key_column``.
        """
        frame = frame.copy()
        frame[self._output_column] = frame[self._key_column].apply(self._normalizer.normalize)
        return frame
