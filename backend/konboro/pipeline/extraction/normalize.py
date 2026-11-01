"""2.4 normalization (02 §2.4): units and spacing, tags, OCR fixes and merged spans, with the raw text always kept.

The dictionary of electrical tokens (02 §4.2) is the data in `TOKENS`: one pattern per kind of token, and the tags
each one gives. A tag says what is written, not what it belongs to: tying a value to a component is stage 4's job.

OCR fixes follow 02 §2.4's rules:
- a letter becomes a digit only when the result is a dictionary token and the letter is one a reader confuses with
  that digit (O/0, l/1, S/5, B/8);
- digits are never changed: `18A` stays `18A`, even though 16A is more common;
- each fix is listed in `corrections` and costs 10% of the span's confidence.
"""

import itertools
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from konboro.contracts.common import Bbox

from .geometry import Size, turn_box, turned_size

FIX_PENALTY = 0.9
MERGE_GAP_SHARE = 0.8  # neighbours on a line closer than this share of the text height may be merged
MAX_FIXES = 3  # letters tried as digits in one token

Tags = dict[str, Any]


def _num(s: str) -> int | float:
    v = float(s)
    return int(v) if v.is_integer() else v


@dataclass(frozen=True)
class Token:
    kind: str
    pattern: re.Pattern[str]
    tags: Callable[[re.Match[str]], Tags]
    fixable: bool = True  # an OCR fix may produce this kind (not designators: too many words look like one)


def _t(kind: str, pattern: str, tags: Callable[[re.Match[str]], Tags], fixable: bool = True) -> Token:
    return Token(kind, re.compile(pattern), tags, fixable)


# Matched against a token after `canonical` (units in their usual case, × for x between numbers).
TOKENS: tuple[Token, ...] = (
    _t("curve_current", r"^([BCDKZ])(\d{1,3})A?$", lambda m: {"curve": m[1], "current_a": _num(m[2])}),
    _t("poles_current", r"^([1-4])×(\d{1,4})A$", lambda m: {"poles": int(m[1]), "current_a": _num(m[2])}),
    _t("poles_by", r"^([1-4])×(\d{1,4})$", lambda m: {"poles": int(m[1])}),  # 02 §2.4: "3×16" → poles=3
    _t("current", r"^(\d{1,4}(?:\.\d)?)A$", lambda m: {"current_a": _num(m[1])}),
    _t("poles", r"^([1-4])P(?:\+N)?$", lambda m: {"poles": int(m[1])}),
    _t("breaking", r"^(\d{1,3}(?:\.\d)?)kA$", lambda m: {"breaking_capacity_ka": _num(m[1])}),
    _t("residual", r"^(\d{1,4})mA$", lambda m: {"residual_ma": _num(m[1])}),
    _t("cable", r"^(\d)×(\d{1,3}(?:\.\d)?)(?:\+\d{1,3}(?:\.\d)?)?(?:mm²)?$", lambda m: {"cable_cores": int(m[1])}),
    _t("cable_type", r"^(NYY|N2XY|NA2XY|XLPE|NYM|H07V-K|H07RN-F|FTP|UTP)$", lambda m: {"cable_type": m[1]}),
    _t("voltage", r"^(\d{2,4})V(?:AC|DC)?$", lambda m: {"voltage_v": _num(m[1])}),
    _t("power", r"^(\d{1,4}(?:\.\d{1,2})?)kW$", lambda m: {"power_kw": _num(m[1])}),
    _t("setting", r"^(INC?|IN|IR)=(\d{1,4})A$", lambda m: {"setting_a": _num(m[2])}),
    _t("designator", r"^[A-Z]{1,3}\d{1,3}(?:[.\-]\d{1,3})?$", lambda m: {}, fixable=False),
)

# A reader's confusions: letter → the digit it stands for, and the rule name in `corrections`.
CONFUSABLE = {
    "O": ("0", "O_to_0"),
    "o": ("0", "O_to_0"),
    "l": ("1", "l_to_1"),
    "S": ("5", "S_to_5"),
    "B": ("8", "B_to_8"),
}

_UNITS = [
    (re.compile(r"(?<=\d)\s*(?:a|א)$"), "A"),
    (re.compile(r"(?<=\d)\s*ka$", re.I), "kA"),
    (re.compile(r"(?<=\d)\s*ma$", re.I), "mA"),
    (re.compile(r"(?<=\d)\s*kw$", re.I), "kW"),
    (re.compile(r"(?<=\d)\s*v$", re.I), "V"),
    (re.compile(r"(?<=\d)\s*mm2$", re.I), "mm²"),
    (re.compile(r"(?<=\d)\s*(?:mm|ממ)²$", re.I), "mm²"),
]
_TIMES = re.compile(r"(?<=\d)\s*[xX×*]\s*(?=\d)")
_SPLIT = re.compile(r"\s+")
_SPACED_UNIT = re.compile(r"(?<=\d)\s+(?=(?:a|א|ka|ma|kw|v|mm²|mm2)(?:\s|$))", re.I)


def canonical(token: str) -> str:
    """One token with its unit in the usual case and × between numbers: `16 a` and `16א` are `16A`, `3x16` is
    `3×16`. The text is otherwise unchanged."""
    t = _TIMES.sub("×", token.strip())
    for pattern, unit in _UNITS:
        t = pattern.sub(unit, t)
    return t


def kind(token: str) -> Token | None:
    return next((k for k in TOKENS if k.pattern.match(token)), None)


