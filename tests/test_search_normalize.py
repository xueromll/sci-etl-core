from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from sci_etl_core.search.query import And, Near, Not, Or, Phrase, Term, normalize

A, B, C, D = (Term(word) for word in "abcd")


class TestDoubleNegation:
    def test_is_removed(self):
        assert normalize(Not(Not(A))) == A

    def test_an_odd_count_keeps_one_negation(self):
        assert normalize(Not(Not(Not(A)))) == Not(A)

    def test_is_removed_below_other_nodes(self):
        assert normalize(Or((Not(Not(A)), B))) == Or((A, B))


class TestFlattening:
    @pytest.mark.parametrize("kind", [And, Or])
    def test_nested_operands_of_the_same_kind_are_spliced_in_place(self, kind):
        assert normalize(kind((A, kind((B, kind((C, D))))))) == kind((A, B, C, D))

    @pytest.mark.parametrize("kind", [And, Or])
    def test_a_single_operand_collapses_to_that_operand(self, kind):
        assert normalize(kind((A,))) == A

    def test_a_collapsed_operand_flattens_into_its_parent(self):
        assert normalize(Or((And((Or((A, B)),)), C))) == Or((A, B, C))

    def test_different_kinds_stay_nested(self):
        tree = And((A, Or((B, C))))
        assert normalize(tree) == tree


class TestDeMorganMerge:
    def test_two_negations_merge(self):
        assert normalize(And((A, Not(B), Not(C)))) == And((A, Not(Or((B, C)))))

    def test_three_negations_merge(self):
        assert normalize(And((A, Not(B), Not(C), Not(D)))) == And((A, Not(Or((B, C, D)))))

    def test_the_merged_negation_stands_where_the_first_one_stood(self):
        assert normalize(And((Not(B), A, Not(C)))) == And((Not(Or((B, C))), A))

    def test_a_conjunction_of_negations_becomes_one_negation(self):
        assert normalize(And((Not(A), Not(B)))) == Not(Or((A, B)))

    def test_merged_disjunctions_flatten(self):
        assert normalize(And((Not(Or((A, B))), Not(C)))) == Not(Or((A, B, C)))

    def test_double_negations_are_removed_before_merging(self):
        assert normalize(And((A, Not(Not(Not(B))), Not(C)))) == And((A, Not(Or((B, C)))))
        assert normalize(And((Not(Not(A)), Not(B)))) == And((A, Not(B)))

    def test_a_single_negation_is_left_alone(self):
        tree = And((A, Not(B)))
        assert normalize(tree) == tree

    def test_negations_inside_a_disjunction_do_not_merge(self):
        tree = Or((Not(A), Not(B)))
        assert normalize(tree) == tree


@pytest.mark.parametrize("kind", [And, Or])
def test_operand_order_is_preserved(kind):
    tree = kind((D, C, B, A))
    assert normalize(tree) == tree


def test_leaves_are_returned_unchanged():
    phrase = Phrase(("dwarf", "galaxy"), fields=("title",))
    term = Term("photometr", fields=("abstract", "body"), prefix=True)
    assert normalize(phrase) is phrase
    assert normalize(term) is term


@pytest.mark.parametrize(
    "tree",
    [
        Not(Not(And((A, Not(B), Not(Or((C, Not(Not(D))))))))),
        Or((And((Not(A), Not(B))), And((C,)), Or((D,)))),
        And((Or((A, And((B, Not(C))))), Not(Not(Not(D))))),
    ],
)
def test_normalizing_twice_changes_nothing(tree):
    once = normalize(tree)
    assert normalize(once) == once


class TestNodeValidation:
    @pytest.mark.parametrize(
        "build, message",
        [
            (lambda: Term(""), "non-empty text"),
            (lambda: Term("x", fields=("titel",)), "Unknown field 'titel'"),
            (lambda: Term("x", fields=("title", "title")), "must not repeat"),
            (lambda: Phrase(()), "at least one word"),
            (lambda: Phrase(("dwarf", "")), "no word may be empty"),
            (lambda: Phrase(("dwarf",), fields=("keywords",)), "Unknown field 'keywords'"),
            (lambda: Near((A,)), "at least two terms or phrases"),
            (lambda: Near((A, Term("b", fields=("title",)))), "cannot have fields of their own"),
            (lambda: Near((A, B), distance=-1), "must not be negative"),
            (lambda: Near((A, B), fields=("titel",)), "Unknown field 'titel'"),
            (lambda: And(()), "at least one operand"),
            (lambda: Or(()), "at least one operand"),
        ],
    )
    def test_an_impossible_node_is_rejected(self, build, message):
        with pytest.raises(ValueError, match=message):
            build()

    def test_nodes_are_frozen_and_usable_as_keys(self):
        def build():
            return And((Term("a", fields=("title",), prefix=True), Not(Phrase(("b", "c")))))

        assert {build(): "cached"}[build()] == "cached"
        with pytest.raises(FrozenInstanceError):
            build().operands = ()
