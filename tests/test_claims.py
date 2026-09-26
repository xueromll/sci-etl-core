from __future__ import annotations

import dataclasses
import subprocess
import sys
from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sci_etl_core.claims.drafts import ClaimDraft, QuantityDraft, StatisticsDraft
from sci_etl_core.claims.locate import locate_quote, sentence_bounds
from sci_etl_core.claims.models import (
    CanonicalValue,
    Claim,
    ClaimContext,
    EvidenceSpan,
    ExtractionStamp,
    Quantity,
    Statistics,
)

STAMP = ExtractionStamp(model="m-1", prompt_hash="p", schema_hash="s", extractor_version="sci-etl-core/0.6.0")
SPAN = EvidenceSpan(record_id="2401.00001", start=10, end=40, quote="Re = 2.9 kpc")


def measurement(**changes) -> ClaimDraft:
    fields = {
        "kind": "measurement",
        "subject": "DF44",
        "predicate": "effective_radius",
        "quantity": QuantityDraft(verbatim="2.9 kpc", value=2.9, unit_text="kpc"),
        "context": {"band": "g"},
        "quote": "Re = 2.9 kpc",
    }
    fields.update(changes)
    return ClaimDraft(**fields)


def claim(draft: ClaimDraft | None = None, *, span: EvidenceSpan = SPAN, stamp: ExtractionStamp = STAMP) -> Claim:
    return Claim.from_draft(draft or measurement(), span=span, stamp=stamp)


class TestClaimModel:
    def test_every_draft_field_maps_onto_a_claim_field(self):
        draft_fields = set(ClaimDraft.model_fields) - {"quote"}
        claim_fields = {field.name for field in dataclasses.fields(Claim)}

        assert draft_fields <= claim_fields
        assert set(QuantityDraft.model_fields) <= {field.name for field in dataclasses.fields(Quantity)}
        assert set(StatisticsDraft.model_fields) <= {field.name for field in dataclasses.fields(Statistics)}

    def test_from_draft_copies_the_draft_and_the_trusted_fields(self):
        draft = measurement(
            statistics=StatisticsDraft(p_value=0.01, p_qualifier="<", group_sizes=[12, 14]),
            modality="hedged",
            confidence=0.8,
        )

        built = claim(draft)

        assert built.record_id == "2401.00001"
        assert built.quantity == Quantity(verbatim="2.9 kpc", value=2.9, unit_text="kpc")
        assert built.statistics == Statistics(p_value=0.01, p_qualifier="<", group_sizes=(12, 14))
        assert built.context == ClaimContext(attributes=(("band", "g"),))
        assert (built.modality, built.confidence, built.stamp, built.span) == ("hedged", 0.8, STAMP, SPAN)

    def test_a_measurement_needs_a_quantity_and_an_assertion_an_object(self):
        with pytest.raises(ValueError, match="needs a quantity"):
            claim(measurement(quantity=None))
        with pytest.raises(ValueError, match="needs an object"):
            claim(ClaimDraft(kind="assertion", subject="DF44", predicate="hosts", quote="q"))

    def test_a_span_needs_ordered_offsets(self):
        with pytest.raises(ValueError, match="start <= end"):
            EvidenceSpan(record_id="r", start=5, end=4, quote="q")

    def test_rows_round_trip_including_canonical_values(self):
        canonical = CanonicalValue(
            value=2.9, uncertainty=0.1, unit="kpc", dimension=(("L", 1),), kind="length", conversion_path=("kpc",)
        )
        built = dataclasses.replace(claim(), quantity=dataclasses.replace(claim().quantity, canonical=canonical))
        assertion = claim(ClaimDraft(kind="assertion", subject="DF44", predicate="hosts", object="GCs", quote="q"))
        with_statistics = claim(measurement(statistics=StatisticsDraft(effect_value=1.2)))

        for original in (built, assertion, with_statistics):
            assert Claim.from_row(original.to_row()) == original


class TestClaimId:
    def test_the_same_claim_from_another_model_has_the_same_id(self):
        other = dataclasses.replace(STAMP, model="m-2", prompt_hash="p2", extractor_version="x")

        assert claim(stamp=other).claim_id == claim().claim_id

    @pytest.mark.parametrize(
        "change",
        [
            {"kind": "assertion", "object": "GCs", "quantity": None},
            {"subject": "DF 44"},
            {"predicate": "stellar_mass"},
            {"polarity": -1},
            {"context": {"band": "r"}},
            {"quantity": QuantityDraft(verbatim="3.1 kpc", value=3.1, unit_text="kpc")},
        ],
        ids=["kind", "subject", "predicate", "polarity", "context", "quantity"],
    )
    def test_each_identifying_draft_field_changes_the_id(self, change):
        assert claim(measurement(**change)).claim_id != claim().claim_id

    def test_the_record_span_and_schema_change_the_id(self):
        assert claim(span=dataclasses.replace(SPAN, record_id="other")).claim_id != claim().claim_id
        assert claim(span=dataclasses.replace(SPAN, start=0)).claim_id != claim().claim_id
        assert claim(span=dataclasses.replace(SPAN, end=41)).claim_id != claim().claim_id
        assert claim(stamp=dataclasses.replace(STAMP, schema_hash="other")).claim_id != claim().claim_id

    def test_whitespace_inside_the_verbatim_quantity_does_not_change_the_id(self):
        spaced = measurement(quantity=QuantityDraft(verbatim="2.9  kpc", value=2.9, unit_text="kpc"))

        assert claim(spaced).claim_id == claim().claim_id

    def test_the_quote_modality_and_confidence_do_not_change_the_id(self):
        assert claim(measurement(quote="other", modality="speculative", confidence=0.1)).claim_id == claim().claim_id


