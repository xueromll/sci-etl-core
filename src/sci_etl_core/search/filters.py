from __future__ import annotations

import json
import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, time
from typing import Any

SNIPPET_OPEN = "\x02"
"""Marks where a highlighted span starts in a raw snippet; :func:`sanitize_text` keeps it out of stored text."""

SNIPPET_CLOSE = "\x03"
"""Marks where a highlighted span ends in a raw snippet; :func:`sanitize_text` keeps it out of stored text."""

SNIPPET_ELLIPSIS = "…"
"""Stands for the text a snippet leaves out before or after it."""

SNIPPET_TOKENS = 24
"""The most tokens a snippet holds."""

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


@dataclass(frozen=True, slots=True)
class RangeFilter:
    """Keep the records with a tag under ``key`` between ``low`` and ``high``, or with ``negated``, drop them.

    Both bounds are inclusive, and a bound left as ``None`` is open, so
    ``RangeFilter("year", low="2020")`` keeps 2020 and later. A record passes
    when any of its tags under ``key`` is in range, as a record passes a
    :class:`MetadataFilter` when any of its tags is among the values.

    The type of the bounds decides how tags compare:

    - **Integer bounds** compare tags numerically. Only a tag written as Python
      writes an integer, such as ``2024``, ``0``, or ``-3``, can be in range; a
      tag such as ``"2024-05-01"``, ``"07"``, or ``"+3"`` never is.
    - **Text bounds** compare tags as text, character by character. ``high`` is
      compared with as many leading characters of the tag as it has, so
      ``high="2024-06"`` keeps ``"2024-06-30T23:59:59Z"``. ISO 8601 dates and
      years of four digits order correctly this way.

    Raises:
        TypeError: A bound is neither an integer nor text, such as a ``bool`` or
            a ``float``, or one bound is an integer and the other text.
        ValueError: Both bounds are ``None``, a text bound is empty, an integer
            bound does not fit in 64 bits, or no tag could be in range because
            ``low`` is above ``high``.
    """

    key: str
    low: int | str | None = None
    high: int | str | None = None
    negated: bool = False

    def __post_init__(self) -> None:
        bounds = [bound for bound in (self.low, self.high) if bound is not None]
        if not bounds:
            raise ValueError(f"The range filter on {self.key!r} needs a low or a high bound")
        for bound in bounds:
            if isinstance(bound, bool) or not isinstance(bound, (int, str)):
                raise TypeError(f"Range bounds must be integers or text, not {type(bound).__name__}")
            if isinstance(bound, str) and not bound:
                raise ValueError(f"The range filter on {self.key!r} has an empty bound")
            if isinstance(bound, int) and not _INT64_MIN <= bound <= _INT64_MAX:
                raise ValueError(f"The range filter on {self.key!r} has a bound outside 64-bit integers")
        if len({type(bound) for bound in bounds}) > 1:
            raise TypeError(f"The bounds of the range filter on {self.key!r} must both be integers or both text")
        if self.low is not None and self.high is not None and not tag_in_range(str(self.low), self.low, self.high):
            raise ValueError(f"The range filter on {self.key!r} can never match, since its low bound is above its high")

    def contains(self, value: str) -> bool:
        """Report whether the tag ``value`` is in range, ignoring ``negated``."""
        return tag_in_range(value, self.low, self.high)


SearchFilter = MetadataFilter | RangeFilter
"""A filter a text search store accepts beside a query."""

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1
_CANONICAL_INTEGER = re.compile(r"0|-?[1-9][0-9]*")


def tag_in_range(value: str, low: int | str | None, high: int | str | None) -> bool:
    """Report whether the tag ``value`` lies between ``low`` and ``high``, as :class:`RangeFilter` defines it.

    The bounds are those of a valid :class:`RangeFilter`. The SQLite store
    registers this function with its connection, so both stores compare tags
    with the same code.
    """
    bound = low if low is not None else high
    if isinstance(bound, int):
        if not _CANONICAL_INTEGER.fullmatch(value):
            return False
        number = int(value)
        return (low is None or int(low) <= number) and (high is None or number <= int(high))
    return (low is None or str(low) <= value) and (high is None or value[: len(str(high))] <= str(high))


def validate_filters(filters: Iterable[SearchFilter], allowed_keys: Collection[str] | None = None) -> None:
    """Raise unless ``filters`` holds at most one filter per key, each on an allowed key.

    Several values of one key belong in a single filter's ``values``, whatever
    the filters' ``negated`` flags, and a :class:`MetadataFilter` and a
    :class:`RangeFilter` on one key are two filters too. ``allowed_keys`` is
    ``None`` when any key is allowed.

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


def matches_filters(metadata: Mapping[str, Any], filters: Iterable[SearchFilter]) -> bool:
    """Report whether a record with ``metadata`` passes every filter in ``filters``."""
    for search_filter in filters:
        tags = _tag_values(metadata.get(search_filter.key))
        if isinstance(search_filter, RangeFilter):
            tagged = any(search_filter.contains(tag) for tag in tags)
        else:
            tagged = not search_filter.values.isdisjoint(tags)
        if tagged is search_filter.negated:
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
