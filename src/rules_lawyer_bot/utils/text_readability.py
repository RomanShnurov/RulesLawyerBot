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
# Mean token length is the scale-invariant, extractor-independent
# signature of glyph-soup extraction: every word is shattered into 1–3
# char fragments. Unlike a unique-vocabulary count it does not grow with
# document size, and unlike longword_ratio it does not depend on which
# pdftotext built the cache. Measured on the real broken Dead Cells
# rulebook: mean 2.8 (poppler) / 3.65 (xpdf-4.00); genuine Russian or
# English prose averages >= 7. The 4.0 threshold sits well inside that
# gap. The token floor keeps a tiny but valid leaflet from being flagged.
#
# longword_ratio is deliberately NOT used here. It was once a veto
# (ratio >= 0.55 => readable) meant to spare "mixed" rulebooks whose body
# prose extracts correctly while decorative headings emit gibberish. But
# the ratio is an artefact of the extractor: xpdf-4.00 renders the same
# broken Dead Cells PDF as short alphanumeric card IDs ("B1-01", "ST-04")
# that are all >= 3 chars, lifting the ratio to 0.68–0.81 and silently
# passing the veto, while poppler yields 0.33 on the identical file. The
# veto therefore hid a wholly unreadable cache on a stock Windows
# toolchain — every keyword hit no_match and the agent looped to
# MaxTurnsExceeded (the production incident). Mean token length stays low
# (2.8–3.65) under both extractors, while a genuinely mixed-but-readable
# rulebook keeps a high mean from its real body words (measured 4.55), so
# the single signal is both sufficient and false-positive-safe — see
# test_mixed_rulebook_with_real_prose_body_stays_readable and
# test_real_xpdf_extraction_is_unreadable.
_DOC_MIN_TOKENS = 50
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
    Condemned on mean token length alone (the extractor-independent
    glyph-soup signature); see the _DOC_* rationale above for why
    longword_ratio is not used. Conservative: too little text to judge
    -> readable.
    """
    if not text or not text.strip():
        return True

    n, _ = _longword_ratio(text)
    if n < _DOC_MIN_TOKENS:
        return False
    return _mean_token_len(text) < _DOC_MIN_MEAN_TOKEN_LEN
