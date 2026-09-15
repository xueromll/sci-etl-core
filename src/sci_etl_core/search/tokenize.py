from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from sci_etl_core.search._unicode61_data import FOLD_RUNS, REMOVED_MARKS, SEPARATOR_RANGES

SURROGATE_CODE_POINTS = range(0xD800, 0xE000)
FTS5_MAX_TOKEN_BYTES = 32768


@dataclass(frozen=True, slots=True)
class Token:
    """One word of a text, folded for matching, with where it was written.

    ``start`` and ``end`` are half-open character offsets into the tokenized
    text, so ``text[start:end]`` is the word as written.
    """

    text: str
    start: int
    end: int


class Tokenizer(Protocol):
    """Splits text into the words a search index matches on."""

    def tokens(self, text: str) -> list[Token]:
        """Return the tokens of ``text`` in the order they appear."""


def _token_run_pattern() -> re.Pattern[str]:
    separators = "".join(f"\\U{first:08x}-\\U{last:08x}" for first, last in SEPARATOR_RANGES)
    return re.compile(f"[^{separators}]+")


def _fold_table() -> dict[int, str]:
    table = {mark: "" for mark in REMOVED_MARKS}
    for source, target, length, source_step, target_step in FOLD_RUNS:
        for index in range(length):
            table[source + index * source_step] = chr(target + index * target_step)
    return table


_TOKEN_RUN = _token_run_pattern()
_FOLDS = _fold_table()


class Unicode61Tokenizer:
    """Reproduce FTS5's ``unicode61 remove_diacritics 2`` tokenizer in pure Python.

    A token is a maximal run of letters, numbers, and private-use characters as
    Unicode 6.1 classifies them; every other character separates tokens, so
    ``H-alpha`` gives ``h`` and ``alpha``. Each character is case-folded one to
    one, never with :meth:`str.casefold`, and loses its diacritic: ``Müller``
    gives ``muller`` while ``Straße`` stays ``straße``, exactly as FTS5 indexes
    them. A run whose characters all fold away, such as a lone combining accent,
    gives no token.

    The character tables come from FTS5 itself and are checked against it for
    every code point. Two differences are known:

    - Surrogate code points (:data:`SURROGATE_CODE_POINTS`) are separators here.
      SQLite cannot receive them, so parity cannot be checked.
    - FTS5 truncates an indexed term to :data:`FTS5_MAX_TOKEN_BYTES` bytes of
      UTF-8. This tokenizer never truncates.
    """

    def tokens(self, text: str) -> list[Token]:
        return [
            Token(folded, match.start(), match.end())
            for match in _TOKEN_RUN.finditer(text)
            if (folded := match.group().translate(_FOLDS))
        ]
