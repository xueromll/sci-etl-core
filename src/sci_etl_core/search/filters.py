from __future__ import annotations

import json
import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, time
from typing import Any

SNIPPET_OPEN = "\x02"
SNIPPET_CLOSE = "\x03"
SNIPPET_ELLIPSIS = "…"
SNIPPET_TOKENS = 24

_UNSTORABLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]")
_SURROGATE = re.compile(r"[\ud800-\udfff]")


@dataclass(frozen=True, slots=True)
class MetadataFilter:
    """Keep the records tagged with any of ``values`` under ``key``, or with ``negated``, drop them.

    A record's tags under ``key`` are the values :func:`tag_rows` derives from
    its metadata, so ``2024`` stored as an integer matches the value ``"2024"``.
    ``values`` may be any collection of strings; it is stored as a
    :class:`frozenset`.

    Raises:
        TypeError: ``values`` is a single string, which would otherwise be
            read as a set of characters.
        ValueError: ``values`` is empty, so the filter could never match.
    """

    key: str
    values: frozenset[str]
    negated: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.values, str):
            raise TypeError("values must be a collection of strings, not a single string")
        object.__setattr__(self, "values", frozenset(self.values))
        if not self.values:
            raise ValueError(f"The filter on {self.key!r} needs at least one value")


def validate_filters(filters: Iterable[MetadataFilter], allowed_keys: Collection[str] | None = None) -> None:
    """Raise unless ``filters`` holds at most one filter per key, each on an allowed key.

    Several values of one key belong in a single filter's ``values``, whatever
    the filters' ``negated`` flags. ``allowed_keys`` is ``None`` when any key is
    allowed.

    Raises:
        ValueError: Two filters share a key, or a key is not in ``allowed_keys``.
    """
    seen: set[str] = set()
    for metadata_filter in filters:
        if allowed_keys is not None:
            validate_facet_keys((metadata_filter.key,), allowed_keys)
        if metadata_filter.key in seen:
            raise ValueError(
                f"Only one filter per key is allowed, and {metadata_filter.key!r} has two; "
                "put several values in one filter's values"
            )
        seen.add(metadata_filter.key)


def validate_facet_keys(keys: Iterable[str], allowed_keys: Collection[str]) -> None:
    """Raise unless every key in ``keys`` is one of ``allowed_keys``.

    Raises:
        ValueError: A key is not in ``allowed_keys``.
    """
    for key in keys:
        if key not in allowed_keys:
            expected = ", ".join(sorted(allowed_keys)) or "none configured"
            raise ValueError(f"{key!r} is not a facet key of this store; facet keys: {expected}")


def matches_filters(metadata: Mapping[str, Any], filters: Iterable[MetadataFilter]) -> bool:
    """Report whether a record with ``metadata`` passes every filter in ``filters``."""
    for metadata_filter in filters:
        tagged = not metadata_filter.values.isdisjoint(_tag_values(metadata.get(metadata_filter.key)))
        if tagged is metadata_filter.negated:
            return False
    return True


def tag_rows(metadata: Mapping[str, Any], facet_keys: Iterable[str]) -> tuple[tuple[str, str], ...]:
    """Return the distinct ``(key, value)`` tags of ``metadata`` under ``facet_keys``.

    A string, or an integer that is not a ``bool``, gives one tag, and a list or
    tuple of them gives one tag per element. Empty strings and every other type
    are skipped. Keys are in sorted order, and the values of each key are sorted
    and never repeat, so the rows can never collide with each other.
    """
    return tuple(
        (key, value) for key in sorted(set(facet_keys)) for value in sorted(_tag_values(metadata.get(key)))
    )


def _tag_values(value: Any) -> set[str]:
    items = value if isinstance(value, (list, tuple)) else (value,)
    return {str(item) for item in items if _is_tag(item)}


def _is_tag(item: Any) -> bool:
    if isinstance(item, str):
        return item != ""
    return isinstance(item, int) and not isinstance(item, bool)


def encode_metadata(metadata: Mapping[str, Any]) -> str:
    """Encode ``metadata`` as the JSON text a text search store keeps.

    Non-ASCII text stays readable UTF-8. A value JSON cannot hold never fails the
    encoding: a ``date``, ``datetime``, or ``time`` becomes its ISO 8601 text, a
    ``bytes`` or ``bytearray`` its ``repr``, and anything else its ``str``. The
    encoding is one-way, so a ``datetime`` reads back as a string. A lone
    surrogate is written as a JSON escape, so the text can always be stored.
    """
    encoded = json.dumps(metadata, ensure_ascii=False, default=_json_default)
    return _SURROGATE.sub(lambda match: f"\\u{ord(match.group()):04x}", encoded)


def _json_default(value: Any) -> str:
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return repr(value)
    return str(value)


def sanitize_text(text: str) -> str:
    """Replace control characters other than tab and line breaks, and lone surrogates, with spaces.

    The FTS5 tokenizer already treats every replaced character as a separator,
    so what matches is unchanged. The replacement guarantees that the snippet
    markers :data:`SNIPPET_OPEN` and :data:`SNIPPET_CLOSE` never occur in stored
    text, and that SQLite can always receive it.
    """
    return _UNSTORABLE.sub(" ", text)


def split_markers(raw: str) -> tuple[str, tuple[tuple[int, int], ...]]:
    """Strip snippet markers from ``raw``, returning the plain text and the highlighted spans.

    Each span is a half-open ``[start, end)`` character range of the plain text.
    :data:`SNIPPET_OPEN` opens a span and :data:`SNIPPET_CLOSE` closes it. The
    function never raises: a second opening marker inside a span and a closing
    marker outside one are ignored, a span still open at the end closes there,
    and an empty span is dropped.
    """
    plain: list[str] = []
    spans: list[tuple[int, int]] = []
    opened: int | None = None
    for character in raw:
        if character == SNIPPET_OPEN:
            opened = len(plain) if opened is None else opened
        elif character == SNIPPET_CLOSE:
            if opened is not None and opened < len(plain):
                spans.append((opened, len(plain)))
            opened = None
        else:
            plain.append(character)
    if opened is not None and opened < len(plain):
        spans.append((opened, len(plain)))
    return "".join(plain), tuple(spans)
