"""looks_garbled() detects PDFs whose text layer is broken.

The Dead Cells rulebook has a font with no valid ToUnicode CMap, so
`pdftotext` emits single-letter gibberish ("С О Я Р"). Search tools must
treat such excerpts as no-match so the agent escalates instead of looping
to MaxTurns. The detector must be conservative: never flag real prose
(Russian or English) or short snippets as garbled.
"""

from src.rules_lawyer_bot.utils.text_readability import (
    document_is_unreadable,
    looks_garbled,
)

# Verbatim from rules_pdfs/.cache/Dead Cells ... .pdf.txt (the artifact the
# agent actually saw — broken font extraction).
GARBLED = """С О     Я   Р




Р
    Р
                                    М Р   Р   РО О
    ОМ О
       Б ОМ


    иомов и   войной иом
                    РО О
                               МЯ
                                                          О    БОЯ
"""

GOOD_RU = (
    "Ход игрока состоит из трёх фаз. В фазе перемещения вы двигаете "
    "своего персонажа на количество клеток, равное значению скорости. "
    "Затем вы можете атаковать соседнего противника, после чего ход "
    "переходит к следующему игроку."
)

GOOD_EN = (
    "On your turn you may move up to your speed in spaces, then perform "
    "one action: attack an adjacent enemy, open a door, or rest. The "
    "turn then passes clockwise to the next player."
)


def test_broken_text_layer_is_garbled():
    assert looks_garbled(GARBLED) is True


def test_normal_russian_prose_is_not_garbled():
    assert looks_garbled(GOOD_RU) is False


def test_normal_english_prose_is_not_garbled():
    assert looks_garbled(GOOD_EN) is False


def test_short_snippet_is_not_flagged():
    """Too few tokens to judge — stay conservative, treat as readable
    (a small table or heading must not be discarded as 'broken')."""
    assert looks_garbled("Page 5") is False
    assert looks_garbled("HP 12 / ATK 3") is False


def test_empty_text_is_garbled():
    """No extractable content is, for search purposes, unusable."""
    assert looks_garbled("") is True
    assert looks_garbled("   \n  \f ") is True


# --- document-level guard -------------------------------------------------
# A low whole-document longword_ratio is necessary but NOT sufficient to
# condemn a rulebook: a genuinely "mixed" PDF extracts body prose correctly
# while decorative/heading fonts emit gibberish that sinks the ratio — yet
# the rules stay searchable. So the guard fires only when the ratio is low
# AND the tokens are, on average, too short to be words (mean token length
# < 4.0) — the scale-invariant signature of glyph-soup extraction. Real
# broken Dead Cells cache -> mean 2.80; genuine prose -> mean 7.2–8.0.


# Verbatim slice (segment 4) of the real Dead Cells pdftotext cache, with
# runs of layout whitespace collapsed (the detector splits on whitespace,
# so this is metrically identical to the raw bytes: 166 alpha tokens,
# longword_ratio 0.488, mean token length 3.18). Despite a few readable
# flavour fragments, the page is overwhelmingly shattered single-glyph
# tokens — the same profile as the full real cache (1580 tokens, ratio
# 0.375, mean 2.80) that returned no_match for every keyword in production.
# This is broken, NOT a usable mixed rulebook.
DEAD_CELLS_MIXED = """1 3

О О О РО
 1 6
 4
 2 2

3 ИИ Е Е Е

4

РА ЕНН
 Неспроста мне казалось, что это яблоко
 было каким-то подозрительно красным.

5 С НН 4 5
 Чувствуете запах подгоревшего тоста?
 +

А

СБРОС
 +
 1 2 3

А КО О
 6 Е ЕР АНН
 Моими же лошадьми… + III +

СБРОС
 :
 ВСЕ
 1 / : 2 / : 3 / : 4

А КО О
 THE
 С Е FLAYED
 АНН 1 2 3 4
 Всё это действует мне на нервы.
 + +
 : : III :+

СБРОС
 1 2 3

КО О
 : :
 1 2 3 4
 АК И А КАР А
 1 2 : 3 : 4
 :
 БОР Б О О О О 1

СЛЕ
 примеру ожж нн й на инает о ками оров поскол ку они на о тс слева от маркера ел но о
 свитка. о а он полу ит ел н й свиток маркер про винетс на ейку вправо и то а у ожж нно о
 станет о ка оров . сли маркер про винетс вправо е ра у е олово о останетс полу енн й
 ранее прирост оров а также по витс а ита от аморо ки. е а вайте ао но про ви ат маркер
 максимал но о оров и отме ат е о нов й уровен"""

