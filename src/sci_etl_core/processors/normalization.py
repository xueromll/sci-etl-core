from __future__ import annotations

import unicodedata
from abc import ABC, abstractmethod

import pandas as pd

from sci_etl_core.processors.base import Processor

_KEY_CATEGORY_CLASSES = frozenset({"L", "M", "N", "S"})


class KeyNormalizer(ABC):
    @abstractmethod
    def normalize(self, raw_value: str) -> str:
        """Produce a canonical key used to match duplicate records."""


class DefaultKeyNormalizer(KeyNormalizer):
    def normalize(self, raw_value: str) -> str:
        if raw_value is None or pd.isna(raw_value):
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
    def __init__(self, key_column: str, normalizer: KeyNormalizer, output_column: str = "_norm_key") -> None:
        self._key_column = key_column
        self._normalizer = normalizer
        self._output_column = output_column

    def process(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        frame[self._output_column] = frame[self._key_column].apply(self._normalizer.normalize)
        return frame
