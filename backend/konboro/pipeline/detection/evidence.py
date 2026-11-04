"""What code knows about a symbol's class once the model has looked (03 §3.4–3.7, S24b). Code only: geometry and the
text stage 2 wrote. Each rule changes an unsure reading only; a sure one (≥ `accepted_from`, a known class) stands.
A class changed here keeps the line yellow at most: code's evidence is good, not a reading of the symbol.

1. **A device's end circles** (BUG-068). Some designers draw a breaker as a contact with a small circle at each end
   (25.26.100). A circle a third the device's size or less, touching its box on its wire (or a short way off it: the
   model's box may stop short of the ends), is part of the device, not a
   terminal or a current transformer of its own. A terminal at the line's end, beside the wire, or with a tag of its
   own (26-993's EM1) stays. Runs after
   the disambiguation call, so the call sees the page as before (its budget and cassettes do not move).
2. **A residual-current rating beside it** (BUG-068). "0.03A" or "30mA" written beside an unsure protective symbol (in
   line with it, within the designator radius) says it is an RCD: 25.26.100's "4×40A 0.03A A" RCDs were read as a
   switch-disconnector and an unknown. When a sure breaker is nearest, an unsure one about as near is meant.
3. **Peers** (BUG-070). Breakers hanging from one bus in a row, drawn the same (same width and top) with the same
   rating beside them, are one class: an unsure one takes the class of the surest one. A symbol under 60% of the
   other's height is not drawn the same: NURSERY-1's 1P+N breakers draw the N contact small beside the breaker.
   25.26.100's four 10A lighting breakers read as switch-disconnectors beside mcbs, and two 16A breakers read as
   push buttons.
4. **The designator's letter** (BUG-070, `prefixes.json`, the factory's own on top). Q is a switching device or an
   MCCB, F an MCB. Among the classes the model saw for an unsure symbol, the one the prefix allows wins; else the one
   class of its family the prefix allows ("Q" on a breaker: an MCCB). A prefix never brings in a family the model
   did not see.
"""

import re

from konboro.contracts.extraction import TextSpan
from konboro.pipeline.association.grammar import parse

from .candidates import Candidate, centre, gap
from .config import DetectionConfig
from .designators import COUNT, NOT_DEVICES, PROTECTIVE, tags
from .library import UNKNOWN, Library

SMALL = 0.35  # an end circle is at most this share of its device's size
TOUCH_PT = 6.0  # and this close to the device's box, or this share of its size (a box drawn short of its ends)
TOUCH_SHARE = 0.3
NEAR_SHARE = 1.25  # a residual rating nearest a sure breaker still names an unsure one about as near
ROW_PT = 3.0  # peers: their tops this close (hanging from one bus)
WIDTH_SHARE = 0.15  # and their widths this close (drawn the same)
HEIGHT_SHARE = 0.6  # and at least this share of the other's height: a 1P+N breaker's N contact is not a peer
PEER_SHARE = 0.9  # a peer's class at this share of the sure one's confidence
TEXT_FLOOR = 0.7  # a class from a residual rating, or from a prefix with the class seen by the model
CIRCLES = ("terminal", "current_transformer")
_LETTERS = re.compile(r"^([A-Z]{1,4})")


def _cap(cfg: DetectionConfig) -> float:
    return round(cfg.accepted_from - 0.01, 4)


def _sure(c: Candidate, cfg: DetectionConfig) -> bool:
    return c.confidence >= cfg.accepted_from and c.symbol_class != UNKNOWN


def _radius(c: Candidate, cfg: DetectionConfig) -> float:
    return max(cfg.designator_min_radius_pt, cfg.designator_radius * c.height)


def _adopt(c: Candidate, family: str, cls: str, floor: float) -> None:
    c.family, c.symbol_class = family, cls
    c.floor = max(c.floor or 0.0, floor)
    if all(x != cls for x, _ in c.candidates):
        c.candidates = [(cls, round(floor, 4)), *c.candidates]


def _on_wire(circle: Candidate, host: Candidate) -> bool:
    """At one of the host's ends, on the line through it (down the page for a symbol on a vertical line, 03 §6.2
    `orientation` 0), touching its box or a short way off it."""
    cx, cy = centre(circle.bbox)
    h = host.bbox
    if gap(circle.bbox, h) > max(TOUCH_PT, TOUCH_SHARE * host.height):
        return False
    if host.orientation % 180 == 0:
        half = (circle.bbox[2] - circle.bbox[0]) / 2
        return h[0] - half <= cx <= h[2] + half
    half = (circle.bbox[3] - circle.bbox[1]) / 2
    return h[1] - half <= cy <= h[3] + half


