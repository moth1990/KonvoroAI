"""A quote line's signature (11 §5.2 items 4–6): the family and the values the line writes, read by the same words
and grammar as a BOM row (`bom.terms`, 04 §5.1), in code.

- "מא"ז 3X16A" → circuit breaker, 3 poles, 16 A. "מא"ז N+16" → 1P+N, 16 A (the factory's way of writing it).
- A range: "מפסק משולב פחת עד 4X100A" → 4 poles, a current up to 100 A (`current_max_a`), not 100 A.
- "הגנת מנוע 4-6.3A" → a motor protection set 4–6.3 A.
- Included items: what follows "כולל", or a "+" between words ("מנתק נתיך גליל+נתיכים"), is kept as the line's
  included items with their families. Components that match one are "כלול", never missing (11 §5.3).
- A line no word names has no family: code can't say what it is, so it never matches (S15 decision 3).
"""

import re
from dataclasses import dataclass, field
from typing import Any

from konboro.pipeline.association.grammar import CONTEXT_KEYS, parse
from konboro.pipeline.association.schemas import Schemas
from konboro.pipeline.association.schemas import default as default_schemas
from konboro.pipeline.bom import terms
from konboro.pipeline.extraction import normalize

UNTYPED = terms.UNTYPED
ENCLOSURE = "enclosure"

_N_PLUS = re.compile(r"\bN\s*\+\s*(\d+(?:[.,]\d+)?)\s*A?\b", re.I)
_UP_TO = re.compile(r"(?:^|\s)(?:עד|up\s+to)\s+(?=\S*\d)", re.I)
_INCLUDES = re.compile(r"\s(?:כולל|כולל:|including|incl\.?)\s", re.I)
_PLUS = re.compile(r"(?<=[^\W\d_])\s*\+\s*(?=[^\W\d_])")  # a "+" between two words; "N+16" has a digit after it
_DIMS = re.compile(r"\b(\d{3,4})\s*[/×xX*]\s*(\d{3,4})\s*[/×xX*]\s*(\d{3,4})\b")
# The cabinet is no symbol of the library (stage 7 prices it from the data page, 07 §7.4), so it is not a BOM word;
# a quote names it as a line of its own.
_ENCLOSURE = re.compile(r"^\s*(?:ארון|מבנה\s+לוח|enclosure|cabinet)\b", re.I)
_RATIO = re.compile(r"\b(\d{2,5})\s*/\s*([15])\s*A?\b", re.I)


@dataclass(frozen=True)
class Included:
    text: str
    family: str
    cls: str


@dataclass
class Signature:
    family: str | None
    cls: str
    values: dict[str, Any] = field(default_factory=dict)
    current_max_a: float | None = None  # "עד 100A": a range, not a value (11 §5.2 item 5)
    dims_mm: tuple[int, ...] | None = None  # an enclosure's sides, sorted
    included: list[Included] = field(default_factory=list)
    main_text: str = ""

    @property
    def signed(self) -> bool:
        return self.family is not None

    def describe(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "class": self.cls,
            "values": self.values,
            "current_max_a": self.current_max_a,
            "dims_mm": list(self.dims_mm) if self.dims_mm else None,
            "included": [{"text": i.text, "family": i.family} for i in self.included],
        }


def _normalized(text: str) -> str:
    return normalize.normalize(
        normalize.Text(raw_text=text, bbox=(0, 0, 0, 0), rotation=0, confidence=1.0, source="bom")
    ).text


def split_included(text: str) -> tuple[str, list[str]]:
    """The line's own product, and the texts it says it includes."""
    m = _INCLUDES.search(f" {text} ")
    main, rest = (text[: max(m.start() - 1, 0)], text[m.end() - 1 :]) if m else (text, "")
    parts = _PLUS.split(main)
    return parts[0].strip(), [p.strip() for p in [*parts[1:], rest] if p.strip()]


def _included(texts: list[str]) -> list[Included]:
    out: list[Included] = []
    for t in texts:
        found = terms.families_in(t)
        for n, (family, cls, start) in enumerate(found):
            end = found[n + 1][2] if n + 1 < len(found) else None
            piece = terms.norm(t)[start:end].strip()
            out.append(Included(piece, family, cls))
    return out


def sign(text: str, model: str | None = None, schemas: Schemas | None = None) -> Signature:
    sch = schemas or default_schemas()
    main, included = split_included(text)
    found = terms.family_of(main) or (terms.family_of(model) if model else None)
    if found is None and _ENCLOSURE.match(main):
        found = (ENCLOSURE, ENCLOSURE)
    family, cls = found if found else (None, UNTYPED)
    sig = Signature(family=family, cls=cls, included=_included(included), main_text=main)
    if family is None:
        return sig
    body = _N_PLUS.sub(lambda m: f"1P+N {m[1]}A", main)
    up_to = _UP_TO.search(body)
    body = _normalized(body)
    names = set(sch.names(family))
    if family == ENCLOSURE:
        if d := _DIMS.search(body):
            sig.dims_mm = tuple(sorted(int(x) for x in d.groups()))
        return sig
    if family == "current_transformer" and (r := _RATIO.search(body)):
        sig.values["ratio_primary_a"], sig.values["ratio_secondary_a"] = int(r[1]), int(r[2])
    for reading in parse(body):
        if not reading.fits(family) or reading.key in CONTEXT_KEYS or reading.key in sig.values:
            continue
        if reading.key in names:
            sig.values[reading.key] = reading.value
    if up_to is not None and "current_a" in sig.values:
        sig.current_max_a = float(sig.values.pop("current_a"))
    return sig
