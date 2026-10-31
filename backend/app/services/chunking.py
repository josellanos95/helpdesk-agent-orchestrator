"""Splitting an article into passages small enough to embed and to quote.

Greedy packing of paragraphs (then sentences, then words for pathological text) up to `max_chars`, with
the tail of the previous chunk repeated at the start of the next one so an answer that straddles a
boundary is still found whole. Every chunk is at most `max_chars` long, including the overlap.
"""

import re

DEFAULT_MAX_CHARS = 900
DEFAULT_OVERLAP = 120
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _hard_split(text: str, size: int) -> list[str]:
    """Last resort for a single 'word' or run of text longer than the budget."""
    pieces: list[str] = []
    current = ""
    for word in text.split():
        while len(word) > size:  # e.g. a long URL or base64 blob
            if current:
                pieces.append(current)
                current = ""
            pieces.append(word[:size])
            word = word[size:]
        if len(current) + len(word) + (1 if current else 0) > size:
            pieces.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        pieces.append(current)
    return pieces


def _units(body: str, size: int) -> list[str]:
    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n", body.replace("\r\n", "\n")):
        paragraph = " ".join(paragraph.split())  # collapse inner whitespace/newlines
        if not paragraph:
            continue
        if len(paragraph) <= size:
            units.append(paragraph)
            continue
        for sentence in _SENTENCE_END.split(paragraph):
            units.extend([sentence] if len(sentence) <= size else _hard_split(sentence, size))
    return units


def _tail(text: str, overlap: int) -> str:
    if overlap <= 0 or len(text) <= overlap:
        return ""
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1 :] if space != -1 else ""  # start on a word boundary


def chunk_text(body: str, *, max_chars: int = DEFAULT_MAX_CHARS, overlap: int = DEFAULT_OVERLAP) -> list[str]:
    if overlap >= max_chars // 2:
        raise ValueError("overlap must be well below max_chars")
    budget = max_chars - overlap  # a unit must fit next to the overlap it may be glued to
    chunks: list[str] = []
    current = ""
    for unit in _units(body, budget):
        joined = f"{current}\n\n{unit}" if current else unit
        if len(joined) <= max_chars:
            current = joined
            continue
        chunks.append(current)
        carry = _tail(current, overlap)
        current = f"{carry} {unit}".strip() if carry else unit
    if current:
        chunks.append(current)
    return chunks