def absorb_end_circles(found: list[Candidate]) -> tuple[list[Candidate], int]:
    """Rule 1: the candidates without the circles that are a device's ends, and how many those were."""
    hosts = [c for c in found if c.family not in (*CIRCLES, *NOT_DEVICES) and c.role == "device"]
    kept: list[Candidate] = []
    absorbed = 0
    for c in found:
        own_tag = bool(c.tag) and not COUNT.match((c.tag or "").strip().upper())  # 26-993's EM1: its own terminal
        if c.family in CIRCLES and not own_tag and any(c.height <= SMALL * h.height and _on_wire(c, h) for h in hosts):
            absorbed += 1
            continue
        kept.append(c)
    return kept, absorbed


def _aligned(c: Candidate, s: TextSpan) -> bool:
    cx, cy = centre(s.bbox)
    return c.bbox[0] <= cx <= c.bbox[2] or c.bbox[1] <= cy <= c.bbox[3]


def residual_is_rcd(found: list[Candidate], spans: list[TextSpan], lib: Library, cfg: DetectionConfig) -> None:
    """Rule 2."""
    if "rcd" not in lib.classes:
        return
    for s in spans:
        if "residual_ma" not in s.tags and not any(r.key == "residual_ma" for r in parse(s.text)):
            continue
        near = [
            (gap(c.bbox, s.bbox), c)
            for c in found
            if c.role == "device"
            and (c.family in PROTECTIVE or c.symbol_class == UNKNOWN)
            and _aligned(c, s)
            and gap(c.bbox, s.bbox) <= _radius(c, cfg)
        ]
        if not near:
            continue
        g, c = min(near, key=lambda it: it[0])
        if _sure(c, cfg):  # the rating beside a block of labels may be nearest the device under it
            unsure = [(x, d) for x, d in near if not _sure(d, cfg) and x <= NEAR_SHARE * g]
            if not unsure:
                continue
            c = min(unsure, key=lambda it: it[0])[1]
        if c.family in ("rcd", "rcbo"):
            continue
        _adopt(c, "rcd", "rcd", min(_cap(cfg), max(c.confidence, TEXT_FLOOR)))


def _rating(c: Candidate, spans: list[TextSpan], cfg: DetectionConfig) -> float | None:
    near = [(gap(c.bbox, s.bbox), s) for s in spans if "current_a" in s.tags and gap(c.bbox, s.bbox) <= _radius(c, cfg)]
    if not near:
        return None
    value = min(near, key=lambda it: (it[0], it[1].span_id))[1].tags["current_a"]
    return float(value) if isinstance(value, int | float) else None


def peers(found: list[Candidate], spans: list[TextSpan], lib: Library, cfg: DetectionConfig) -> None:
    """Rule 3."""
    devices = [c for c in found if c.role == "device" and c.family not in ("terminal", *NOT_DEVICES)]
    rating = {id(c): _rating(c, spans, cfg) for c in devices}
    sure = [c for c in devices if _sure(c, cfg) and c.family in PROTECTIVE and rating[id(c)] is not None]
    for c in devices:
        if _sure(c, cfg) or rating[id(c)] is None:
            continue
        width = c.bbox[2] - c.bbox[0]
        like = [
            a
            for a in sure
            if abs(a.bbox[1] - c.bbox[1]) <= ROW_PT
            and abs((a.bbox[2] - a.bbox[0]) - width) <= WIDTH_SHARE * (a.bbox[2] - a.bbox[0])
            and _height_alike(a, c)
            and a.orientation == c.orientation
            and rating[id(a)] == rating[id(c)]
        ]
        if not like:
            continue
        best = max(like, key=lambda a: (a.confidence, -abs(a.bbox[0] - c.bbox[0])))
        if (best.family, best.symbol_class) != (c.family, c.symbol_class):
            _adopt(c, best.family, best.symbol_class, min(_cap(cfg), max(c.confidence, best.confidence * PEER_SHARE)))


def _height_alike(a: Candidate, b: Candidate) -> bool:
    ha, hb = a.bbox[3] - a.bbox[1], b.bbox[3] - b.bbox[1]
    return min(ha, hb) >= HEIGHT_SHARE * max(ha, hb)


def _allowed(designator: str | None, lib: Library) -> tuple[str, ...]:
    first = tags(designator)[0] if designator else ""
    m = _LETTERS.match(first)
    if not m:
        return ()
    letters = m[1]
    for n in range(len(letters), 0, -1):
        if letters[:n] in lib.prefixes:
            return lib.prefixes[letters[:n]]
    return ()


def weigh_by_prefix(c: Candidate, lib: Library, cfg: DetectionConfig) -> None:
    """Rule 4, after the designator is linked."""
    allowed = _allowed(c.designator, lib)
    if not allowed or c.symbol_class in allowed or _sure(c, cfg):
        return
    seen = [(score, -allowed.index(cls), cls) for cls, score in c.candidates if cls in allowed and cls in lib.classes]
    if seen:
        score, _, cls = max(seen)
        _adopt(c, lib.classes[cls].family, cls, min(_cap(cfg), max(score, TEXT_FLOOR)))
        return
    own = [cls for cls in allowed if cls in lib.classes and lib.classes[cls].family == c.family]
    if len(own) == 1:
        c.symbol_class = own[0]
