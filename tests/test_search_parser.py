from __future__ import annotations

import re

import pytest

from sci_etl_core.exceptions import SearchQueryError
from sci_etl_core.search.parser import MAX_GROUP_DEPTH, parse_query, parse_ranked_query, parse_semantic_query
from sci_etl_core.search.query import And, Near, Not, Or, Phrase, QueryChip, Term, describe

A, B, C = Term("a"), Term("b"), Term("c")
NOT_RANKABLE = "A ranked search needs at least one term that is not negated"
NO_WHOLE_WORD = "A semantic search needs at least one whole word; prefix terms match lexically only"


@pytest.mark.parametrize(
    ("query", "expected"),
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
    ("query", "expected"),
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
    ("query", "expected"),
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
    ("query", "position", "token", "message"),
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


class TestNear:
    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("NEAR(a b)", Near((A, B))),
            ("NEAR(a b, 5)", Near((A, B), 5)),
            ('NEAR( a  "b c" d* , 0 )', Near((A, Phrase(("b", "c")), Term("d", prefix=True)), 0)),
            ("title,body:NEAR(a b, 2)", Near((A, B), 2, ("title", "body"))),
            ('NEAR("a b", 3)', Near((A, B), 3)),
            ('NEAR(a"b c")', Near((A, Phrase(("b", "c"))))),
            ("NEAR(a-b c)", Near((Phrase(("a", "b")), C))),
            ("NEAR(a)", A),
            ('NEAR("a")', A),
            ("title:NEAR(a)", Term("a", fields=("title",))),
            ('abstract:NEAR("a b" , 4)', Near((A, B), 4, ("abstract",))),
            ("title:NEAR(a-b)", Phrase(("a", "b"), fields=("title",))),
            ("x NEAR(a b)c", And((Term("x"), Near((A, B)), C))),
            ("-NEAR(a b)", Not(Near((A, B)))),
            ("NEAR (a b)", And((Term("near"), A, B))),
            ("near(a b)", And((Term("near"), A, B))),
        ],
    )
    def test_groups(self, query, expected):
        assert parse_query(query) == expected

    def test_default_fields_scope_the_group_not_its_operands(self):
        assert parse_query("NEAR(a b)", default_fields=["title"]) == Near((A, B), fields=("title",))

    @pytest.mark.parametrize(
        ("query", "position", "token", "message"),
        [
            ("NEAR(a b", 4, "(", "NEAR( is never closed"),
            ("NEAR(", 4, "(", "NEAR( is never closed"),
            ('NEAR(a "b', 7, '"', "Quoted phrase is never closed"),
            ('NEAR("" a)', 5, '""', "'\"\"' contains no word to search for"),
            ("NEAR()", 0, "NEAR()", "NEAR() needs at least one term or phrase"),
            ("title:NEAR(, 3)", 0, "title:NEAR(, 3)", "NEAR() needs at least one term or phrase"),
            ("NEAR(a b, 5", 8, ",", "NEAR() takes a whole number of tokens after its comma"),
            ("NEAR(a b, x)", 8, ",", "NEAR() takes a whole number of tokens after its comma"),
            ("NEAR(a b,)", 8, ",", "NEAR() takes a whole number of tokens after its comma"),
            ("NEAR(a b, -1)", 8, ",", "NEAR() takes a whole number of tokens after its comma"),
            ("NEAR(a (b))", 7, "(", "Unexpected '(' inside NEAR()"),
            ("NEAR(title:a b)", 5, "title:a", "Only terms and phrases can go inside NEAR()"),
            ('NEAR(title:"a b")', 5, "title:", "Only terms and phrases can go inside NEAR()"),
            ("NEAR(a AND b)", 7, "AND", "Only terms and phrases can go inside NEAR()"),
            ("NEAR(a -b)", 7, "-b", "Only terms and phrases can go inside NEAR()"),
            ("NEAR(- a)", 5, "-", "Only terms and phrases can go inside NEAR()"),
            ("NEAR(a && b)", 7, "&&", "Only terms and phrases can go inside NEAR()"),
            ("NEAR(a||b)", 6, "||", "Only terms and phrases can go inside NEAR()"),
            ("NEAR(a**)", 7, "*", "'*' must directly follow a single word"),
        ],
    )
    def test_a_malformed_group_names_the_first_fault(self, query, position, token, message):
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


