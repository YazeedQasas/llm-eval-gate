"""Text normalization shared by scorers and guards. Pure functions, no state."""

from __future__ import annotations

import re
import unicodedata

# Harakat, tanween, shadda, sukun, superscript alef, Quranic marks.
_AR_DIACRITICS = re.compile("[ً-ٰٟۖ-ۭ]")
_TATWEEL = "ـ"
_AR_LETTERS = str.maketrans(
    {
        "أ": "ا",  # أ -> ا
        "إ": "ا",  # إ -> ا
        "آ": "ا",  # آ -> ا
        "ٱ": "ا",  # ٱ -> ا
        "ى": "ي",  # ى -> ي
        "ة": "ه",  # ة -> ه
    }
)
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_WS = re.compile(r"\s+")


def normalize_arabic(text: str) -> str:
    """Strip diacritics and tatweel; unify alef, alef maqsura/ya and ta marbuta/ha."""
    text = _AR_DIACRITICS.sub("", text).replace(_TATWEEL, "")
    return text.translate(_AR_LETTERS)


def strip_punctuation(text: str) -> str:
    """Replace every Unicode punctuation character (incl. Arabic ، ؛ ؟) with a space."""
    return "".join(" " if unicodedata.category(ch).startswith("P") else ch for ch in text)


def collapse_whitespace(text: str) -> str:
    return _WS.sub(" ", text).strip()


def normalize_text(
    text: str,
    *,
    arabic: bool = True,
    casefold: bool = True,
    punctuation: bool = True,
    digits: bool = True,
) -> str:
    """The standard normalization: NFKC, Arabic folding, digits, case, punctuation, spaces."""
    text = unicodedata.normalize("NFKC", text)
    if arabic:
        text = normalize_arabic(text)
    if digits:
        text = text.translate(_DIGITS)
    if casefold:
        text = text.casefold()
    if punctuation:
        text = strip_punctuation(text)
    return collapse_whitespace(text)


def word_ngrams(text: str, n: int) -> set[tuple[str, ...]]:
    """Word n-grams of already-normalized text. Short texts give their single full tuple."""
    words = text.split()
    if not words:
        return set()
    if len(words) < n:
        return {tuple(words)}
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def containment(needle: str, haystack: str, n: int) -> float:
    """Share of `needle`'s word n-grams that also occur in `haystack` (both normalized)."""
    a = word_ngrams(needle, n)
    if not a:
        return 0.0
    return len(a & word_ngrams(haystack, n)) / len(a)
