"""Detect PDF text extraction that is broken beyond use.

Some rulebooks embed fonts with no valid ToUnicode CMap, so
``pdftotext`` emits single-letter gibberish ("С О Я Р") instead of words.
Search tools must treat such text as a non-match: the agent should
escalate to the user rather than burn its whole turn budget re-searching
an unreadable document.

The detector is deliberately conservative — it must never flag real prose
(Russian or English) or short snippets (a heading, a stat line) as broken.
A false positive silently hides a usable rulebook; a false negative only
costs the behaviour we already have.
"""

from __future__ import annotations

# Real prose is overwhelmingly words of 3+ chars; broken extraction is
# mostly stray 1-2 char glyphs.
#
# Excerpt level: a single ugrep hit + 10 context lines. Mixed blocks
# (broken Russian + stray readable English from cards) need a strict
# threshold and a low token floor.
_EXCERPT_MIN_TOKENS = 8
_EXCERPT_MIN_LONGWORD_RATIO = 0.35

# Document level: the whole pdftotext cache.
#
# A low longword_ratio alone is NOT sufficient: "mixed" rulebooks extract
# their body prose correctly but render headings and card titles with
# decorative fonts that have no ToUnicode CMap, emitting single-glyph
# gibberish. That gibberish can drag the whole-document ratio under 0.55
# even though the rules text stays searchable — flagging it would be a
# false positive that hides a usable rulebook.
#
# So the document is condemned only when BOTH signals agree: the
# longword_ratio is low AND the tokens are, on average, too short to be
# words. Mean token length is the scale-invariant signature of glyph-soup
# extraction (every word shattered into 1–2 char fragments) and, unlike a
# unique-vocabulary count, does not grow with document size — a large
# broken cache still averages ~2–3 chars/token, while genuine Russian or
# English prose averages >= 7. The token floor avoids flagging a tiny but
# valid leaflet.
#
# Measured mean token length: real broken Dead Cells cache -> 2.80,
# genuine prose -> 7.2–8.0. The 4.0 threshold sits well inside that gap.
_DOC_MIN_TOKENS = 50
_DOC_MIN_LONGWORD_RATIO = 0.55
_DOC_MIN_MEAN_TOKEN_LEN = 4.0


def _mean_token_len(text: str) -> float:
    """Mean character length of letter-bearing whitespace tokens.

    Scale-invariant: broken glyph-soup extraction averages ~1.8–2.8
    chars/token; genuine Russian or English prose averages >= 7.2.
    Returns 0.0 when there are no letter tokens.
    """
    tokens = [t for t in text.split() if any(ch.isalpha() for ch in t)]
    if not tokens:
        return 0.0
    return sum(len(t) for t in tokens) / len(tokens)


def _longword_ratio(text: str) -> tuple[int, float]:
    """Return (letter_token_count, fraction of tokens with length >= 3)."""
    tokens = [t for t in text.split() if any(ch.isalpha() for ch in t)]
    if not tokens:
        return 0, 0.0
    long_words = sum(1 for t in tokens if len(t) >= 3)
    return len(tokens), long_words / len(tokens)


def looks_garbled(text: str) -> bool:
    """Return True if a single excerpt looks like a broken extraction.

    Empty/whitespace-only text counts as garbled — for search purposes it
    is unusable. Short snippets with few real tokens are treated as
    readable (not enough evidence to discard them).
    """
    if not text or not text.strip():
        return True

    n, ratio = _longword_ratio(text)
    if n < _EXCERPT_MIN_TOKENS:
        return False
    return ratio < _EXCERPT_MIN_LONGWORD_RATIO


def document_is_unreadable(text: str) -> bool:
    """Return True if a whole document's text layer is broken.

    Judged over the entire extraction, where scattered readable islands
    (English card text inside an otherwise broken Russian rulebook)
    average out — the failure mode that defeats per-excerpt detection.
    Conservative: too little text to judge -> readable.
    """
    if not text or not text.strip():
        return True

    n, ratio = _longword_ratio(text)
    if n < _DOC_MIN_TOKENS:
        return False
    if ratio >= _DOC_MIN_LONGWORD_RATIO:
        return False
    # Low ratio: only condemn if the tokens are also, on average, too
    # short to be words. A mixed-but-usable rulebook keeps a high mean
    # (its real body words) even when decorative gibberish sinks the ratio.
    return _mean_token_len(text) < _DOC_MIN_MEAN_TOKEN_LEN
