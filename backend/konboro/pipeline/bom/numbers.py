"""Numbers as an estimator says them, in Hebrew words, for the chat builder's check (13 §4.2, S27 design 3).

Transcribe has no Hebrew custom language model, so "שלוש על שש עשרה" comes out in words; the `chat_bom_extraction`
model writes it "3X16A", and code checks that every number it wrote was said. This reads the words back as numbers:
units and teens in both genders, their construct forms ("שלושת"), "חד", "דו" and "תלת" ("חד פאזי" is 1P), tens,
hundreds and thousands, joined by "ו"
("שישים ושלוש" = 63), with a one-letter prefix ("ל", "ב", "ה", "מ", "ו", "ש") on the first word. Digits count too.

A phrase stops at a word that is not a number word, or at one that can't follow what came before ("שלוש שש" is two
numbers, 3 and 6). The reading is for checking only: values in the quote come from the spelling grammar (04 §5.1).
"""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_UNITS = {
    "אחד": 1,
    "אחת": 1,
    "שניים": 2,
    "שנים": 2,
    "שתיים": 2,
    "שתים": 2,
    "שני": 2,
    "שתי": 2,
    "שלושה": 3,
    "שלשה": 3,
    "שלוש": 3,
    "שלש": 3,
    "שלושת": 3,
    "ארבעה": 4,
    "ארבע": 4,
    "ארבעת": 4,
    "חמישה": 5,
    "חמשה": 5,
    "חמש": 5,
    "חמשת": 5,
    "שישה": 6,
    "ששה": 6,
    "שש": 6,
    "ששת": 6,
    "שבעה": 7,
    "שבע": 7,
    "שבעת": 7,
    "שמונה": 8,
    "שמונת": 8,
    "תשעה": 9,
    "תשע": 9,
    "תשעת": 9,
    # a phase or pole count as a panel builder says it: "חד פאזי" (1P), "דו קוטבי" (2P), "תלת פאזי" (3P)
    "חד": 1,
    "דו": 2,
    "תלת": 3,
}
_TEN = {"עשר": 10, "עשרה": 10, "עשרת": 10}
_TENS = {
    "עשרים": 20,
    "שלושים": 30,
    "שלשים": 30,
    "ארבעים": 40,
    "חמישים": 50,
    "חמשים": 50,
    "שישים": 60,
    "ששים": 60,
    "שבעים": 70,
    "שמונים": 80,
    "תשעים": 90,
}
_HUNDREDS = {"מאה": 100, "מאתיים": 200, "מאתים": 200}
_HUNDREDS_OF = {"מאות"}  # "שלוש מאות"
_THOUSANDS = {"אלף": 1000, "אלפיים": 2000}
_THOUSANDS_OF = {"אלפים"}  # "שלושת אלפים"
_WORDS = set(_UNITS) | set(_TEN) | set(_TENS) | set(_HUNDREDS) | _HUNDREDS_OF | set(_THOUSANDS) | _THOUSANDS_OF
_PREFIXES = "ולבהמש"

_TOKEN = re.compile(r"\d+(?:[.,]\d+)?|[^\W\d_]+", re.UNICODE)
DIGITS = re.compile(r"\d+(?:[.,]\d+)?")


def _bare(word: str, first: bool) -> str | None:
    """The number word inside `word`: itself, or after "ו" on any word of a phrase ("שישים ושלוש"), or after one or
    two prefix letters on its first word ("לשש", "ובשש")."""
    if word in _WORDS:
        return word
    if not first:
        return word[1:] if len(word) > 2 and word[0] == "ו" and word[1:] in _WORDS else None
    for cut in (1, 2):
        rest = word[cut:]
        if len(rest) >= 2 and all(c in _PREFIXES for c in word[:cut]) and rest in _WORDS:
            return rest
    return None


@dataclass(frozen=True)
class Found:
    value: int
    start: int  # where it starts in the text
    end: int


def _place(value: int) -> int:
    """The order of a part: thousands 4, hundreds 3, tens 2, a unit or a teen 1."""
    if value >= 1000:
        return 4
    if value >= 100:
        return 3
    if value >= 20:
        return 2
    return 1


def spoken(text: str) -> list[Found]:
    """Every number written in words in `text`, left to right."""
    tokens = [(m.group(), m.start(), m.end()) for m in _TOKEN.finditer(text)]
    out: list[Found] = []
    i = 0
    while i < len(tokens):
        word, start, _ = tokens[i]
        bare = _bare(word, first=True)
        if bare is None:
            i += 1
            continue
        total = 0
        last_place = 5
        end = start
        j = i
        first = True
        while j < len(tokens):
            w = _bare(tokens[j][0], first)
            if w is None:
                break
            nxt = _bare(tokens[j + 1][0], False) if j + 1 < len(tokens) else None
            used = 1
            if w in _UNITS and nxt in _TEN and last_place != 2:
                part = _UNITS[w] + 10  # "שש עשרה", "שנים עשר"; after tens it isn't: "שלושים ושתיים עשרה" is 32, 10
                used = 2
            elif w in _UNITS and nxt in _HUNDREDS_OF:
                part = _UNITS[w] * 100
                used = 2
            elif w in _UNITS and nxt in _THOUSANDS_OF:
                part = _UNITS[w] * 1000
                used = 2
            elif w in _UNITS:
                part = _UNITS[w]
            elif w in _TEN:
                part = 10
            elif w in _TENS:
                part = _TENS[w]
            elif w in _HUNDREDS:
                part = _HUNDREDS[w]
            elif w in _THOUSANDS:
                part = _THOUSANDS[w]
            else:  # "מאות" with no unit before it
                break
            place = _place(part)
            if place >= last_place:
                break  # "שלוש שש": a new number
            total += part
            last_place = place
            end = tokens[j + used - 1][2]
            j += used
            first = False
        if j == i:
            i += 1
            continue
        out.append(Found(total, start, end))
        i = j
    return out


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", ".")).normalize()
    except InvalidOperation:
        return None


def numbers(text: str) -> set[Decimal]:
    """Every number in `text`: written in digits ("16", "0,03") or in words ("שש עשרה")."""
    out = {d for x in DIGITS.findall(text) if (d := _decimal(x)) is not None}
    out |= {Decimal(f.value).normalize() for f in spoken(text)}
    return out


def in_digits(text: str) -> str:
    """`text` with its spoken numbers in digits ("שנים עשר מא"ז" → "12 מא"ז"), for the stand-in model."""
    parts: list[str] = []
    at = 0
    for f in spoken(text):
        parts.append(text[at : f.start])
        parts.append(str(f.value))
        at = f.end
    parts.append(text[at:])
    return "".join(parts)
