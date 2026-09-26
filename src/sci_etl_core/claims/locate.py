from __future__ import annotations

import re
from bisect import bisect_right
from difflib import SequenceMatcher

_ABBREVIATIONS = frozenset(
    {
        "al",
        "app",
        "approx",
        "ca",
        "cf",
        "ch",
        "eq",
        "eqs",
        "fig",
        "figs",
        "no",
        "nos",
        "pp",
        "ref",
        "refs",
        "resp",
        "sec",
        "sect",
        "sects",
        "tab",
        "tabs",
        "viz",
        "vol",
        "vs",
    }
)
_INITIALISM = re.compile(r"^(?:[A-Za-z]\.)+[A-Za-z]$")
_CANDIDATE = re.compile(r"[.!?]+[\"')\]]*(?=\s)")
_PARAGRAPH = re.compile(r"\n[ \t]*\n\s*")
_LONGEST_TOKEN = 40
_MIN_BLOCK = 3
_WHITESPACE = re.compile(r"\s+")


def sentence_bounds(text: str) -> list[tuple[int, int]]:
    """Split ``text`` into sentences tuned for scientific prose, as half-open ``(start, end)`` offsets.

    A sentence ends at ``.``, ``!``, or ``?`` followed by whitespace and a
    character that is not a lowercase letter, and at every blank line. A
    period does not end a sentence after a common abbreviation such as
    ``et al.``, ``Fig.``, ``Eq.``, ``Ref.``, or ``cf.``, after an initialism
    such as ``R.A.``, ``e.g.``, or ``i.e.``, or inside a number such as
    ``0.5``. Offsets exclude the whitespace between sentences.
    """
    bounds: list[tuple[int, int]] = []
    paragraph_start = 0
    for paragraph in [*_PARAGRAPH.finditer(text), None]:
        paragraph_end = len(text) if paragraph is None else paragraph.start()
        bounds.extend(_paragraph_sentences(text, paragraph_start, paragraph_end))
        if paragraph is not None:
            paragraph_start = paragraph.end()
    return bounds


def _paragraph_sentences(text: str, start: int, end: int) -> list[tuple[int, int]]:
    sentences: list[tuple[int, int]] = []
    sentence_start = _skip_space(text, start, end)
    for match in _CANDIDATE.finditer(text, sentence_start, end):
        following = _skip_space(text, match.end(), end)
        if following >= end:
            break
        if not _ends_sentence(text, match.start(), text[following]):
            continue
        sentences.append((sentence_start, match.end()))
        sentence_start = following
    closing = _trim_space(text, sentence_start, end)
    if closing > sentence_start:
        sentences.append((sentence_start, closing))
    return sentences


def _ends_sentence(text: str, punctuation: int, following: str) -> bool:
    if following.islower():
        return False
    if text[punctuation] != ".":
        return True
    begin = punctuation
    while begin > 0 and not text[begin - 1].isspace() and punctuation - begin < _LONGEST_TOKEN:
        begin -= 1
    token = text[begin:punctuation].lstrip("([\"'")
    return token.lower() not in _ABBREVIATIONS and _INITIALISM.match(token) is None


def _skip_space(text: str, position: int, end: int) -> int:
    while position < end and text[position].isspace():
        position += 1
    return position


def _trim_space(text: str, start: int, end: int) -> int:
    while end > start and text[end - 1].isspace():
        end -= 1
    return end


def locate_quote(text: str, quote: str, *, min_ratio: float = 0.9) -> tuple[int, int, float] | None:
    """Return the sentence-snapped offsets of ``quote`` in ``text`` and how closely it matched.

    Matching is exact after collapsing whitespace first, which gives a ratio
    of ``1.0``. Otherwise each sentence, and each pair of adjacent sentences,
    is aligned with the quote through :mod:`difflib`, counting runs of three
    or more matching characters. The ratio compares the matched characters
    with the length of the quote and of the stretch of text they span, so a
    quote scattered over a long candidate scores low. The best candidate at
    ``min_ratio`` or above wins, and of equal candidates the shortest. The
    offsets cover whole sentences, so two models that quote different parts
    of one sentence get the same span. ``None`` means the quote is not in the
    text, so the claim is ungrounded.

    Raises:
        ValueError: ``min_ratio`` is not between 0 and 1.
    """
    if not 0.0 <= min_ratio <= 1.0:
        raise ValueError("min_ratio must be between 0 and 1")
    target = _WHITESPACE.sub(" ", quote).strip()
    if not target:
        return None
    bounds = sentence_bounds(text)
    if not bounds:
        return None
    normalized, positions = _normalized(text)
    found = normalized.find(target)
    if found >= 0:
        start, end = positions[found], positions[found + len(target) - 1] + 1
        return (*_snap(bounds, start, end), 1.0)
    best: tuple[float, int, int] | None = None
    for index, (start, _end) in enumerate(bounds):
        for last in range(index, min(index + 2, len(bounds))):
            candidate_end = bounds[last][1]
            ratio = _alignment(target, _WHITESPACE.sub(" ", text[start:candidate_end]))
            if best is None or (ratio, start - candidate_end) > (best[0], best[1] - best[2]):
                best = (ratio, start, candidate_end)
    if best is None or best[0] < min_ratio:
        return None
    return best[1], best[2], best[0]


def _normalized(text: str) -> tuple[str, list[int]]:
    characters: list[str] = []
    positions: list[int] = []
    previous_space = True
    for position, character in enumerate(text):
        if character.isspace():
            if previous_space:
                continue
            characters.append(" ")
            previous_space = True
        else:
            characters.append(character)
            previous_space = False
        positions.append(position)
    return "".join(characters), positions


def _snap(bounds: list[tuple[int, int]], start: int, end: int) -> tuple[int, int]:
    starts = [bound[0] for bound in bounds]
    first = max(bisect_right(starts, start) - 1, 0)
    last = max(bisect_right(starts, end - 1) - 1, first)
    return bounds[first][0], max(bounds[last][1], end)


def _alignment(target: str, candidate: str) -> float:
    blocks = [
        block
        for block in SequenceMatcher(None, target, candidate, autojunk=False).get_matching_blocks()
        if block.size >= _MIN_BLOCK
    ]
    if not blocks:
        return 0.0
    matched = sum(block.size for block in blocks)
    region = blocks[-1].b + blocks[-1].size - blocks[0].b
    return 2 * matched / (len(target) + region)
