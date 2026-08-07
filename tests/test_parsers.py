from __future__ import annotations

import gzip
import io
import tarfile

import pytest

from sci_etl_core.parsers.html import HtmlTextParser
from sci_etl_core.parsers.latex import LatexTarballParser
from sci_etl_core.parsers.reference_trimmer import DEFAULT_TRIM_PATTERNS, trim_after_references


class TestHtmlTextParser:
    def test_extracts_visible_text_and_strips_tags(self):
        html = b"<html><body><h1>Title</h1><p>Hello <b>world</b></p></body></html>"
        assert HtmlTextParser().extract_text(html) == "Title Hello world"

    def test_returns_empty_string_for_empty_input(self):
        assert HtmlTextParser().extract_text(b"") == ""

    def test_collapses_whitespace_across_elements(self):
        html = b"<div>a</div>\n\n   <div>b</div>"
        assert HtmlTextParser().extract_text(html) == "a b"


class TestLatexTarballParser:
    @staticmethod
    def _make_tarball(files: dict[str, bytes]) -> bytes:
        buffer = io.BytesIO()
        with tarfile.open(mode="w:gz", fileobj=buffer) as tar:
            for name, content in files.items():
                info = tarfile.TarInfo(name=name)
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
        return buffer.getvalue()

    def test_concatenates_all_tex_files(self):
        tarball = self._make_tarball({"main.tex": b"Main body.", "appendix.tex": b"Appendix body."})
        text = LatexTarballParser().extract_text(tarball)
        assert "Main body." in text
        assert "Appendix body." in text

    def test_ignores_non_tex_files(self):
        tarball = self._make_tarball({"main.tex": b"Keep this.", "figure.png": b"\x89PNG binary"})
        text = LatexTarballParser().extract_text(tarball)
        assert "Keep this." in text
        assert "PNG" not in text

    def test_strips_line_comments_but_keeps_escaped_percent(self):
        tarball = self._make_tarball({"main.tex": b"visible %hidden comment\n50\\% efficiency"})
        text = LatexTarballParser().extract_text(tarball)
        assert "visible" in text
        assert "hidden comment" not in text
        assert "50\\% efficiency" in text

    def test_returns_empty_when_no_tex_present(self):
        tarball = self._make_tarball({"data.csv": b"1,2,3"})
        assert LatexTarballParser().extract_text(tarball) == ""


class TestReferenceTrimmer:
    @pytest.mark.parametrize(
        "text",
        [
            "Body text.\n\\begin{thebibliography}{99}\n\\bibitem{a} X",
            "Body text.\n\\bibliography{refs}",
            "Body text.\nReferences\n[1] X",
            "Body text.\nAcknowledgments\nThanks.",
        ],
    )
    def test_trims_everything_from_the_first_reference_marker(self, text):
        result = trim_after_references(text)
        assert result == "Body text."

    def test_trims_at_the_earliest_marker_when_multiple_present(self):
        text = "Intro.\nAcknowledgments\nmid\nReferences\nend"
        assert trim_after_references(text) == "Intro."

    def test_returns_text_unchanged_when_no_marker_present(self):
        text = "A clean body with no bibliography section."
        assert trim_after_references(text) == text

    @pytest.mark.parametrize("empty", [None, ""])
    def test_passes_through_empty_values(self, empty):
        assert trim_after_references(empty) == empty

    def test_matching_is_case_insensitive(self):
        assert trim_after_references("Body.\nREFERENCES\n[1]") == "Body."

    def test_accepts_custom_patterns(self):
        assert trim_after_references("Body.\nENDE\ntail", patterns=(r"\nENDE\n",)) == "Body."

    def test_default_patterns_are_exposed(self):
        assert r"\\begin\{thebibliography\}" in DEFAULT_TRIM_PATTERNS
