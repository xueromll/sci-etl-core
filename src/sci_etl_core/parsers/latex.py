from __future__ import annotations

import gzip
import io
import posixpath
import re
import tarfile
import zlib

from sci_etl_core.exceptions import ParsingError
from sci_etl_core.parsers.base import Parser

_COMMENT = re.compile(rb"(?<!\\)%.*")
_INCLUDE = re.compile(rb"\\(?:input|include|subfile)\s*\{([^}]+)\}")
_ROOT_MARKER = b"\\documentclass"
_PDF_MAGIC = b"%PDF"
_TEX_SUFFIX = ".tex"


class LatexTarballParser(Parser):
    """Extract TeX source from an arXiv e-print.

    arXiv serves a multi-file submission as a tarball and a single-file
    submission as one gzipped ``.tex`` file; both are accepted. Line comments
    are removed from each file before anything else, so commented-out
    ``\\input`` commands are ignored.

    In a tarball, each root document (a file declaring ``\\documentclass``) is
    expanded in place by following ``\\input``, ``\\include`` and ``\\subfile``,
    so the body reads in document order and a ``\\bibliography`` command at the
    end of the root cannot land before the sections it includes. ``.tex`` files
    that no root includes are appended afterwards in name order.

    Members are read in memory and never extracted to disk. With
    ``max_tex_bytes``, at most that many bytes of TeX are decompressed from one
    e-print, across all its ``.tex`` members, so an archive that expands
    without bound cannot exhaust memory.
    """

    def __init__(self, max_tex_bytes: int | None = None) -> None:
        """Configure the parser.

        Raises:
            ValueError: ``max_tex_bytes`` is less than 1.
        """
        if max_tex_bytes is not None and max_tex_bytes < 1:
            raise ValueError("max_tex_bytes must be a positive integer")
        self._max_tex_bytes = max_tex_bytes

    def extract_text(self, content: bytes) -> str:
        """Return the submission's TeX source as text.

        Raises:
            ParsingError: The payload is neither a tarball nor gzipped TeX, for
                example a PDF-only submission, or its TeX exceeds
                ``max_tex_bytes``.
        """
        sources = self._read_tarball(content)
        if sources is None:
            body = _COMMENT.sub(b"", self._read_single_file(content))
        else:
            body = self._assemble(sources)
        return body.decode("utf-8", errors="ignore")

    def _read_tarball(self, content: bytes) -> dict[str, bytes] | None:
        try:
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:*") as tar:
                sources: dict[str, bytes] = {}
                total = 0
                for member in tar:
                    if not (member.isfile() and member.name.endswith(_TEX_SUFFIX)):
                        continue
                    total += member.size
                    self._check_size(total)
                    extracted = tar.extractfile(member)
                    if extracted is not None:
                        sources[posixpath.normpath(member.name)] = _COMMENT.sub(b"", extracted.read())
                return sources
        except (tarfile.TarError, EOFError, zlib.error):
            return None

    def _read_single_file(self, content: bytes) -> bytes:
        limit = -1 if self._max_tex_bytes is None else self._max_tex_bytes + 1
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(content)) as compressed:
                payload = compressed.read(limit)
        except (OSError, EOFError, zlib.error) as exc:
            raise ParsingError(f"E-print is neither a tarball nor gzipped TeX: {exc}") from exc
        self._check_size(len(payload))
        if payload.startswith(_PDF_MAGIC):
            raise ParsingError("E-print is a gzipped PDF, not TeX source")
        return payload

    def _check_size(self, size: int) -> None:
        if self._max_tex_bytes is not None and size > self._max_tex_bytes:
            raise ParsingError(f"E-print TeX exceeds {self._max_tex_bytes} bytes once decompressed")

    @classmethod
    def _assemble(cls, sources: dict[str, bytes]) -> bytes:
        included: set[str] = set()
        parts: list[bytes] = []
        for root in sorted(name for name, body in sources.items() if _ROOT_MARKER in body):
            if root not in included:
                parts.append(cls._expand(root, sources, included))
        parts.extend(sources[name] for name in sorted(sources) if name not in included)
        return b"\n".join(parts)

    @classmethod
    def _expand(cls, name: str, sources: dict[str, bytes], included: set[str]) -> bytes:
        included.add(name)

        def substitute(match: re.Match[bytes]) -> bytes:
            target = cls._resolve(match.group(1), name, sources)
            if target is None or target in included:
                return match.group(0)
            return cls._expand(target, sources, included)

        return _INCLUDE.sub(substitute, sources[name])

    @staticmethod
    def _resolve(reference: bytes, including: str, sources: dict[str, bytes]) -> str | None:
        """Map an include argument to a file in the archive.

        TeX resolves paths against the directory the root is compiled from, so
        the archive root is tried before the including file's own directory.
        """
        stem = reference.decode("utf-8", errors="ignore").strip()
        if not stem.endswith(_TEX_SUFFIX):
            stem += _TEX_SUFFIX
        for candidate in (stem, posixpath.join(posixpath.dirname(including), stem)):
            normalized = posixpath.normpath(candidate)
            if normalized in sources:
                return normalized
        return None
