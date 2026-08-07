from __future__ import annotations

import io
import re
import tarfile

from sci_etl_core.parsers.base import Parser


class LatexTarballParser(Parser):
    def extract_text(self, content: bytes) -> str:
        chunks: list[bytes] = []
        with tarfile.open(mode="r|gz", fileobj=io.BytesIO(content)) as tar:
            for member in tar:
                if member.isfile() and member.name.endswith(".tex"):
                    extracted = tar.extractfile(member)
                    if extracted:
                        chunks.append(extracted.read())
        if not chunks:
            return ""
        cleaned = re.sub(rb"(?<!\\)%.*", b"", b"\n".join(chunks))
        return cleaned.decode("utf-8", errors="ignore")
