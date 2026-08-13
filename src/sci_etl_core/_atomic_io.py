from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(destination: str | Path, text: str, encoding: str = "utf-8") -> None:
    """Write text through a same-directory temp file and an atomic rename.

    The payload is flushed and fsynced before the rename, so a crash or a
    cancellation can leave either the previous file or the complete new one,
    never a truncated destination.
    """
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
