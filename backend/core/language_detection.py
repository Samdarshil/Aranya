"""
Language detection for the Voice pipeline — spec section 16
("automatic language detection... conversation language independent of
UI language").

Real and testable, unlike most of the Voice pipeline: this classifies
text by Unicode script range (Devanagari vs Latin), which needs no
network call and no ML model. It's necessarily coarse — it tells you
what SCRIPT the text is written in, not which of India's many languages
that maps to (Devanagari covers Hindi, Marathi, Nepali, and others; this
returns "hi" as a reasonable default for Devanagari text, not a promise
it's specifically Hindi). "Hinglish" — Latin-script Hindi, or a genuine
mix of Hindi and English words — is detected as CODE_MIXED when both
scripts appear together, which is common in real farmer speech-to-text
transcripts.

IMPORTANT LIMITATION, confirmed by testing: Hindi words spelled out in
Latin script ("FIELD-01 mein kya hua tha") are classified as ENGLISH,
because script detection cannot distinguish transliterated Hindi from
English — both use the Latin alphabet. This only correctly detects
Hindi/mixed content when Devanagari script is actually present. A real
STT provider transcribing spoken Hindi would normally output Devanagari
script, which is why this is adequate for its actual use case (classifying
a transcript, not raw romanized text a farmer might type) — but it's a
real gap if raw Latin-script farmer input needs Hindi detection too.
"""

from __future__ import annotations

from enum import Enum

# Devanagari Unicode block (covers Hindi, Marathi, Nepali, Sanskrit, etc.)
_DEVANAGARI_RANGE = (0x0900, 0x097F)


class DetectedLanguage(str, Enum):
    ENGLISH = "en"
    HINDI = "hi"           # Devanagari script — see module docstring caveat
    CODE_MIXED = "mixed"   # both scripts present (common "Hinglish" pattern)
    UNKNOWN = "unknown"    # no alphabetic content to classify (pure numbers/symbols)


def detect_language(text: str) -> DetectedLanguage:
    if not text or not text.strip():
        return DetectedLanguage.UNKNOWN

    has_devanagari = False
    has_latin = False
    for ch in text:
        code = ord(ch)
        if _DEVANAGARI_RANGE[0] <= code <= _DEVANAGARI_RANGE[1]:
            has_devanagari = True
        elif ch.isalpha() and ch.isascii():
            has_latin = True
        if has_devanagari and has_latin:
            return DetectedLanguage.CODE_MIXED

    if has_devanagari:
        return DetectedLanguage.HINDI
    if has_latin:
        return DetectedLanguage.ENGLISH
    return DetectedLanguage.UNKNOWN
