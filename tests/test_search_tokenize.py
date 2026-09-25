from __future__ import annotations

import sys

import pytest

from sci_etl_core.search.tokenize import (
    FTS5_MAX_TOKEN_BYTES,
    SURROGATE_CODE_POINTS,
    Token,
    Unicode61Tokenizer,
)

TOKENIZER = Unicode61Tokenizer()
BLOCK_SIZE = 512


def words(text: str) -> list[str]:
    return [token.text for token in TOKENIZER.tokens(text)]


def test_every_code_point_tokenizes_as_fts5_does(fts5_terms):
    code_points = [code_point for code_point in range(sys.maxunicode + 1) if code_point not in SURROGATE_CODE_POINTS]
    blocks = [
        "".join(f"x{chr(code_point)}x " for code_point in code_points[start : start + BLOCK_SIZE])
        for start in range(0, len(code_points), BLOCK_SIZE)
    ]
    expected = fts5_terms(blocks)
    diverging_blocks = [
        f"U+{ord(block[1]):04X}" for block, terms in zip(blocks, expected, strict=True) if words(block) != terms
    ]
    assert diverging_blocks == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Müller's H-alpha", ["muller", "s", "h", "alpha"]),
        ("z~0.5", ["z", "0", "5"]),
        ("nothing\x02here", ["nothing", "here"]),
        ("Straße STRASSE", ["straße", "strasse"]),
        ("naïve Ångström", ["naive", "angstrom"]),
        ("Méne", ["mene"]),
        ("a ́́ b", ["a", "b"]),
        ("ab\x00cd", ["ab", "cd"]),
        ("", []),
        (" \t\n", []),
    ],
)
def test_examples_agree_with_fts5(text, expected, fts5_terms):
    assert words(text) == expected
    assert fts5_terms([text]) == [expected]


class TestOffsets:
    def test_each_token_spans_the_word_as_written(self):
        assert TOKENIZER.tokens("Müller's H-alpha") == [
            Token("muller", 0, 6),
            Token("s", 7, 8),
            Token("h", 9, 10),
            Token("alpha", 11, 16),
        ]

    def test_a_combining_accent_stays_inside_its_word_span(self):
        assert TOKENIZER.tokens("Méne x") == [Token("mene", 0, 5), Token("x", 6, 7)]

    def test_a_word_of_accents_alone_takes_no_span(self):
        assert TOKENIZER.tokens("a ́́ b") == [Token("a", 0, 1), Token("b", 5, 6)]


class TestRecordedDivergences:
    def test_sqlite_cannot_receive_a_surrogate(self, fts5_terms):
        with pytest.raises(UnicodeEncodeError):
            fts5_terms([f"a{chr(SURROGATE_CODE_POINTS[0])}b"])

    def test_a_surrogate_separates_tokens(self):
        first, last = chr(SURROGATE_CODE_POINTS[0]), chr(SURROGATE_CODE_POINTS[-1])
        assert words(f"a{first}b{last}c") == ["a", "b", "c"]

    def test_fts5_truncates_a_longer_term_and_this_tokenizer_does_not(self, fts5_terms):
        at_limit = "a" * FTS5_MAX_TOKEN_BYTES
        assert fts5_terms([at_limit, at_limit + "a"]) == [[at_limit], [at_limit]]
        assert words(at_limit + "a") == [at_limit + "a"]