class TestSentenceBounds:
    @staticmethod
    def sentences(text: str) -> list[str]:
        return [text[start:end] for start, end in sentence_bounds(text)]

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("As shown by Smith et al. the galaxy is diffuse. It is faint.", 2),
            ("See Fig. 3 for the profile. It is flat.", 2),
            ("We use Eq. (2) to fit it. The fit is good.", 2),
            ("Some galaxies, i.e. the faint ones, are red. Others are blue.", 2),
            ("The ratio is 0.5 in this band. It rises later.", 2),
            ("The radius is 2.5 kpc. The mass is small.", 2),
            ("The R.A. offset is small. The Dec offset is large.", 2),
            ("A first paragraph without a period\n\nA second one.", 2),
            ("One sentence only.", 1),
            ("  Leading space. Trailing space.  ", 2),
        ],
        ids=["et-al", "fig", "eq", "ie", "decimal", "unit", "ra", "paragraph", "single", "whitespace"],
    )
    def test_scientific_prose_cases(self, text, expected):
        sentences = self.sentences(text)

        assert len(sentences) == expected
        assert all(sentence == sentence.strip() for sentence in sentences)

    def test_question_and_exclamation_marks_end_sentences(self):
        assert self.sentences("Is it a UDG? Yes! It is.") == ["Is it a UDG?", "Yes!", "It is."]

    def test_a_single_capital_letter_ends_a_sentence(self):
        assert self.sentences("It is in band V. The next band is R.") == ["It is in band V.", "The next band is R."]

    def test_empty_text_has_no_sentences(self):
        assert sentence_bounds("") == []
        assert sentence_bounds("   \n\n  ") == []

    @given(st.text(max_size=200))
    def test_bounds_are_ordered_non_overlapping_and_inside_the_text(self, text):
        bounds = sentence_bounds(text)

        assert all(0 <= start < end <= len(text) for start, end in bounds)
        assert all(previous[1] <= following[0] for previous, following in pairwise(bounds))


TEXT = (
    "The galaxy DF44 has Re = 4.6 kpc (van Dokkum et al. 2016). See Fig. 3 for R.A. values, i.e. the map. "
    "The mass is 3e8 Msun. It lies at 100 Mpc.\n\nA new paragraph starts here"
)


class TestLocateQuote:
    def test_an_exact_quote_snaps_to_its_sentence(self):
        start, end, ratio = locate_quote(TEXT, "mass is 3e8  Msun")

        assert (TEXT[start:end], ratio) == ("The mass is 3e8 Msun.", 1.0)

    def test_a_quote_across_two_sentences_snaps_to_both(self):
        start, end, _ratio = locate_quote(TEXT, "3e8 Msun. It lies")

        assert TEXT[start:end] == "The mass is 3e8 Msun. It lies at 100 Mpc."

    def test_quotes_at_the_start_and_end_of_the_text(self):
        first = locate_quote(TEXT, "The galaxy DF44")
        last = locate_quote(TEXT, "starts here")

        assert first[:2] == (0, TEXT.index(" See"))
        assert TEXT[last[0] : last[1]] == "A new paragraph starts here"

    def test_a_paraphrase_is_matched_fuzzily_to_the_shortest_sentence(self):
        start, end, ratio = locate_quote(TEXT, "the mass was 3e8 Msun", min_ratio=0.85)

        assert TEXT[start:end] == "The mass is 3e8 Msun."
        assert 0.85 <= ratio < 1.0

    def test_a_quote_that_is_not_in_the_text_is_ungrounded(self):
        assert locate_quote(TEXT, "a completely different statement") is None
        assert locate_quote(TEXT, "zzzz") is None

    def test_an_empty_quote_or_text_is_ungrounded(self):
        assert locate_quote(TEXT, "   ") is None
        assert locate_quote("", "anything") is None

    def test_min_ratio_must_be_a_share(self):
        with pytest.raises(ValueError, match="min_ratio"):
            locate_quote(TEXT, "q", min_ratio=1.5)


def test_importing_claims_loads_neither_numpy_nor_the_pipeline():
    code = (
        "import sys, sci_etl_core.claims as claims; claims.Claim; claims.AsyncSqliteClaimStore; "
        "print('numpy' in sys.modules, 'sci_etl_core.pipeline_async' in sys.modules)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)

    assert result.stdout.split() == ["False", "False"]
