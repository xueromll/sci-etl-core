from __future__ import annotations

import gzip
import io
import tarfile

import pytest

from sci_etl_core.exceptions import ParsingError
from sci_etl_core.parsers.latex import LatexTarballParser
from sci_etl_core.parsers.pdf import PdfPlumberParser
from sci_etl_core.parsers.reference_trimmer import trim_after_references


def _tarball(files: dict[str, bytes], mode: str = "w:gz") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode=mode) as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


class TestEprintPayloads:
    def test_single_gzipped_tex_file_is_accepted(self):
        assert LatexTarballParser().extract_text(gzip.compress(b"Body %comment\nMore")) == "Body \nMore"

    def test_uncompressed_tarball_is_accepted(self):
        payload = _tarball({"main.tex": b"Plain tar body"}, mode="w")
        assert LatexTarballParser().extract_text(payload) == "Plain tar body"

    def test_empty_payload_yields_empty_text(self):
        assert LatexTarballParser().extract_text(b"") == ""

    @pytest.mark.parametrize("payload", [b"%PDF-1.4 not tex", b"plain bytes that are not an archive"])
    def test_payload_that_is_not_an_archive_raises(self, payload):
        with pytest.raises(ParsingError, match="neither a tarball nor gzipped TeX"):
            LatexTarballParser().extract_text(payload)

    def test_gzipped_pdf_raises(self):
        with pytest.raises(ParsingError, match="gzipped PDF"):
            LatexTarballParser().extract_text(gzip.compress(b"%PDF-1.4 body"))

    def test_truncated_tarball_raises(self):
        payload = _tarball({"main.tex": b"x" * 4096, "other.tex": b"y" * 4096})
        with pytest.raises(ParsingError):
            LatexTarballParser().extract_text(payload[: len(payload) // 2])


class TestDocumentAssembly:
    def test_included_sections_precede_the_bibliography(self):
        payload = _tarball(
            {
                "main.tex": b"\\documentclass{article}\\begin{document}\\input{intro}\n"
                b"\\include{results.tex}\n\\bibliography{refs}\\end{document}",
                "intro.tex": b"INTRO body",
                "results.tex": b"RESULTS body",
            }
        )
        text = LatexTarballParser().extract_text(payload)
        assert text.index("INTRO") < text.index("RESULTS") < text.index("\\bibliography")
        trimmed = trim_after_references(text)
        assert "INTRO body" in trimmed
        assert "RESULTS body" in trimmed

    def test_paths_resolve_from_the_archive_root_or_the_including_directory(self):
        payload = _tarball(
            {
                "paper/main.tex": b"\\documentclass{x}\\input{sections/a}\\subfile{top}",
                "paper/sections/a.tex": b"A[\\input{b}]",
                "paper/sections/b.tex": b"DEEP",
                "top.tex": b"TOP",
            }
        )
        assert LatexTarballParser().extract_text(payload) == "\\documentclass{x}A[DEEP]TOP"

    def test_commented_out_inputs_are_not_expanded(self):
        payload = _tarball({"main.tex": b"\\documentclass{x}\n%\\input{old}\nBODY", "old.tex": b"OLD"})
        text = LatexTarballParser().extract_text(payload)
        assert "\\input{old}" not in text
        assert text.index("BODY") < text.index("OLD")

    def test_files_no_root_includes_are_appended_in_name_order(self):
        payload = _tarball({"main.tex": b"\\documentclass{x}MAIN", "z.tex": b"ZED", "a.tex": b"AAA"})
        assert LatexTarballParser().extract_text(payload) == "\\documentclass{x}MAIN\nAAA\nZED"

    def test_cyclic_and_missing_includes_are_left_in_place(self):
        payload = _tarball(
            {"main.tex": b"\\documentclass{x}\\input{loop}\\input{missing}", "loop.tex": b"LOOP\\input{main}"}
        )
        assert LatexTarballParser().extract_text(payload) == "\\documentclass{x}LOOP\\input{main}\\input{missing}"


class TestPdfParsingErrors:
    def test_parser_failure_is_raised_as_parsing_error(self, mocker):
        mocker.patch("sci_etl_core.parsers.pdf.pdfplumber.open", side_effect=ValueError("No /Root object"))
        with pytest.raises(ParsingError, match="PDF could not be parsed"):
            PdfPlumberParser().extract_text(b"garbage")

    def test_bytes_that_are_not_a_pdf_raise_parsing_error(self):
        with pytest.raises(ParsingError):
            PdfPlumberParser().extract_text(b"not a pdf at all")
