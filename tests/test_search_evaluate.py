from __future__ import annotations

import re
from dataclasses import fields

import pytest

from sci_etl_core.search.compile_fts5 import to_match_expression
from sci_etl_core.search.evaluate import TokenizedDocument, matches
from sci_etl_core.search.query import FIELDS, And, Not, Or, Phrase, Term
from sci_etl_core.search.store_base import SearchDocument
from sci_etl_core.search.tokenize import Token

ARTICLE = SearchDocument(
    "2401.00001",
    title="Dwarf galaxies in Müller's survey",
    abstract="H-alpha photometry of nearby galaxies",
    body="The Straße sample",
)

CORPUS = [
    SearchDocument("1", title="a b"),
    SearchDocument("2", title="a", abstract="b c"),
    SearchDocument("3", body="dwarf galaxy"),
    SearchDocument("4", title="dwarf galaxies", body="c"),
    SearchDocument("5", title="Müller", abstract="b", body="a c"),
    SearchDocument("6", title="a", body="b"),
]


class WhitespaceTokenizer:
    def tokens(self, text: str) -> list[Token]:
        return [Token(match.group(), match.start(), match.end()) for match in re.finditer(r"\S+", text)]


@pytest.mark.parametrize(
    "node, expected",
    [
        (Term("galaxies"), True),
        (Term("quasar"), False),
        (Term("muller"), True),
        (Term("Müller"), True),
        (Term("straße"), True),
        (Term("strasse"), False),
        (Term("photometry", fields=("title",)), False),
        (Term("photometry", fields=("abstract",)), True),
        (Term("photometry", fields=("title", "body")), False),
        (Term("photometr", prefix=True), True),
        (Term("photometry", prefix=True), True),
        (Term("hotometr", prefix=True), False),
        (Term("photometr", fields=("body",), prefix=True), False),
        (Phrase(("dwarf", "galaxies")), True),
        (Phrase(("galaxies", "dwarf")), False),
        (Phrase(("dwarf", "survey")), False),
        (Phrase(("survey", "h")), False),
        (Phrase(("nearby", "galaxies"), fields=("abstract",)), True),
        (Term("H-alpha"), True),
        (Term("alpha-H"), False),
        (Term("h alph", prefix=True), True),
        (Term("~"), False),
        (Term("~", prefix=True), False),
        (Phrase(("~", "...")), False),
    ],
)
def test_leaf_semantics(node, expected):
    assert matches(node, ARTICLE) is expected


@pytest.mark.parametrize(
    "node, expected",
    [
        (And((Term("dwarf"), Term("sample"))), True),
        (And((Term("dwarf"), Term("quasar"))), False),
        (Or((Term("quasar"), Term("sample"))), True),
        (Or((Term("quasar"), Term("blazar"))), False),
        (Not(Term("quasar")), True),
        (Not(Term("dwarf")), False),
        (Not(Not(Term("dwarf"))), True),
        (Or((Not(Term("dwarf")), Term("quasar"))), False),
        (And((Term("dwarf"), Not(Or((Term("quasar"), Term("blazar")))))), True),
    ],
)
def test_boolean_semantics(node, expected):
    assert matches(node, ARTICLE) is expected


@pytest.mark.parametrize(
    "node, expected",
    [
        (Term("~"), set()),
        (And((Term("a"), Term("~"))), set()),
        (Or((Term("a"), Term("~"))), {"1", "2", "5", "6"}),
        (And((Term("a"), Not(Term("~")))), {"1", "2", "5", "6"}),
        (Term("dwarf gal", prefix=True), {"3", "4"}),
        (Term("gal", fields=("title", "abstract"), prefix=True), {"4"}),
        (Phrase(("dwarf", "galaxy"), fields=("body",)), {"3"}),
        (Term("mü", prefix=True), {"5"}),
        (Term("a\x00b"), {"1"}),
        (And((Term("a"), Not(And((Term("b"), Not(Term("c"))))))), {"2", "5"}),
        (Or((And((Term("a"), Not(Term("b")))), Term("c"))), {"2", "4", "5"}),
        (And((Term("a"), Not(Term("b", fields=("abstract",))))), {"1", "6"}),
    ],
)
def test_agrees_with_fts5_running_the_compiled_expression(node, expected, fts5_match):
    assert {document.record_id for document in CORPUS if matches(node, document)} == expected
    assert fts5_match(CORPUS, to_match_expression(node)) == expected


class TestTokenizer:
    def test_the_given_tokenizer_splits_both_the_document_and_the_query(self):
        tokenizer = WhitespaceTokenizer()
        assert matches(Term("H-alpha"), ARTICLE, tokenizer=tokenizer)
        assert matches(Phrase(("Dwarf", "galaxies")), ARTICLE, tokenizer=tokenizer)
        assert not matches(Term("h"), ARTICLE, tokenizer=tokenizer)

    def test_a_tokenized_document_is_not_tokenized_again(self):
        tokenized = TokenizedDocument.from_document(ARTICLE)
        assert tokenized.title == ("dwarf", "galaxies", "in", "muller", "s", "survey")
        assert matches(Term("Muller"), tokenized)
        assert not matches(Term("muller"), TokenizedDocument(title=("müller",)))

    def test_from_document_uses_the_given_tokenizer(self):
        tokenized = TokenizedDocument.from_document(ARTICLE, WhitespaceTokenizer())
        assert tokenized.body == ("The", "Straße", "sample")

    def test_a_tokenized_document_has_one_attribute_per_search_field(self):
        assert tuple(attribute.name for attribute in fields(TokenizedDocument)) == FIELDS


def test_search_document_defaults_are_empty_and_unshared():
    first, second = SearchDocument("r1"), SearchDocument("r2")
    assert (first.title, first.abstract, first.body, first.metadata) == ("", "", "", {})
    assert first.metadata is not second.metadata
