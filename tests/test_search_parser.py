from __future__ import annotations

import re

import pytest

from sci_etl_core.exceptions import SearchQueryError
from sci_etl_core.search.parser import MAX_GROUP_DEPTH, parse_query
from sci_etl_core.search.query import And, Not, Or, Phrase, Term

A, B, C = Term("a"), Term("b"), Term("c")


@pytest.mark.parametrize(
    "query, expected",
    [
        ("galaxy", Term("galaxy")),
        ("GaLaXy", Term("galaxy")),
        ("Müller", Term("muller")),
        ("Straße", Term("straße")),
        ("photometr*", Term("photometr", prefix=True)),
        ("Photométr*", Term("photometr", prefix=True)),
        ('"dwarf galaxy"', Phrase(("dwarf", "galaxy"))),
        ('"Galaxy"', Term("galaxy")),
        ('"  galaxy, "', Term("galaxy")),
        ('"a AND b"', Phrase(("a", "and", "b"))),
        ("H-alpha", Phrase(("h", "alpha"))),
        ("z~0.5", Phrase(("z", "0", "5"))),
        ("R&D", Phrase(("r", "d"))),
        ("a|b", Phrase(("a", "b"))),
        ("10:30", Phrase(("10", "30"))),
        ('"arXiv:2401.00001"', Phrase(("arxiv", "2401", "00001"))),
        ("and", Term("and")),
        ("title:quasar", Term("quasar", fields=("title",))),
        ("Title,ABSTRACT:quasar", Term("quasar", fields=("title", "abstract"))),
        ("body,title,title:quasar", Term("quasar", fields=("title", "body"))),
        ('abstract:"dwarf galaxy"', Phrase(("dwarf", "galaxy"), fields=("abstract",))),
        ("title:photometr*", Term("photometr", fields=("title",), prefix=True)),
        ("title:H-alpha", Phrase(("h", "alpha"), fields=("title",))),
        ("title:AND", Term("and", fields=("title",))),
    ],
)
def test_leaves(query, expected):
    assert parse_query(query) == expected


@pytest.mark.parametrize("query", ["a AND b", "a && b", "a&&b", "a b", "  a\tb\n"])
def test_conjunction_forms(query):
    assert parse_query(query) == And((A, B))


@pytest.mark.parametrize("query", ["a OR b", "a || b", "a||b"])
def test_disjunction_forms(query):
    assert parse_query(query) == Or((A, B))


@pytest.mark.parametrize("query", ["NOT a", "-a", "- a"])
def test_negation_forms(query):
    assert parse_query(query) == Not(A)


@pytest.mark.parametrize(
    "query, expected",
    [
        ("a OR b c", Or((A, And((B, C))))),
        ("a b OR c", Or((And((A, B)), C))),
        ("NOT a b", And((Not(A), B))),
        ("NOT a OR b", Or((Not(A), B))),
        ("(a OR b) c", And((Or((A, B)), C))),
        ("(a OR b) AND NOT c", And((Or((A, B)), Not(C)))),
        ("-(a OR b)", Not(Or((A, B)))),
        ("a -b", And((A, Not(B)))),
        ("a NOT b", And((A, Not(B)))),
        ("a-b", Phrase(("a", "b"))),
        ("a and b", And((A, Term("and"), B))),
        ('a"b"', And((A, B))),
        ("(a)(b)", And((A, B))),
        ("-title:a", Not(Term("a", fields=("title",)))),
    ],
)
def test_precedence_and_grouping(query, expected):
    assert parse_query(query) == expected


@pytest.mark.parametrize(
    "query, expected",
    [
        ("NOT NOT a", A),
        ("--a", A),
        ("NOT -a", A),
        ("NOT NOT NOT a", Not(A)),
        ("a -b -c", And((A, Not(Or((B, C)))))),
        ("(a (b c)) OR (a OR (b OR c))", Or((And((A, B, C)), A, B, C))),
        ("((((a))))", A),
    ],
)
def test_the_result_is_normalized(query, expected):
    assert parse_query(query) == expected