class TestParseRankedQuery:
    def test_a_rankable_query_returns_its_normalized_node(self):
        assert parse_ranked_query("a -b", default_fields=["title"]) == And(
            (Term("a", fields=("title",)), Not(Term("b", fields=("title",))))
        )

    @pytest.mark.parametrize(
        ("query", "position", "token"),
        [
            ("NOT b", 0, "NOT"),
            ("NOT b OR c", 0, "NOT"),
            ("a OR -b", 5, "-"),
            ("x AND (y OR NOT z)", 12, "NOT"),
            ('"NOT a" OR -(b c)', 11, "-"),
        ],
    )
    def test_a_query_that_cannot_be_ranked_is_located_at_its_first_negation(self, query, position, token):
        with pytest.raises(SearchQueryError, match=NOT_RANKABLE) as raised:
            parse_ranked_query(query)
        assert (raised.value.position, raised.value.token) == (position, token)
        assert query[position : position + len(token)] == token

    def test_a_malformed_query_is_reported_as_parse_query_reports_it(self):
        with pytest.raises(SearchQueryError, match="'\\(' is never closed") as raised:
            parse_ranked_query("NOT (a")
        assert (raised.value.position, raised.value.token) == (4, "(")


class TestParseSemanticQuery:
    def test_returns_the_node_and_the_text_to_embed(self):
        assert parse_semantic_query("photometr* dwarf -quasar") == (
            And((Term("photometr", prefix=True), Term("dwarf"), Not(Term("quasar")))),
            "dwarf",
        )

    @pytest.mark.parametrize(
        ("query", "position", "token"),
        [
            ("photometr*", 0, "photometr*"),
            ("a* title:b*", 0, "a*"),
            ("-quasar title:photometr*", 8, "title:photometr*"),
            ("gal* -dwarf", 0, "gal*"),
            ("-y NEAR(a* b*, 2)", 3, "NEAR(a* b*, 2)"),
        ],
    )
    def test_a_query_with_only_prefix_terms_is_located_at_its_first_prefix_term(self, query, position, token):
        with pytest.raises(SearchQueryError, match=re.escape(NO_WHOLE_WORD)) as raised:
            parse_semantic_query(query)
        assert (raised.value.position, raised.value.token) == (position, token)

    def test_rankability_is_checked_before_the_text_to_embed(self):
        with pytest.raises(SearchQueryError, match=NOT_RANKABLE) as raised:
            parse_semantic_query("NOT a*")
        assert (raised.value.position, raised.value.token) == (0, "NOT")


class TestDescribe:
    def test_a_single_word_is_one_chip_without_an_operator(self):
        assert describe(parse_query("title:quasar")) == [QueryChip("quasar", fields=("title",))]

    def test_chips_follow_the_written_order_with_their_group_and_polarity(self):
        assert describe(parse_query('a -"dwarf galaxy" (b OR title:photometr*)')) == [
            QueryChip("a", operator="AND"),
            QueryChip("dwarf galaxy", operator="AND", negated=True, phrase=True),
            QueryChip("b", operator="OR", depth=1),
            QueryChip("photometr", fields=("title",), operator="OR", prefix=True, depth=1),
        ]

    def test_a_negated_group_negates_every_chip_inside_it(self):
        assert describe(parse_query("NOT (a OR b)")) == [
            QueryChip("a", operator="OR", negated=True),
            QueryChip("b", operator="OR", negated=True),
        ]

    def test_a_near_group_is_one_chip_carrying_its_distance(self):
        assert describe(parse_query('x OR -title:NEAR(a* "b c", 4)')) == [
            QueryChip("x", operator="OR"),
            QueryChip('a* "b c"', fields=("title",), operator="OR", negated=True, near=4),
        ]

    def test_a_hand_built_ast_is_normalized_first(self):
        assert describe(Not(Not(A))) == [QueryChip("a")]
        assert describe(And((A, Not(B), Not(C)))) == [
            QueryChip("a", operator="AND"),
            QueryChip("b", operator="OR", negated=True, depth=1),
            QueryChip("c", operator="OR", negated=True, depth=1),
        ]
