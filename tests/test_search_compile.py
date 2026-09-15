from __future__ import annotations

import re

import pytest

from sci_etl_core.exceptions import SearchQueryError
from sci_etl_core.search.compile_fts5 import is_rankable, require_rankable, to_match_expression
from sci_etl_core.search.parser import parse_query
from sci_etl_core.search.query import And, Not, Or, Phrase, Term
from sci_etl_core.search.store_base import SearchDocument

A, B, C = Term("a"), Term("b"), Term("c")
NOT_RANKABLE = "A ranked search needs at least one term that is not negated, and so does each OR alternative"


def assert_rankable(node, expression):
    assert is_rankable(node)
    require_rankable(node)
    assert to_match_expression(node) == expression


def assert_not_rankable(node):
    assert not is_rankable(node)
    for compile_step in (require_rankable, to_match_expression):
        with pytest.raises(SearchQueryError, match=re.escape(NOT_RANKABLE)) as raised:
            compile_step(node)
        assert (raised.value.position, raised.value.token) == (None, "")


class TestRankabilityTable:
    def test_a_b_is_a_ranked_conjunction(self):
        node = parse_query("a b")
        assert node == And((A, B))
        assert_rankable(node, '("a" AND "b")')

    def test_a_minus_b_is_a_binary_negation(self):
        node = parse_query("a -b")
        assert node == And((A, Not(B)))
        assert_rankable(node, '"a" NOT "b"')

    def test_a_minus_b_minus_c_subtracts_the_merged_negations(self):
        node = parse_query("a -b -c")
        assert node == And((A, Not(Or((B, C)))))
        assert_rankable(node, '"a" NOT ("b" OR "c")')

    def test_not_not_a_is_the_term_itself(self):
        node = parse_query("NOT NOT a")
        assert node == A
        assert_rankable(node, '"a"')

    def test_not_b_has_no_positive_part(self):
        node = parse_query("NOT b")
        assert node == Not(B)
        assert_not_rankable(node)

    def test_not_b_or_c_has_an_alternative_that_is_not_rankable(self):
        node = parse_query("NOT b OR c")
        assert node == Or((Not(B), C))
        assert_not_rankable(node)

    def test_a_or_minus_b_is_the_same_case_with_operands_swapped(self):
        node = parse_query("a OR -b")
        assert node == Or((A, Not(B)))
        assert_not_rankable(node)

    def test_not_of_a_group_has_no_positive_part(self):
        node = parse_query("NOT (a OR b)")
        assert node == Not(Or((A, B)))
        assert_not_rankable(node)


@pytest.mark.parametrize(
    "node",
    [
        And((A, Not(Or((B, Not(C)))))),
        Or((A, And((Not(B), Not(C))))),
        Not(Not(Not(A))),
    ],
)
def test_a_nested_negation_without_a_positive_part_is_not_rankable(node):
    assert_not_rankable(node)


@pytest.mark.parametrize(
    "node, expression",
    [
        (Term("foo", prefix=True), '"foo"*'),
        (Term('a"b'), '"a""b"'),
        (Term("x", fields=("title",)), '{title} : "x"'),
        (Term("gal", fields=("title", "abstract"), prefix=True), '{title abstract} : "gal"*'),
        (Phrase(("dwarf", "galaxy")), '"dwarf galaxy"'),
        (Phrase(("dwarf", "galaxy"), fields=("body",)), '{body} : "dwarf galaxy"'),
        (Term('") OR NOT ("'), '""") OR NOT ("""'),
        (Term("a\x00b\ud800c"), '"a b c"'),
    ],
)
def test_every_word_reaches_fts5_as_one_quoted_literal(node, expression, fts5_match):
    assert_rankable(node, expression)
    fts5_match([SearchDocument("1", title="foo x", abstract="a b c", body="dwarf galaxy")], expression)


@pytest.mark.parametrize(
    "node, expression",
    [
        (And((A, B, C)), '("a" AND "b" AND "c")'),
        (Or((A, B)), '("a" OR "b")'),
        (And((A, B, Not(C))), '("a" AND "b") NOT "c"'),
        (And((Or((A, B)), C)), '(("a" OR "b") AND "c")'),
        (Or((And((A, Not(B))), C)), '(("a" NOT "b") OR "c")'),
        (And((A, Not(And((B, Not(C)))))), '"a" NOT ("b" NOT "c")'),
        (And((A, Not(B), Not(C))), '"a" NOT ("b" OR "c")'),
        (Not(Not(And((Not(B), A)))), '"a" NOT "b"'),
    ],
)
def test_composites_are_parenthesized_so_precedence_never_decides(node, expression):
    assert_rankable(node, expression)