# A genuinely broken layer (single-glyph soup) with a few stray readable
# English card words — the exact "scattered islands average out" failure
# mode the whole-document guard was built to catch. Must stay unreadable:
# nothing here can answer a rules question, so the agent must escalate
# instead of looping every keyword to MaxTurns.
BROKEN_WITH_ISLANDS = (GARBLED * 4) + " CONCIERGE PLAYERS FLIP THIS CARD"

# Faithful reproduction of the real Dead Cells .pdf.txt cache signature
# (the production incident): glyph-soup-dominated extraction with a thin
# remnant of recoverable prose. Real cache: 1580 tokens, ratio 0.375,
# mean 2.80. This fixture: 128 tokens, ratio 0.33, mean 2.80 — same
# profile, built from inline constants only (rules_pdfs/ is gitignored).
# The old _unique_real_words signal returned 306 on the real file and let
# it through; mean token length is scale-invariant and catches it.
REAL_BROKEN_CACHE_SIGNATURE = (GARBLED * 4) + " " + GOOD_RU

# Mixed rulebook: decorative-font heading gibberish + a genuinely readable
# body. The body keeps longword_ratio >= 0.55 (measured 0.69), so it must
# stay READABLE — the false positive the dual-signal structure prevents.
MIXED_READABLE_BODY = (GARBLED * 2) + (" " + GOOD_RU + " " + GOOD_EN) * 4


def test_whole_broken_document_is_unreadable():
    # ~50+ tokens of the real Dead Cells extraction, ratio well below 0.55.
    doc = GARBLED * 4
    assert document_is_unreadable(doc) is True


def test_dense_glyph_soup_page_is_unreadable():
    """A real pdftotext page that is ~half single-glyph tokens
    (longword_ratio 0.488, mean token length 3.18) cannot answer a rules
    question — every keyword search returned no_match in production. It
    must be flagged so the agent escalates instead of looping to
    MaxTurnsExceeded. The prior `is False` expectation reflected the
    size-scaling _unique_real_words bug behind that incident."""
    assert document_is_unreadable(DEAD_CELLS_MIXED) is True


def test_broken_document_with_readable_islands_stays_unreadable():
    """The guard's original purpose must survive the fix: a layer with no
    recoverable vocabulary is unreadable even when a handful of stray
    English words slip through."""
    assert document_is_unreadable(BROKEN_WITH_ISLANDS) is True


def test_real_broken_cache_signature_is_unreadable():
    """Regression for the production incident: a pdftotext cache that is
    overwhelmingly single-glyph soup with a thin prose remnant must be
    flagged so the agent escalates in one turn instead of looping to
    MaxTurnsExceeded."""
    assert document_is_unreadable(REAL_BROKEN_CACHE_SIGNATURE) is True


def test_mixed_rulebook_with_real_prose_body_stays_readable():
    """A rulebook whose body extracts correctly but whose decorative
    heading fonts emit gibberish must NOT be flagged: the readable body
    keeps longword_ratio >= 0.55."""
    assert document_is_unreadable(MIXED_READABLE_BODY) is False


def test_whole_normal_document_is_readable():
    doc = (GOOD_RU + " " + GOOD_EN) * 5  # plenty of real words
    assert document_is_unreadable(doc) is False


def test_small_document_not_flagged():
    """Too little text to judge — a tiny but valid leaflet must not be
    discarded as broken."""
    assert document_is_unreadable("Move 1 space. Attack. End turn.") is False


def test_empty_document_is_unreadable():
    assert document_is_unreadable("") is True
    assert document_is_unreadable("   \f \n ") is True
