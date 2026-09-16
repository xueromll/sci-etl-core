from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from sci_etl_core.exceptions import ParsingError
from sci_etl_core.parsers import DocxParser, JatsArticle, JatsSection, JatsXmlParser

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _docx(body: str, footnotes: str | None = None, extra_parts: dict[str, bytes] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", f"<w:document {W}><w:body>{body}</w:body></w:document>")
        if footnotes is not None:
            archive.writestr("word/footnotes.xml", f"<w:footnotes {W}>{footnotes}</w:footnotes>")
        for name, data in (extra_parts or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _paragraph(*runs: str) -> str:
    return "<w:p>" + "".join(f"<w:r>{run}</w:r>" for run in runs) + "</w:p>"


class TestDocxParser:
    def test_paragraphs_come_out_in_order_one_per_line(self):
        content = _docx(_paragraph("<w:t>Title</w:t>") + _paragraph("<w:t>First </w:t>", "<w:t>body.</w:t>"))
        assert DocxParser().extract_text(content) == "Title\nFirst body."

    def test_tabs_breaks_and_non_breaking_hyphens_are_kept(self):
        content = _docx(_paragraph("<w:t>a</w:t><w:tab/><w:t>b</w:t><w:br/><w:t>c</w:t><w:noBreakHyphen/><w:t>d</w:t>"))
        assert DocxParser().extract_text(content) == "a\tb\nc-d"

    def test_deleted_revisions_and_field_codes_are_left_out_while_insertions_and_links_are_kept(self):
        body = (
            "<w:p>"
            "<w:r><w:t>kept </w:t></w:r>"
            "<w:del><w:r><w:delText>removed </w:delText></w:r></w:del>"
            "<w:ins><w:r><w:t>inserted </w:t></w:r></w:ins>"
            "<w:r><w:instrText>HYPERLINK x</w:instrText></w:r>"
            "<w:hyperlink><w:r><w:t>link</w:t></w:r></w:hyperlink>"
            "</w:p>"
        )
        assert DocxParser().extract_text(_docx(body)) == "kept inserted link"

    def test_tables_become_tab_separated_rows(self):
        table = (
            "<w:tbl><w:tblPr/>"
            "<w:tr><w:tc><w:p><w:r><w:t>Name</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Mass</w:t></w:r></w:p></w:tc></w:tr>"
            "<w:tr><w:trPr/><w:tc><w:tcPr/><w:p><w:r><w:t>DF44</w:t></w:r></w:p><w:p><w:r><w:t>(UDG)</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>3e8</w:t></w:r></w:p></w:tc></w:tr>"
            "</w:tbl>"
        )
        assert DocxParser().extract_text(_docx(_paragraph("<w:t>Table 1</w:t>") + table)) == (
            "Table 1\nName\tMass\nDF44 (UDG)\t3e8"
        )

    def test_content_controls_are_read(self):
        body = "<w:sdt><w:sdtContent>" + _paragraph("<w:t>in a control</w:t>") + "</w:sdtContent></w:sdt>"
        assert DocxParser().extract_text(_docx(body)) == "in a control"

    def test_blank_lines_collapse_and_the_text_is_stripped(self):
        body = "<w:p/>" * 4 + _paragraph("<w:t>a</w:t>") + "<w:p/>" * 5 + _paragraph("<w:t>b</w:t>") + "<w:sectPr/>"
        assert DocxParser().extract_text(_docx(body)) == "a\n\nb"

    def test_notes_are_appended_only_when_asked_and_separators_are_skipped(self):
        footnotes = (
            '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:t>----</w:t></w:r></w:p></w:footnote>'
            '<w:footnote w:id="1"><w:p><w:r><w:t>A note.</w:t></w:r></w:p></w:footnote>'
        )
        content = _docx(_paragraph("<w:t>Body</w:t>"), footnotes=footnotes)
        assert DocxParser().extract_text(content) == "Body"
        assert DocxParser(include_notes=True).extract_text(content) == "Body\nA note."

    def test_a_document_without_a_namespace_is_read(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", "<document><body><p><r><t>plain</t></r></p></body></document>")
        assert DocxParser(include_notes=True).extract_text(buffer.getvalue()) == "plain"

    def test_a_document_without_a_body_is_empty(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", f"<w:document {W}/>")
        assert DocxParser().extract_text(buffer.getvalue()) == ""

    def test_a_payload_that_is_not_a_zip_raises_a_parsing_error(self):
        with pytest.raises(ParsingError, match="not a zip archive"):
            DocxParser().extract_text(b"%PDF-1.7 not a zip")

    def test_an_archive_without_a_document_part_raises_a_parsing_error(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("xl/workbook.xml", "<workbook/>")
        with pytest.raises(ParsingError, match="no word/document.xml"):
            DocxParser().extract_text(buffer.getvalue())

    def test_malformed_xml_raises_a_parsing_error(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", "<w:document")
        with pytest.raises(ParsingError, match="not well-formed XML"):
            DocxParser().extract_text(buffer.getvalue())

    def test_an_empty_part_raises_a_parsing_error(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", "")
        with pytest.raises(ParsingError):
            DocxParser().extract_text(buffer.getvalue())

    def test_a_part_larger_than_the_limit_is_refused(self):
        content = _docx(_paragraph("<w:t>" + "x" * 5000 + "</w:t>"))
        with pytest.raises(ParsingError, match="larger than 1000 bytes"):
            DocxParser(max_part_bytes=1000).extract_text(content)

    def test_entities_are_not_expanded(self):
        buffer = io.BytesIO()
        hostile = (
            '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
            f"<w:document {W}><w:body><w:p><w:r><w:t>&e;</w:t></w:r></w:p></w:body></w:document>"
        )
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", hostile)
        assert "root:" not in DocxParser().extract_text(buffer.getvalue())

    def test_rejects_a_non_positive_part_limit(self):
        with pytest.raises(ValueError, match="positive"):
            DocxParser(max_part_bytes=0)


JATS = (Path(__file__).parent / "data" / "jats_article.xml").read_bytes()


class TestJatsXmlParser:
    def test_front_matter(self):
        article = JatsXmlParser().parse_article(JATS)
        assert article.title == "Dark matter in ultra-diffuse galaxies"
        assert article.authors == ("Pieter van Dokkum", "The Dragonfly Team", "Solo Author")
        assert article.keywords == ("galaxies", "dark matter")
        assert article.journal == "The Astrophysical Journal"
        assert article.identifiers == {"pmcid": "PMC123", "doi": "10.1000/xyz"}
        assert article.doi == "10.1000/xyz"
        assert article.published == "2024-03-07"

    def test_the_abstract_prefers_the_plain_abstract_and_keeps_its_section_titles(self):
        article = JatsXmlParser().parse_article(JATS)
        assert article.abstract == "Background\n\nUDGs are large but faint.\n\nResults\n\nDF44 has M mass."

    def test_sections_keep_their_order_levels_and_mixed_content(self):
        sections = JatsXmlParser().parse_article(JATS).sections
        assert [(section.title, section.level) for section in sections] == [
            ("", 0),
            ("Introduction", 1),
            ("Sample", 2),
            ("", 1),
        ]
        assert sections[0].text == "An unnumbered lead paragraph."
        assert sections[1].text == (
            "Ultra-diffuse galaxies were found [1].\n\n"
            "Text before a list\n\nfirst item\n\nsecond item\n\nand after it."
        )
        assert sections[2].text == "Images of DF44.\n\nTable 1\n\nName\tDistance\n\nDF44\t100 Mpc"

    def test_tables_can_be_left_out_while_captions_stay(self):
        sections = JatsXmlParser(include_tables=False).parse_article(JATS).sections
        assert sections[2].text == "Images of DF44.\n\nTable 1"

    def test_references_are_listed_in_order(self):
        article = JatsXmlParser().parse_article(JATS)
        assert article.references == ("van Dokkum P. et al. 2015, ApJL, 798, L45", "Koda 2015")

    def test_extract_text_has_title_abstract_and_body_but_no_references_or_footnotes(self):
        text = JatsXmlParser().extract_text(JATS)
        assert text.startswith("Dark matter in ultra-diffuse galaxies\n\nBackground")
        assert "Introduction\n\nUltra-diffuse galaxies were found [1]." in text
        assert "A footnote" not in text
        assert "Koda" not in text
        assert "Table note" not in text
        assert "1." not in text.split("Introduction")[0].split("\n")[-1]

    def test_a_bare_article_root_with_little_metadata(self):
        article = JatsXmlParser().parse_article(
            b"<article><front><article-meta><title-group><article-title>T</article-title></title-group>"
            b"<abstract abstract-type='teaser'><p>Only teaser.</p></abstract>"
            b"<pub-date><month>13</month><year>2020</year></pub-date>"
            b"<pub-date><month>2</month><day>40</day><year>2021</year></pub-date>"
            b"</article-meta></front></article>"
        )
        assert article == JatsArticle(title="T", abstract="Only teaser.", published="2020")
        assert article.body_text() == ""

    def test_the_earliest_date_wins_with_its_own_precision(self):
        article = JatsXmlParser().parse_article(
            b"<article><front><article-meta>"
            b"<pub-date><month>2</month><day>40</day><year>2021</year></pub-date>"
            b"<pub-date><month>February</month><year>2021</year></pub-date>"
            b"</article-meta></front></article>"
        )
        assert article.published == "2021-02"

    def test_an_article_without_front_matter_or_dates(self):
        article = JatsXmlParser().parse_article(b"<article><body><sec><title>Only</title></sec></body></article>")
        assert article == JatsArticle(title="", abstract="", sections=(JatsSection("Only", 1, ""),))
        assert JatsXmlParser().extract_text(b"<article><body><sec><title>Only</title></sec></body></article>") == (
            "Only"
        )

    def test_comments_are_ignored_but_their_tail_text_is_kept(self):
        article = JatsXmlParser().parse_article(b"<article><body><p>a <!-- note --> b</p></body></article>")
        assert article.sections[0].text == "a b"

    @pytest.mark.parametrize(
        ("content", "message"),
        [(b"<not-closed", "not well-formed XML"), (b"<pmc-articleset/>", "holds no <article>")],
    )
    def test_unreadable_payloads_raise_parsing_errors(self, content, message):
        with pytest.raises(ParsingError, match=message):
            JatsXmlParser().parse_article(content)
