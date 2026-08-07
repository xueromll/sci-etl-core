from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

from sci_etl_core.processors.base import Processor


class FeatureExtractor(ABC):
    @abstractmethod
    def extract(self, frame: pd.DataFrame) -> tuple[np.ndarray, pd.Index]:
        """Return a feature matrix and the row index it corresponds to."""


class ClusteringStep(Processor):
    def __init__(
        self,
        feature_extractor: FeatureExtractor,
        output_column: str = "cluster_id",
        eps: float = 1.0,
        min_samples: int = 2,
    ) -> None:
        self._feature_extractor = feature_extractor
        self._output_column = output_column
        self._eps = eps
        self._min_samples = min_samples

    def process(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        frame[self._output_column] = -1

        features, valid_index = self._feature_extractor.extract(frame)
        if len(valid_index) < self._min_samples:
            return frame

        labels = DBSCAN(eps=self._eps, min_samples=self._min_samples).fit_predict(features)
        frame.loc[valid_index, self._output_column] = labels
        return frame
