from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

_REPLACE_ATTEMPTS = 6
_REPLACE_BACKOFF_SECONDS = 0.05


def atomic_write_text(destination: str | Path, text: str, encoding: str = "utf-8") -> None:
    """Write text through a same-directory temp file and an atomic rename.

    The payload is flushed and fsynced before the rename, so a crash or a
    cancellation can leave either the previous file or the complete new one,
    never a truncated destination. Newline translation is disabled so the
    payload lands byte for byte: content that already carries CRLF, such as
    pandas CSV output, would otherwise gain a second carriage return on Windows.

    On Windows a rename onto a file that another process holds open fails with
    ``PermissionError``. Such holds are usually brief (a reader, an indexer, a
    sync client), so the rename is retried with exponential backoff for about
    1.5 seconds before the error is raised.
    """
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(temp_path, target)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def _replace_with_retry(source: Path, target: Path) -> None:
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_BACKOFF_SECONDS * 2**attempt)
