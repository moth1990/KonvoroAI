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
   3b. **A rated push button** (the user's exception to S24b decision 2, after a live run of 25.26.100): a symbol
   read as a push button, however sure, with a current rating beside it and drawn like the breakers in its row
   (whatever their confidence) with the same rating, is a breaker, and yellow: the model was sure of two 16A
   socket breakers as push buttons ("לחצן" × 12, one with "X11"), in a row with no sure breaker for rule 3.
   3c. **A row with no sure symbol votes** (BUG-088, BUG-090): drawn alike, rated alike, it is the family most of it
   was read as (more than half), and that family's most-read class; another family's symbol joins only when the
   model saw that class for it. 3b also takes an unsure contactor rated like the breakers in its row, and a row may
   line up by its symbols' middles as well as their tops (BUG-087: a box drawn taller than its peers).
   2b. **A curve on the rating** ("1×10AC", "C16") beside a disconnector or an unknown protective symbol, nearest it,
   says an MCB: a written reading, like "MCB" (BUG-091).
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
from .library import UNKNOWN, Library, prefix_classes

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


def _beside(c: Candidate, s: TextSpan) -> bool:
    """Written beside the symbol: across its line, level with it (a label to the side, not above or below)."""
    cx, cy = centre(s.bbox)
    return c.bbox[1] <= cy <= c.bbox[3] if c.orientation % 180 == 0 else c.bbox[0] <= cx <= c.bbox[2]


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
        devices = [
            (gap(c.bbox, s.bbox), c)
            for c in found
            if c.role == "device"
            and (c.family in PROTECTIVE or c.symbol_class == UNKNOWN)
            and gap(c.bbox, s.bbox) <= _radius(c, cfg)
        ]
        if not devices or min(devices, key=lambda it: it[0])[1].family in ("rcd", "rcbo"):
            continue  # the rating of the RCD nearest it (6199-2-50's "מ.פ." box)
        near = [(not _beside(c, s), g, c) for g, c in devices if _aligned(c, s)]
        if not near:
            continue
        _, g, c = min(near, key=lambda it: (it[0], it[1]))  # the one it is written beside, before one under it
        if _sure(c, cfg):  # the rating beside a block of labels may be nearest the device under it
            unsure = [(x, d) for _, x, d in near if not _sure(d, cfg) and x <= NEAR_SHARE * g]
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


BUTTONS = ("push_button",)  # rule 3b: a current rating beside one says it is not what it was read as, however sure
UNSURE_RATED = ("contactor",)  # rule 3b too, when unsure (BUG-087: 25.26.100's x2 10A breakers)
AMPS_WRITTEN = re.compile(r"\d\s*A", re.IGNORECASE)  # "10AC", "16 A": a current with its unit, not a tag's digits
CURVED = ("switch_disconnector",)  # rule 2b: a curve on its rating says a breaker (and an unknown protective one)
ROW_MIN = 3  # rule 3c: a row votes from this many symbols


def _alike(a: Candidate, c: Candidate, rating: dict[int, float | None], centred: bool = False) -> bool:
    """Drawn the same in one row: tops level (or, `centred`, their middles: a box drawn taller than its peers, BUG-087),
    widths and heights alike, the same way, the same rating."""
    width = c.bbox[2] - c.bbox[0]
    level = abs(a.bbox[1] - c.bbox[1]) <= ROW_PT or (
        centred and abs((a.bbox[1] + a.bbox[3]) / 2 - (c.bbox[1] + c.bbox[3]) / 2) <= ROW_PT
    )
    return (
        level
        and abs((a.bbox[2] - a.bbox[0]) - width) <= WIDTH_SHARE * (a.bbox[2] - a.bbox[0])
        and _height_alike(a, c)
        and a.orientation == c.orientation
        and rating[id(a)] == rating[id(c)]
    )


def _vote(a: Candidate, family: str, lib: Library) -> str | None:
    """What one symbol says its class in `family` is: its own, else the likeliest the model saw for it."""
    if a.family == family and a.symbol_class != UNKNOWN:
        return a.symbol_class
    seen = [(s, k) for k, s in a.candidates if k in lib.classes and lib.classes[k].family == family]
    return max(seen, key=lambda it: (it[0], -_rank(k := it[1], family, lib), k))[1] if seen else None


def _rank(cls: str, family: str, lib: Library) -> int:
    order = [k.symbol_class for k in lib.families.get(family, [])]
    return order.index(cls) if cls in order else len(order)


def _class_of(family: str, like: list[Candidate], lib: Library) -> str | None:
    """The class a row of `family` reads most; a tie goes to the family's first class (an MCB). None: no reading."""
    votes: dict[str, int] = {}
    for a in like:
        if (v := _vote(a, family, lib)) is not None:
            votes[v] = votes.get(v, 0) + 1
    if not votes:
        return None
    return max(votes, key=lambda k: (votes[k], -_rank(k, family, lib)))


def curve_is_a_breaker(found: list[Candidate], spans: list[TextSpan], cfg: DetectionConfig) -> None:
    """Rule 2b (BUG-091): a curve written on a rating ("1×10AC", "C16") is a breaker's, like "MCB" written beside it:
    the disconnector (or an unknown protective symbol) it is written beside, nearest it, is an MCB. So is an unsure
    contactor, drawn as a device or as its power contacts (25.26.100's "1×10AC" read as a contactor at 0.504): a
    contactor's rating carries no curve. For a contactor the amps must be written with their unit: its own tag "C1"
    reads as curve C, 1A too (6199-2-50's contactors C1 and C2). A written reading beats the model's class; the line
    stays yellow."""
    for s in spans:
        readings = parse(s.text)
        if not any(r.key == "curve" for r in readings) or not any(r.key == "current_a" for r in readings):
            continue
        amps = bool(AMPS_WRITTEN.search(s.text))
        near = [
            (gap(c.bbox, s.bbox), c)
            for c in found
            if (c.role == "device" or (amps and _curved_contactor(c, cfg)))
            and (c.family in (*PROTECTIVE, *CURVED, *UNSURE_RATED) or c.symbol_class == UNKNOWN)
            and gap(c.bbox, s.bbox) <= _radius(c, cfg)
            and _aligned(c, s)
        ]
        if not near:
            continue
        _, c = min(near, key=lambda it: (it[0], it[1].bbox))
        curved = c.family in CURVED or (c.family in PROTECTIVE and c.symbol_class == UNKNOWN)
        if curved or (amps and _curved_contactor(c, cfg)):
            _adopt(c, "circuit_breaker", "mcb", min(_cap(cfg), max(c.confidence, TEXT_FLOOR)))
            c.ceiling = _cap(cfg)
            c.role = "device"


def _curved_contactor(c: Candidate, cfg: DetectionConfig) -> bool:
    return c.family in UNSURE_RATED and c.role in ("device", "power_contact") and not _sure(c, cfg)


def _rated_buttons(
    devices: list[Candidate],
    contacts: list[Candidate],
    rating: dict[int, float | None],
    lib: Library,
    cfg: DetectionConfig,
) -> None:
    """Rule 3b. `contacts`: unsure contactors' power contacts, how the first look draws a contactor (BUG-087)."""
    for c in [*devices, *contacts]:
        rated = c.family in BUTTONS or (c.family in UNSURE_RATED and not _sure(c, cfg))
        if not rated or rating[id(c)] is None:
            continue
        like = [a for a in devices if a is not c and a.family in PROTECTIVE and _alike(a, c, rating, centred=True)]
        if not like:
            continue
        family = max({a.family for a in like}, key=lambda f: (sum(a.family == f for a in like), f))
        first = [k.symbol_class for k in lib.families.get(family, [])]
        _adopt(c, family, _class_of(family, like, lib) or (first[0] if first else UNKNOWN), TEXT_FLOOR)
        c.ceiling = _cap(cfg)  # a reading overturned by code is yellow at most
        c.role = "device"


def _row_vote(devices: list[Candidate], rating: dict[int, float | None], lib: Library, cfg: DetectionConfig) -> None:
    """Rule 3c (BUG-088, BUG-090): a row of symbols drawn alike, rated alike, with no sure one for rule 3, is one
    device type: the family most of it was read as, when that is more than half the row and protective, and that
    family's class the row reads most. A symbol of another family joins only when the model saw that class for it too
    (25.26.100's four 10A "disconnectors", `mcb` 0.7 among their own candidates); one of the family takes its class
    (the 40A row read mcb × 3 and mccb × 2, drawn alike). Its confidence stays its own."""
    done: set[int] = set()
    for c in devices:
        if id(c) in done or rating[id(c)] is None or _sure(c, cfg):
            continue
        row = [a for a in devices if a is c or (rating[id(a)] is not None and _alike(a, c, rating, centred=True))]
        if len(row) < ROW_MIN or any(_sure(a, cfg) and a.family in PROTECTIVE for a in row):
            continue
        done.update(id(a) for a in row)
        family = max({a.family for a in row}, key=lambda f: (sum(a.family == f for a in row), f))
        if family not in PROTECTIVE or 2 * sum(a.family == family for a in row) <= len(row):
            continue
        cls = _class_of(family, [a for a in row if a.family == family], lib)
        if cls is None:
            continue
        for a in row:
            if (a.family == family and a.symbol_class == cls) or _sure(a, cfg):
                continue
            if a.family != family and all(k != cls for k, _ in a.candidates):
                continue
            _adopt(a, family, cls, a.confidence)


def peers(found: list[Candidate], spans: list[TextSpan], lib: Library, cfg: DetectionConfig) -> None:
    """Rules 3, 3b and 3c."""
    devices = [c for c in found if c.role == "device" and c.family not in ("terminal", "rcd", "rcbo", *NOT_DEVICES)]
    contacts = [c for c in found if c.role == "power_contact" and c.family in UNSURE_RATED and not _sure(c, cfg)]
    rating = {id(c): _rating(c, spans, cfg) for c in [*devices, *contacts]}  # an RCD in the row is no breaker's peer
    _rated_buttons(devices, contacts, rating, lib, cfg)
    devices += [c for c in contacts if c.role == "device"]
    _row_vote(devices, rating, lib, cfg)
    sure = [c for c in devices if _sure(c, cfg) and c.family in PROTECTIVE and rating[id(c)] is not None]
    for c in devices:
        if _sure(c, cfg) or rating[id(c)] is None:
            continue
        like = [a for a in sure if _alike(a, c, rating)]
        if not like:
            continue
        best = max(like, key=lambda a: (a.confidence, -abs(a.bbox[0] - c.bbox[0])))
        if (best.family, best.symbol_class) != (c.family, c.symbol_class):
            _adopt(c, best.family, best.symbol_class, min(_cap(cfg), max(c.confidence, best.confidence * PEER_SHARE)))


def _height_alike(a: Candidate, b: Candidate) -> bool:
    ha, hb = a.bbox[3] - a.bbox[1], b.bbox[3] - b.bbox[1]
    return min(ha, hb) >= HEIGHT_SHARE * max(ha, hb)


def _allowed(designator: str | None, lib: Library) -> tuple[str, ...]:
    return prefix_classes(tags(designator)[0], lib.prefixes) if designator else ()


def weigh_by_prefix(c: Candidate, lib: Library, cfg: DetectionConfig, page: list[Candidate] = ()) -> None:  # type: ignore[assignment]
    """Rule 4, after the designator is linked. `page`: the page's symbols. A smaller one beside a sure device with
    the same tag is a part of its drawing (NEVIS-1 F5's N contact, its cross): the letter names the device, not it."""
    allowed = _allowed(c.designator, lib)
    if not allowed or c.symbol_class in allowed or _sure(c, cfg):
        return
    if any(
        o is not c
        and o.designator == c.designator
        and _sure(o, cfg)
        and o.height > c.height
        and gap(o.bbox, c.bbox) <= o.height
        for o in page
    ):
        return
    seen = [(score, -allowed.index(cls), cls) for cls, score in c.candidates if cls in allowed and cls in lib.classes]
    if seen:
        score, _, cls = max(seen)
        _adopt(c, lib.classes[cls].family, cls, min(_cap(cfg), max(score, TEXT_FLOOR)))
        return
    own = [cls for cls in allowed if cls in lib.classes and lib.classes[cls].family == c.family]
    if len(own) == 1:
        c.symbol_class = own[0]
