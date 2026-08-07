from __future__ import annotations

import re
from abc import ABC, abstractmethod

import pandas as pd

from sci_etl_core.processors.base import Processor


class KeyNormalizer(ABC):
    @abstractmethod
    def normalize(self, raw_value: str) -> str:
        """Produce a canonical key used to match duplicate records."""


class DefaultKeyNormalizer(KeyNormalizer):
    def normalize(self, raw_value: str) -> str:
        if raw_value is None or pd.isna(raw_value):
            return ""
        return re.sub(r"[^a-z0-9]", "", str(raw_value).strip().lower())


class NormalizationStep(Processor):
    def __init__(self, key_column: str, normalizer: KeyNormalizer, output_column: str = "_norm_key") -> None:
        self._key_column = key_column
        self._normalizer = normalizer
        self._output_column = output_column

    def process(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        frame[self._output_column] = frame[self._key_column].apply(self._normalizer.normalize)
        return frame