def tags(text: str) -> Tags:
    found: Tags = {}
    for token in _SPLIT.split(text):
        k = kind(token)
        if k is not None:
            for key, value in k.tags(k.pattern.match(token)).items():  # type: ignore[arg-type]
                found.setdefault(key, value)
    return found


def looks_electrical(text: str) -> bool:
    """Worth a re-read when unsure (02 §2.3 step 3): a dictionary token, or one an OCR fix could make."""
    return any(kind(canonical(t)) is not None or _fix(canonical(t)) is not None for t in _SPLIT.split(text) if t)


def _fix(token: str) -> tuple[str, list[str]] | None:
    """The dictionary token this one becomes when some confusable letters are read as digits, if any."""
    if kind(token) is not None:
        return None
    spots = [i for i, ch in enumerate(token) if ch in CONFUSABLE][:MAX_FIXES]
    for n in range(1, len(spots) + 1):
        for chosen in itertools.combinations(spots, n):
            chars = list(token)
            for i in chosen:
                chars[i] = CONFUSABLE[token[i]][0]
            candidate = canonical("".join(chars))
            k = kind(candidate)
            if k is not None and k.fixable:
                return candidate, sorted({CONFUSABLE[token[i]][1] for i in chosen})
    return None


@dataclass
class Text:
    """A span on its way out: what normalization changes, and what it keeps."""

    raw_text: str
    bbox: Bbox
    rotation: int
    confidence: float
    source: str
    text: str = ""
    font_size_pt: float | None = None
    color: str | None = None
    corrections: list[dict[str, str]] = field(default_factory=list)
    merged_from: list[str] = field(default_factory=list)
    span_id: str = ""
    tags: Tags = field(default_factory=dict)


def normalize(t: Text) -> Text:
    """Units and spacing, then (OCR spans only) the fixes, then the tags."""
    out: list[str] = []
    joined = _SPACED_UNIT.sub("", _TIMES.sub("×", t.raw_text.strip()))  # "16 A" → "16A", "3 x 16" → "3×16"
    for token in _SPLIT.split(joined):
        c = canonical(token)
        if t.source == "ocr":
            fixed = _fix(c)
            if fixed is not None:
                c, rules = fixed
                t.corrections += [{"from": token, "to": c, "rule": r} for r in rules]
        out.append(c)
    t.text = " ".join(out)
    if t.corrections:
        t.confidence = round(t.confidence * FIX_PENALTY, 4)
    t.tags = tags(t.text)
    return t


def _joins(left: Text, right: Text) -> str | None:
    """How two neighbours on a line become one span (02 §2.4 "איחוד מקטעים"), or None: a number and its unit
    with no space ("16" "A"), two electrical tokens other than designators with one ("3P" "10kA")."""
    if re.fullmatch(r"\d+(?:\.\d+)?", left.text) and kind(canonical(left.text + right.text)) is not None:
        return ""
    a, b = kind(left.text.split()[-1]), kind(right.text.split()[0])
    if a is not None and b is not None and "designator" not in (a.kind, b.kind):
        return " "
    return None


def merge(spans: list[Text], size: Size) -> list[Text]:
    """Neighbours on one line that belong together become one span; `merged_from` keeps the parts' ids."""
    by_rotation: dict[int, list[Text]] = {}
    for s in spans:
        by_rotation.setdefault(s.rotation, []).append(s)
    out: list[Text] = []
    for rot, group in by_rotation.items():
        frame = turned_size(size, rot)
        flat = sorted(((turn_box(s.bbox, size, rot), s) for s in group), key=lambda it: (it[0][1], it[0][0]))
        used: set[int] = set()
        for i, (box, s) in enumerate(flat):
            if i in used:
                continue
            current, cbox = s, box
            while True:
                nxt = _neighbour(flat, used, i, cbox)
                if nxt is None:
                    break
                j, (nbox, n) = nxt
                glue = _joins(current, n)
                if glue is None:
                    break
                used.add(j)
                cbox = (cbox[0], min(cbox[1], nbox[1]), nbox[2], max(cbox[3], nbox[3]))
                current = _combine(current, n, glue, turn_box(cbox, frame, (360 - rot) % 360))
            out.append(current)
    return out


Placed = tuple[Bbox, Text]


def _neighbour(flat: list[Placed], used: set[int], me: int, box: Bbox) -> tuple[int, Placed] | None:
    """The nearest unused span to the right of `box` on its line, close enough to merge."""
    height = box[3] - box[1]
    best: tuple[int, Placed] | None = None
    for j, (b, s) in enumerate(flat):
        if j == me or j in used:
            continue
        overlap = min(box[3], b[3]) - max(box[1], b[1])
        gap = b[0] - box[2]
        close = overlap >= 0.5 * min(height, b[3] - b[1]) and -0.2 * height <= gap <= MERGE_GAP_SHARE * height
        if close and (best is None or b[0] < best[1][0][0]):
            best = (j, (b, s))
    return best


def _combine(a: Text, b: Text, glue: str, bbox: Bbox) -> Text:
    merged = Text(
        raw_text=a.raw_text + glue + b.raw_text,
        bbox=bbox,
        rotation=a.rotation,
        confidence=min(a.confidence, b.confidence),
        source=a.source,
        font_size_pt=a.font_size_pt,
        color=a.color or b.color,
        corrections=a.corrections + b.corrections,
        merged_from=(a.merged_from or [a.span_id]) + (b.merged_from or [b.span_id]),
    )
    merged.text = canonical(a.text + b.text) if glue == "" else a.text + glue + b.text
    merged.tags = tags(merged.text)
    return merged
