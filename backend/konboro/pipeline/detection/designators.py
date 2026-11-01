"""3.7 (03 §3.7): each symbol's designator, the device tag written next to it (F1, Q0, C3, HT2, SW1, R5, TH1, FNV).

Code links it, from stage 2's spans: a value has evidence only when it is written (00 §5.3). The model's reading of
the tag is a hint, never the value.

1. Candidates are spans shaped like a tag (letters then digits, or a short run of letters) within
   `designator_radius` symbol heights of the box (at least `designator_min_radius_pt`), the box's own text included.
2. A span with the tag the model read wins, also a little farther out (twice the radius); else the nearest.
3. Some words are not tags (03 §3.7 item 2): phases and buses (`L1`–`L3`, `N`, `PE`, `W0`) count only next to a
   symbol they can name (NEVIS-1's lamps are L1–L3); ratings never do (`C16` beside a breaker is its curve and
   current); a run of letters only when the model read it or it is written inside the symbol's box (`ABB`, `MCB`
   beside a breaker are not tags; `NVR` inside a relay's box is).
4. An auxiliary contact takes only the tag the model read beside it: the nearest tag is usually the breaker or
   contactor next to it, and its own device is the one the dashed line leads to (item 4, not read in v1).
5. On a drawing where most devices have a tag (`no_tag_share`), a billable device without one is flagged `no_tag`
   (03 §3.7 last line).

Ranges on a front view ("R1-R7", item 5) and the dashed link from an auxiliary contact to its breaker (item 4) are
not read in v1: front views are not `process` pages, and the dashed line needs the wire graph's line styles.
"""

import re

from konboro.contracts.extraction import TextSpan

from .candidates import Candidate, gap
from .config import DetectionConfig

_TAG = re.compile(r"^[A-Z]{1,4}\d{0,3}(?:[.\-][A-Z]{0,2}\d{1,3})*$")
_LETTERS = re.compile(r"^[A-Z]{1,4}$")
_RATING = re.compile(r"^[BCDKZ]\d{2,3}A?$")  # C16, B10: a breaker's curve and current
_PHASE = re.compile(r"^(?:L[1-3]|N|PE|W\d)$")
PHASE_OK = {"indicator_lamp": re.compile(r"^L[1-3]$"), "busbar": re.compile(r"^W\d$")}
BREAKERS = ("circuit_breaker", "rcd", "rcbo")


def _canon(text: str) -> str:
    return text.strip().upper().replace("–", "-")


def tag_shaped(span: TextSpan) -> bool:
    t = _canon(span.text)
    return bool(_TAG.match(t)) and len(t) <= 8


def acceptable(text: str, c: Candidate, model_read: bool, inside: bool = False) -> bool:
    """`inside`: the span lies in the symbol's own box (a coil labelled with its tag)."""
    t = _canon(text)
    if _PHASE.match(t):
        rule = PHASE_OK.get(c.family)
        return bool(rule and rule.match(t))
    if c.family in BREAKERS and _RATING.match(t) and not model_read:
        return False
    return model_read or inside or not _LETTERS.match(t)


def link(c: Candidate, spans: list[TextSpan], cfg: DetectionConfig) -> None:
    radius = max(cfg.designator_min_radius_pt, cfg.designator_radius * c.height)
    wanted = _canon(c.tag) if c.tag else None
    near = [(gap(c.bbox, s.bbox), s) for s in spans if tag_shaped(s)]
    if wanted:
        read = [(d, s) for d, s in near if d <= 2 * radius and _canon(s.text) == wanted]
        if read and acceptable(wanted, c, model_read=True):
            _, span = min(read, key=lambda it: it[0])
            c.designator, c.designator_span_id = _canon(span.text), span.span_id
            return
    if c.role == "aux_contact":
        return  # its device is the one it is mounted on: the dashed link (item 4), not the nearest tag
    pool = [(d, s) for d, s in near if d <= radius and acceptable(s.text, c, model_read=False, inside=d == 0)]
    if pool:
        _, span = min(pool, key=lambda it: it[0])
        c.designator, c.designator_span_id = _canon(span.text), span.span_id


def flag_untagged(found: list[Candidate], billable: dict[str, bool], cfg: DetectionConfig) -> None:
    devices = [c for c in found if c.role == "device" and billable.get(c.symbol_class, False)]
    if not devices:
        return
    tagged = sum(1 for c in devices if c.designator)
    if tagged / len(devices) >= cfg.no_tag_share:
        for c in devices:
            if not c.designator and "no_tag" not in c.flags:
                c.flags.append("no_tag")
