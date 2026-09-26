from __future__ import annotations

import gzip
import io
import tarfile

import httpx
import pytest

from sci_etl_core.exceptions import ExtractionError, UpstreamError
from sci_etl_core.extractors.arxiv_async import AsyncArxivExtractor
from sci_etl_core.models import RawRecord
from sci_etl_core.parsers.latex import LatexTarballParser
from sci_etl_core.parsers.pdf import PdfPlumberParser

RECORD = RawRecord(record_id="2401.00001v1", title="t", abstract="abstract fallback")
EPRINT = "https://arxiv.org/e-print/"
PDF = "https://arxiv.org/pdf/"
MIRROR = "https://mirror.example/pdf/"
LISTING = AsyncArxivExtractor.API_URL


def _pdf(lines: list[str]) -> bytes:
    stream = ("BT /F1 12 Tf 14 TL 72 720 Td " + " ".join(f"({line}) Tj T*" for line in lines) + " ET").encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    out.write("".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def _tarball(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


async def _no_sleep(_seconds: float) -> None:
    return None


def _extractor(routes: dict[str, httpx.Response], **kwargs) -> tuple[AsyncArxivExtractor, list[str]]:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested.append(url)
        for prefix, response in routes.items():
            if url.startswith(prefix):
                return response
        return httpx.Response(404)

    kwargs.setdefault("sleep", _no_sleep)
    extractor = AsyncArxivExtractor(
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        PdfPlumberParser(),
        LatexTarballParser(),
        sleep_before_search=0,
        **kwargs,
    )
    return extractor, requested


class TestEprintFormats:
    @pytest.mark.asyncio
    async def test_single_gzipped_tex_file_is_used(self):
        extractor, requested = _extractor({EPRINT: httpx.Response(200, content=gzip.compress(b"TEX body"))})
        assert await extractor.fetch_full_text(RECORD) == "TEX body"
        assert not any(url.startswith(PDF) for url in requested)

    @pytest.mark.asyncio
    async def test_tarball_is_used(self):
        extractor, _ = _extractor({EPRINT: httpx.Response(200, content=_tarball({"m.tex": b"TAR body"}))})
        assert await extractor.fetch_full_text(RECORD) == "TAR body"

    @pytest.mark.asyncio
    async def test_pdf_only_submission_falls_back_to_the_pdf(self):
        logged: list[str] = []
        pdf = httpx.Response(200, content=_pdf(["PDF body text"]))
        extractor, _ = _extractor(
            {EPRINT: httpx.Response(200, content=_pdf(["eprint"])), PDF: pdf}, logger=logged.append
        )
        assert "PDF body text" in await extractor.fetch_full_text(RECORD)
        assert any("LaTeX unusable" in message for message in logged)

    @pytest.mark.asyncio
    async def test_unreadable_artifacts_fall_back_to_the_abstract(self):
        logged: list[str] = []
        extractor, _ = _extractor(
            {
                EPRINT: httpx.Response(200, content=b"not an archive"),
                PDF: httpx.Response(200, content=b"<html>captcha</html>"),
            },
            logger=logged.append,
        )
        assert await extractor.fetch_full_text(RECORD) == "abstract fallback"
        assert any("PDF unusable" in message for message in logged)

    @pytest.mark.asyncio
    async def test_an_e_print_past_the_download_limit_is_passed_over_for_the_pdf(self):
        routes = {
            EPRINT: httpx.Response(200, content=b"x" * 4096),
            PDF: httpx.Response(200, content=_pdf(["Small PDF body"])),
        }
        logged: list[str] = []
        extractor, _requested = _extractor(routes, max_download_bytes=2048, logger=logged.append)
        assert "Small PDF body" in await extractor.fetch_full_text(RECORD)
        assert any("LaTeX fetch" in line and "exceeds 2048 bytes" in line for line in logged)

    @pytest.mark.asyncio
    async def test_a_listing_past_the_download_limit_is_an_extraction_error(self):
        extractor, requested = _extractor({LISTING: httpx.Response(200, content=b"x" * 100)}, max_download_bytes=10)
        with pytest.raises(ExtractionError, match="exceeds 10 bytes"):
            await extractor._search("q", 10, 0)
        assert len(requested) == 1

    @pytest.mark.asyncio
    async def test_redirected_pdf_is_followed(self):
        extractor, requested = _extractor(
            {
                PDF: httpx.Response(301, headers={"Location": f"{MIRROR}2401.00001v1"}),
                MIRROR: httpx.Response(200, content=_pdf(["Mirrored body"])),
            }
        )
        assert "Mirrored body" in await extractor.fetch_full_text(RECORD)
        assert any(url.startswith(MIRROR) for url in requested)


class TestListingStatus:
    @pytest.mark.asyncio
    async def test_rejected_request_is_not_retried_and_not_upstream(self):
        extractor, requested = _extractor({LISTING: httpx.Response(400, content=b"<feed/>")})
        with pytest.raises(ExtractionError, match="status 400") as excinfo:
            await extractor._search("bad query", 10, 0)
        assert not isinstance(excinfo.value, UpstreamError)
        assert len(requested) == 1

    @pytest.mark.asyncio
    async def test_any_success_status_returns_the_payload(self):
        extractor, _ = _extractor({LISTING: httpx.Response(203, content=b"<feed/>")})
        assert await extractor._search("q", 10, 0) == b"<feed/>"

    @pytest.mark.asyncio
    async def test_no_backoff_after_the_final_retryable_attempt(self, mocker):
        sleep = mocker.AsyncMock()
        extractor, requested = _extractor({LISTING: httpx.Response(503)}, sleep=sleep, max_retries=3)
        with pytest.raises(UpstreamError, match="after 3 attempts"):
            await extractor._search("q", 10, 0)
        assert len(requested) == 3
        assert [call.args[0] for call in sleep.await_args_list] == [0, 1.0, 2.0]

    @pytest.mark.asyncio
    async def test_redirect_loop_is_retried_then_reported_upstream(self):
        extractor, _ = _extractor({LISTING: httpx.Response(302, headers={"Location": LISTING})}, max_retries=2)
        with pytest.raises(UpstreamError) as excinfo:
            await extractor._search("q", 10, 0)
        assert isinstance(excinfo.value.__cause__, httpx.TooManyRedirects)


class TestRetryAfter:
    @pytest.mark.asyncio
    async def test_listing_retry_waits_as_long_as_arxiv_asks(self, mocker):
        sleep = mocker.AsyncMock()
        logged: list[str] = []
        extractor, requested = _extractor(
            {LISTING: httpx.Response(429, headers={"Retry-After": "7"})},
            sleep=sleep,
            max_retries=2,
            logger=logged.append,
        )
        with pytest.raises(UpstreamError, match="after 2 attempts"):
            await extractor._search("q", 10, 0)
        assert len(requested) == 2
        assert [call.args[0] for call in sleep.await_args_list] == [0, 7.0]
        assert any("arXiv search attempt 1 failed" in message and "retrying in 7 s" in message for message in logged)

    @pytest.mark.asyncio
    async def test_long_server_wait_is_capped(self, mocker):
        sleep = mocker.AsyncMock()
        extractor, _ = _extractor(
            {LISTING: httpx.Response(503, headers={"Retry-After": "3600"})},
            sleep=sleep,
            max_retries=2,
            max_retry_after=30,
        )
        with pytest.raises(UpstreamError):
            await extractor._search("q", 10, 0)
        assert [call.args[0] for call in sleep.await_args_list] == [0, 30]

    @pytest.mark.asyncio
    async def test_full_text_retry_honors_retry_after(self, mocker):
        sleep = mocker.AsyncMock()
        extractor, _ = _extractor(
            {PDF: httpx.Response(503, headers={"Retry-After": "4"})},
            sleep=sleep,
            max_retries=2,
        )
        with pytest.raises(UpstreamError, match="Full-text retrieval failed"):
            await extractor.fetch_full_text(RECORD)
        assert [call.args[0] for call in sleep.await_args_list] == [4.0]

    def test_negative_retry_after_cap_is_rejected(self):
        with pytest.raises(ValueError, match="max_retry_after"):
            _extractor({}, max_retry_after=-1)


class TestListingParsing:
    def _parse(self, entries: str):
        extractor, _ = _extractor({})
        return extractor._parse_listing(f"<feed xmlns='http://www.w3.org/2005/Atom'>{entries}</feed>".encode())

    def test_landing_page_is_the_alternate_html_link(self):
        records, _ = self._parse(
            "<entry><id>http://arxiv.org/abs/2401.00001v1</id>"
            "<link href='http://arxiv.org/abs/2401.00001v1' rel='alternate' type='text/html'/>"
            "<link title='pdf' href='http://arxiv.org/pdf/2401.00001v1' rel='related' type='application/pdf'/>"
            "</entry>"
        )
        assert records[0].source_url == "http://arxiv.org/abs/2401.00001v1"

    def test_entry_without_a_landing_page_has_no_source_url(self):
        records, _ = self._parse(
            "<entry><id>http://arxiv.org/abs/2401.00001v1</id>"
            "<link href='http://arxiv.org/pdf/2401.00001v1' rel='related' type='application/pdf'/>"
            "<link rel='alternate' type='text/html'/>"
            "</entry>"
        )
        assert records[0].source_url is None

    def test_entry_without_an_id_is_skipped_but_counted(self):
        records, total = self._parse(
            "<entry><title>no id</title></entry>"
            "<entry><id>http://arxiv.org/abs/2401.00002v1</id><title>kept</title></entry>"
        )
        assert [record.record_id for record in records] == ["2401.00002v1"]
        assert total == 2
