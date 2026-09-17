from __future__ import annotations

import re

DEFAULT_TRIM_PATTERNS: tuple[str, ...] = (
    r"\\begin\{thebibliography\}",
    r"\\bibliography\{",
    r"\\printbibliography",
    r"\n\s*references\s*\n",
    r"\n\s*bibliography\s*\n",
    r"\n\s*acknowledgments?\s*\n",
    r"\n\s*literature cited\s*\n",
)


def trim_after_references(text: str | None, patterns: tuple[str, ...] = DEFAULT_TRIM_PATTERNS) -> str | None:
    """Cut ``text`` at the earliest match of any pattern, such as a references or acknowledgments heading.

    Patterns are regular expressions matched without regard to case. The kept
    text has trailing whitespace removed. ``text`` is returned unchanged when
    no pattern matches, and ``None`` or ``""`` is returned as given.
    """
    if not text:
        return text

    cutoff = len(text)
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match and match.start() < cutoff:
            cutoff = match.start()

    return text[:cutoff].rstrip() if cutoff < len(text) else text
