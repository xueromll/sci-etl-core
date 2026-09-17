from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Processor(ABC):
    """Contract for one post-processing step over the exported table."""

    @abstractmethod
    def process(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Transform a dataframe and return the result."""


class ProcessorChain(Processor):
    """Run processor steps in order, each on the previous step's output."""

    def __init__(self, steps: list[Processor]) -> None:
        self._steps = steps

    def process(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return ``frame`` after every step, or ``frame`` itself when there are no steps."""
        for step in self._steps:
            frame = step.process(frame)
        return frame
