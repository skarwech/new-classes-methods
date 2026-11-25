"""Accent-, case- and punctuation-insensitive text folding for search."""

from __future__ import annotations

import unicodedata

# Letters that Unicode normalization does not decompose into a base letter.
_LETTER_MAP = str.maketrans(
    {
        "ø": "o",
        "Ø": "O",
        "ł": "l",
        "Ł": "L",
        "đ": "d",
        "Đ": "D",
        "ð": "d",
        "Ð": "D",
        "þ": "th",
        "Þ": "Th",
        "ı": "i",
        "æ": "ae",
        "Æ": "AE",
        "œ": "oe",
        "Œ": "OE",
        "ß": "ss",
    }
)

# Typographic dashes and quotes, mapped to their plain keyboard equivalents.
_PUNCTUATION_MAP = str.maketrans(
    {
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "−": "-",
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
    }
)

# Separators between words: a query and the text are compared word by word, so
# "open-set", "open set" and "Open, Set" all mean the same. Apostrophes and dots stay
# inside words.
_SEPARATOR_MAP = str.maketrans(dict.fromkeys('-_,;:()[]{}/\\|<>"', " "))


def fold(text: str) -> str:
    """Return ``text`` lower-cased, accent-free, with separators as single spaces.

    >>> fold("Halász – Łukasz (2023)")
    'halasz lukasz 2023'
    """
    if not isinstance(text, str):
        raise TypeError(f"fold() needs text, got {type(text).__name__}")
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    plain = (
        without_marks.translate(_LETTER_MAP)
        .translate(_PUNCTUATION_MAP)
        .translate(_SEPARATOR_MAP)
    )
    return " ".join(plain.casefold().split())
