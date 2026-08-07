from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Processor(ABC):
    @abstractmethod
    def process(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Transform a dataframe and return the result."""


class ProcessorChain(Processor):
    def __init__(self, steps: list[Processor]) -> None:
        self._steps = steps

    def process(self, frame: pd.DataFrame) -> pd.DataFrame:
        for step in self._steps:
            frame = step.process(frame)
        return frame