class TestDefaultFields:
    def test_scope_only_the_leaves_without_their_own_scope(self):
        node = parse_query('a "b c" abstract:d', default_fields=["body", "title"])
        assert node == And(
            (
                Term("a", fields=("title", "body")),
                Phrase(("b", "c"), fields=("title", "body")),
                Term("d", fields=("abstract",)),
            )
        )

    def test_none_means_every_field(self):
        assert parse_query("a") == Term("a", fields=())

    def test_an_unknown_name_is_a_request_error_without_a_position(self):
        with pytest.raises(SearchQueryError, match="Unknown field 'keywords'") as raised:
            parse_query("a", default_fields=("title", "keywords"))
        assert (raised.value.position, raised.value.token) == (None, "keywords")


@pytest.mark.parametrize(
    "query, position, token, message",
    [
        ("", 0, "", "The query is empty"),
        (" \t ", 0, "", "The query is empty"),
        ("(a", 0, "(", "'(' is never closed"),
        ("a (b (c)", 2, "(", "'(' is never closed"),
        ("a)", 1, ")", "')' has no matching '('"),
        ("(a))", 3, ")", "')' has no matching '('"),
        ("a AND", 2, "AND", "Expected a search term after 'AND'"),
        ("a OR", 2, "OR", "Expected a search term after 'OR'"),
        ("a ||", 2, "||", "Expected a search term after '||'"),
        ("NOT", 0, "NOT", "Expected a search term after 'NOT'"),
        ("a -", 2, "-", "Expected a search term after '-'"),
        ("(", 0, "(", "Expected a search term after '('"),
        ("AND a", 0, "AND", "Expected a search term before 'AND'"),
        ("a OR OR b", 5, "OR", "Expected a search term before 'OR'"),
        ("a && && b", 5, "&&", "Expected a search term before '&&'"),
        ("()", 1, ")", "Expected a search term before ')'"),
        ("a (OR b)", 3, "OR", "Expected a search term before 'OR'"),
        (') "never closed', 0, ")", "Expected a search term before ')'"),
        ('"dwarf galaxy', 0, '"', "Quoted phrase is never closed"),
        ('a title:"b', 8, '"', "Quoted phrase is never closed"),
        ('""', 0, '""', "'\"\"' contains no word to search for"),
        ('title:"..."', 6, '"..."', "'\"...\"' contains no word to search for"),
        ("a ~", 2, "~", "'~' contains no word to search for"),
        ("title:...", 6, "...", "'...' contains no word to search for"),
        ("titel:quasar", 0, "titel", "Unknown field 'titel'; expected one of title, abstract, body"),
        ("a title,abstrct:x", 8, "abstrct", "Unknown field 'abstrct'"),
        ("arXiv:2401.00001", 0, "arXiv", "Unknown field 'arXiv'"),
        ("title:", 0, "title:", "Field scope 'title:' must be directly followed by a word or a quoted phrase"),
        ("title: quasar", 0, "title:", "Field scope 'title:' must be directly followed"),
        ("title:(a)", 0, "title:", "Field scope 'title:' must be directly followed"),
        ("photo-metr*", 10, "*", "'*' must directly follow a single word"),
        ("*", 0, "*", "'*' must directly follow a single word"),
        ("a**", 2, "*", "'*' must directly follow a single word"),
        ('"dwarf gal"*', 11, "*", "'*' must directly follow a single word"),
        ("title:*", 6, "*", "'*' must directly follow a single word"),
    ],
)
def test_a_malformed_query_names_the_first_fault(query, position, token, message):
    with pytest.raises(SearchQueryError, match=re.escape(message)) as raised:
        parse_query(query)
    assert (raised.value.position, raised.value.token) == (position, token)
    assert query[position : position + len(token)] == token


class TestNestingLimits:
    def test_parentheses_nest_up_to_the_limit(self):
        assert parse_query("(" * MAX_GROUP_DEPTH + "a" + ")" * MAX_GROUP_DEPTH) == A

    def test_the_first_parenthesis_past_the_limit_is_rejected(self):
        depth = MAX_GROUP_DEPTH + 1
        with pytest.raises(SearchQueryError, match=f"nest more than {MAX_GROUP_DEPTH} deep") as raised:
            parse_query("(" * depth + "a" + ")" * depth)
        assert (raised.value.position, raised.value.token) == (MAX_GROUP_DEPTH, "(")

    def test_a_long_chain_of_negations_parses_without_recursion(self):
        assert parse_query("NOT " * 10_000 + "a") == A
        assert parse_query("-" * 10_001 + "a") == Not(A)

    def test_a_long_flat_query_parses(self):
        assert parse_query(" OR ".join(["a -b"] * 5_000)) == Or((And((A, Not(B))),) * 5_000)
