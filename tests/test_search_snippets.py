from __future__ import annotations

import pytest

from sci_etl_core.search.parser import parse_query
from sci_etl_core.search.snippets import passage_snippet, snippet_window
from sci_etl_core.search.store_base import Snippet
from sci_etl_core.search.tokenize import Unicode61Tokenizer

TOKENIZER = Unicode61Tokenizer()
PASSAGE = "We observe nearby dwarf galaxies and their dark matter halos with deep photometry."


def marked(snippet):
    return [snippet.text[start:end] for start, end in snippet.highlights]


class TestPassageSnippet:
    @pytest.mark.parametrize(
        ("query", "words"),
        [
            ("dwarf galaxies", ["dwarf", "galaxies"]),
            ("quasar OR halo*", ["halos"]),
            ('"dark matter" -dwarf', ["dark matter"]),
            ("-(dwarf OR nearby) photometry", ["photometry"]),
            ("NOT NOT dwarf", ["dwarf"]),
            ("NEAR(dwarf photometry, 1)", ["dwarf", "photometry"]),
            ("title:dwarf halos", ["halos"]),
            ("body:dwarf", ["dwarf"]),
        ],
    )
    def test_highlights_every_word_of_the_query_that_is_not_negated(self, query, words):
        snippet = passage_snippet(parse_query(query), PASSAGE)
        assert snippet.field == "body"
        assert snippet.text == PASSAGE
        assert marked(snippet) == words

    def test_highlights_words_even_when_the_passage_does_not_match_the_whole_query(self):
        assert marked(passage_snippet(parse_query("dwarf quasar"), PASSAGE)) == ["dwarf"]

    def test_a_passage_without_a_query_word_gives_its_start(self):
        words = " ".join(f"w{index}" for index in range(40))
        snippet = passage_snippet(parse_query("quasar"), words)
        assert snippet.highlights == ()
        assert snippet.text.startswith("w0 w1")
        assert snippet.text.endswith("…")

    def test_the_field_decides_which_scoped_words_are_highlighted(self):
        assert marked(passage_snippet(parse_query("title:dwarf"), PASSAGE, "title")) == ["dwarf"]
        assert passage_snippet(parse_query("title:dwarf"), PASSAGE, "abstract").highlights == ()

    def test_control_characters_are_read_as_spaces(self):
        assert passage_snippet(parse_query("dwarf"), "a\x00dwarf") == Snippet("body", "a dwarf", ((2, 7),))

    def test_an_unknown_field_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown field 'keywords'"):
            passage_snippet(parse_query("dwarf"), PASSAGE, "keywords")

    def test_another_tokenizer_can_be_used(self):
        class Silent:
            def tokens(self, text):
                return []

        assert passage_snippet(parse_query("dwarf"), PASSAGE, tokenizer=Silent()) == Snippet("body", PASSAGE)


class TestSnippetWindow:
    def test_a_short_text_is_kept_whole(self):
        text = "dwarf galaxies"
        assert snippet_window(text, TOKENIZER.tokens(text), [(1, 2)]) == (text, ((6, 14),))

    def test_a_long_text_is_cut_around_the_first_range_with_ellipses(self):
        text = " ".join(f"w{index}" for index in range(100))
        window, highlights = snippet_window(text, TOKENIZER.tokens(text), [(50, 51), (40, 42)])
        assert window.startswith("…w40 w41")
        assert window.endswith("w63…")
        assert [window[start:end] for start, end in highlights] == ["w40 w41", "w50"]

    def test_a_range_near_the_end_moves_the_window_back(self):
        text = " ".join(f"w{index}" for index in range(30))
        window, highlights = snippet_window(text, TOKENIZER.tokens(text), [(29, 30)])
        assert window.startswith("…w6 ")
        assert window.endswith("w29")
        assert [window[start:end] for start, end in highlights] == ["w29"]

    def test_overlapping_ranges_become_one_span_and_ranges_outside_the_window_are_dropped(self):
        text = " ".join(f"w{index}" for index in range(100))
        window, highlights = snippet_window(text, TOKENIZER.tokens(text), [(0, 2), (1, 3), (90, 91)])
        assert [window[start:end] for start, end in highlights] == ["w0 w1 w2"]

    def test_an_empty_text_gives_an_empty_window(self):
        assert snippet_window("", [], []) == ("", ())
