"""04 §5.2: geometric association, in code. Which text belongs to which symbol, and what it says.

For every billable symbol, the candidate spans lie within `assoc_radius` (3 × the symbol's height) on the whole page,
not only its tile, so a label past a tile's edge is not lost. Each (symbol, span) pair gets a score:
- distance: closer is higher (`1 / (1 + gap / height)`);
- alignment: the span lies above, below or beside the symbol, within its extent;
- direction: the span runs the way the symbol does;
- family fit: a span with a reading of the family's attributes fits; one with only a model, a brand or a
  multiplicity fits less; one whose readings mean nothing to this family ("30mA" beside a contactor) not at all;
- competition: each span goes to the symbol that scores it highest (the assignment that maximizes the total when
  every span goes to one symbol), and a runner-up within `resolved_gap` lowers the association's confidence.

A symbol is resolved (5.2 item 4) when every attribute it must read was found, each from one span with association
confidence ≥ 0.9, with no close competitor and no competing value, and no multiplicity or shared label near it.
"Must read" is required and never filled in later: current and poles (S13 decision; curve and breaking capacity may
come from the factory's defaults in stage 5).

Shared labels (S13 decision, 04 §13 item 1) are found here on the whole page: one span over a row of same-class
symbols with no value of their own for what it says. The tile agent confirms or corrects them.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from konboro.contracts.common import Bbox
from konboro.contracts.detection import Detection
from konboro.contracts.extraction import TextSpan

from .config import DEFAULT, AssociationConfig
from .grammar import CONTEXT_KEYS, Reading, parse, same
from .schemas import Schemas

# Keys any billable symbol may take from a span beside it, whatever its family (04 §5.1, §5.1.1, 05 §5.2)
CONTEXT_FIT_KEYS = frozenset(
    {"model_token", "brand", "multiplicity", "spare", "lockable", "load_current_a", "unknown_prefixed"}
)


def gap(a: Bbox, b: Bbox) -> float:
    """The distance between two boxes; 0 when they touch or overlap."""
    dx = max(a[0] - b[2], 0.0, b[0] - a[2])
    dy = max(a[1] - b[3], 0.0, b[1] - a[3])
    return math.hypot(dx, dy)


def centre(b: Bbox) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def height(d: Detection, cfg: AssociationConfig = DEFAULT) -> float:
    """The symbol's height: along its line (a breaker drawn on a vertical line is tall, on a horizontal one wide)."""
    w, h = d.bbox[2] - d.bbox[0], d.bbox[3] - d.bbox[1]
    return max(cfg.min_height_pt, max(w, h))


def radius(d: Detection, cfg: AssociationConfig = DEFAULT) -> float:
    return cfg.radius_factor * height(d, cfg)


@dataclass
class Text:
    span: TextSpan
    readings: list[Reading]

    @property
    def id(self) -> str:
        return self.span.span_id


def texts(spans: list[TextSpan], designators: set[str] = frozenset()) -> list[Text]:  # type: ignore[assignment]
    """The page's spans and their readings. A span that is a device's tag on this page (C1, C3: contactors, not
    curve C at 1 A) is read as nothing: stage 3 linked it (03 §3.7)."""
    return [Text(s, [] if s.text.strip() in designators else parse(s.text)) for s in spans]


def fit(readings: list[Reading], family: str, schemas: Schemas, cfg: AssociationConfig = DEFAULT) -> float:
    names = set(schemas.names(family))
    fitting = [r for r in readings if r.fits(family)]
    if any(r.key in names for r in fitting):
        return 1.0
    context = CONTEXT_FIT_KEYS if "current_a" in names else CONTEXT_FIT_KEYS - {"load_current_a"}
    if any(r.key in context for r in fitting):
        return cfg.context_fit
    if any(r.key == "symbol_class" or (r.key == "family" and r.value == family) for r in fitting):
        return cfg.context_fit
    return 0.0


def _aligned(d: Detection, b: Bbox) -> bool:
    cx, cy = centre(b)
    x0, y0, x1, y1 = d.bbox
    return x0 <= cx <= x1 or y0 <= cy <= y1


def score(d: Detection, t: Text, schemas: Schemas, cfg: AssociationConfig = DEFAULT) -> float:
    g = gap(d.bbox, t.span.bbox)
    if g > radius(d, cfg):
        return 0.0
    f = fit(t.readings, d.family, schemas, cfg)
    if f == 0:
        return 0.0
    s = f / (1 + g / height(d, cfg))
    if _aligned(d, t.span.bbox):
        s *= cfg.align_bonus
    if t.span.rotation % 180 == d.orientation % 180:
        s *= cfg.direction_bonus
    return s


@dataclass
class Link:
    det_id: str
    span_id: str
    score: float
    gap: float
    margin: float  # (best − runner-up) / best; 1 when no other symbol wants the span
    confidence: float  # association confidence (6.4)
    shared: bool = False  # through a shared label (5.6 item 2)


@dataclass
class Assignment:
    links: dict[str, list[Link]] = field(default_factory=lambda: defaultdict(list))  # det_id → its spans
    competitors: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))  # span → others in range
    shared_labels: list["SharedLabel"] = field(default_factory=list)


@dataclass
class SharedLabel:
    span_ids: list[str]
    applies_to: list[str]  # det ids
    keys: list[str]
    reason: str = ""


def _association_confidence(g: float, h: float, margin: float, cfg: AssociationConfig) -> float:
    near = 1.0 if g <= h else max(0.5, 1.0 - 0.25 * (g - h) / h)
    return round(near * (1.0 if margin >= cfg.resolved_gap else cfg.near_competitor), 4)


def associate(
    detections: list[Detection], page_texts: list[Text], schemas: Schemas, cfg: AssociationConfig = DEFAULT
) -> Assignment:
    """Every span to the billable symbol that scores it highest, on the whole page (5.2 items 1–3)."""
    out = Assignment()
    billable = [d for d in detections if d.billable]
    for t in page_texts:
        scored = sorted(((score(d, t, schemas, cfg), d) for d in billable), key=lambda p: (-p[0], p[1].det_id))
        scored = [(s, d) for s, d in scored if s > 0]
        if not scored:
            continue
        best_score, best = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0
        margin = (best_score - second) / best_score
        g = gap(best.bbox, t.span.bbox)
        conf = _association_confidence(g, height(best, cfg), margin, cfg)
        link = Link(best.det_id, t.id, round(best_score, 4), round(g, 2), round(margin, 4), conf)
        out.links[best.det_id].append(link)
        out.competitors[t.id] = [d.det_id for _, d in scored[1:]]
    out.shared_labels = find_shared_labels(billable, page_texts, out, schemas, cfg)
    for label in out.shared_labels:
        owner_links = {lk.span_id: lk for ls in out.links.values() for lk in ls}
        for det_id in label.applies_to:
            for span_id in label.span_ids:
                if any(lk.span_id == span_id for lk in out.links[det_id]):
                    continue
                base = owner_links.get(span_id)
                out.links[det_id].append(
                    Link(det_id, span_id, base.score if base else 0.0, 0.0, 0.0, cfg.near_competitor, shared=True)
                )
    return out


# --- values -------------------------------------------------------------------------------------------------------


@dataclass
class Value:
    """One attribute's value and its evidence (04 §6.2)."""

    value: Any
    source: str  # drawing, graphic, shared_label
    span_ids: list[str]
    parse_confidence: float
    association_confidence: float
    span_confidence: float
    graphic_note: str | None = None

    @property
    def confidence(self) -> float:
        return round(self.parse_confidence * self.association_confidence * self.span_confidence, 4)


@dataclass
class Read:
    """What the text near one symbol says."""

    values: dict[str, Value] = field(default_factory=dict)  # attributes of the family's schema
    context: dict[str, list[Value]] = field(default_factory=dict)  # model tokens, multiplicity, load current, …
    conflicts: list[str] = field(default_factory=list)  # attributes two spans gave different values for
    symbol_class: str | None = None  # a hint in the text (MCB, MCCB) within the symbol's family
    explicit_texts: list[str] = field(default_factory=list)
    span_ids: list[str] = field(default_factory=list)


def read(
    d: Detection,
    links: list[Link],
    by_id: dict[str, Text],
    schemas: Schemas,
    class_family: dict[str, str],
) -> Read:
    """The symbol's values from its spans (5.6 item 1); a direct value beats a shared label (5.6 item 2, §7)."""
    out = Read()
    names = set(schemas.names(d.family))
    ordered = sorted(links, key=lambda lk: (lk.shared, -lk.confidence, lk.gap, lk.span_id))
    for lk in ordered:
        t = by_id[lk.span_id]
        out.span_ids.append(t.id)
        if not lk.shared:
            out.explicit_texts.append(t.span.text)
        for r in t.readings:
            if not r.fits(d.family):
                continue
            v = Value(
                r.value,
                "shared_label" if lk.shared else "drawing",
                [t.id],
                r.confidence,
                lk.confidence,
                t.span.confidence,
            )
            if r.key == "symbol_class":
                if class_family.get(r.value) == d.family and out.symbol_class is None:
                    out.symbol_class = r.value
                continue
            if r.key in names:
                have = out.values.get(r.key)
                if have is None:
                    out.values[r.key] = v
                elif same(have.value, r.value) or _refines(r.key, have.value, r.value):
                    if t.id not in have.span_ids:
                        have.span_ids.append(t.id)
                    if _refines(r.key, have.value, r.value) and have.value == "electronic":
                        have.value = r.value
                elif not lk.shared and have.source != "shared_label":
                    if r.key not in out.conflicts:
                        out.conflicts.append(r.key)
                elif not lk.shared:  # a direct value beats the shared label's
                    out.values[r.key] = v
            elif r.key in CONTEXT_KEYS or r.key not in names:
                bucket = out.context.setdefault(r.key, [])
                if not any(same(x.value, r.value) for x in bucket):
                    bucket.append(v)
    return out


def _refines(key: str, a: Any, b: Any) -> bool:
    """Two values that don't contradict: "אלקטרוני" and LSI (an electronic trip unit, and which one)."""
    return key == "trip_unit" and "electronic" in (a, b) and a != b


def resolved(
    d: Detection, r: Read, links: list[Link], schemas: Schemas, near_shared: bool, cfg: AssociationConfig = DEFAULT
) -> bool:
    """04 §5.2 item 4."""
    if r.conflicts or near_shared or "multiplicity" in r.context:
        return False
    by_span = {lk.span_id: lk for lk in links}
    for name in schemas.must_read(d.family):
        v = r.values.get(name)
        if v is None or v.source != "drawing":
            return False
        if not any(
            by_span[s].confidence >= cfg.resolved_confidence and by_span[s].margin >= cfg.resolved_gap
            for s in v.span_ids
            if s in by_span
        ):
            return False
    return True


# --- shared labels and the neutral pole ---------------------------------------------------------------------------


def _rows(detections: list[Detection], cfg: AssociationConfig) -> list[list[Detection]]:
    """Symbols of one class side by side, in a horizontal row or a vertical column, without a wide gap."""
    rows: list[list[Detection]] = []
    by_class: dict[str, list[Detection]] = defaultdict(list)
    for d in detections:
        by_class[d.symbol_class].append(d)
    for members in by_class.values():
        for axis in (0, 1):  # 0: a row (same y), 1: a column (same x)
            other = 1 - axis
            members_sorted = sorted(members, key=lambda d: (round(centre(d.bbox)[other]), centre(d.bbox)[axis]))
            groups: list[list[Detection]] = []
            for d in members_sorted:
                h = height(d, cfg)
                c = centre(d.bbox)
                g = groups[-1] if groups else None
                if g is not None:
                    last = g[-1]
                    lc = centre(last.bbox)
                    if abs(lc[other] - c[other]) <= cfg.row_tolerance * h and (
                        abs(c[axis] - lc[axis]) <= cfg.row_gap_factor * max(h, height(last, cfg))
                    ):
                        g.append(d)
                        continue
                groups.append([d])
            rows += [g for g in groups if len(g) >= 2]
    return rows


def find_shared_labels(
    billable: list[Detection], page_texts: list[Text], assignment: Assignment, schemas: Schemas, cfg: AssociationConfig
) -> list[SharedLabel]:
    by_id = {t.id: t for t in page_texts}
    owner_of = {lk.span_id: det for det, ls in assignment.links.items() for lk in ls}
    own_keys: dict[str, set[str]] = defaultdict(set)
    for det_id, ls in assignment.links.items():
        family = next((d.family for d in billable if d.det_id == det_id), "")
        names = set(schemas.names(family))
        for lk in ls:
            own_keys[det_id] |= {r.key for r in by_id[lk.span_id].readings if r.key in names and r.fits(family)}
    out: list[SharedLabel] = []
    for row in _rows(billable, cfg):
        ids = {d.det_id for d in row}
        bare = [d for d in row if not own_keys[d.det_id]]
        if not bare:
            continue
        lo_x = min(d.bbox[0] for d in row)
        hi_x = max(d.bbox[2] for d in row)
        lo_y = min(d.bbox[1] for d in row)
        hi_y = max(d.bbox[3] for d in row)
        for span_id, det_id in sorted(owner_of.items()):
            if det_id not in ids:
                continue
            t = by_id[span_id]
            family = row[0].family
            keys = sorted({r.key for r in t.readings if r.key in set(schemas.names(family)) and r.fits(family)})
            if not keys:
                continue
            cx, cy = centre(t.span.bbox)
            if not (lo_x <= cx <= hi_x or lo_y <= cy <= hi_y):
                continue
            # the label's owner must be the only one in the row with text of its own
            if sum(1 for d in row if own_keys[d.det_id]) != 1:
                continue
            out.append(
                SharedLabel(
                    [span_id],
                    sorted(d.det_id for d in row),
                    keys,
                    f"one label over {len(row)} {row[0].symbol_class} in a row, the others with no text of their own",
                )
            )
    return out


NEUTRAL_HOSTS = frozenset({"circuit_breaker", "rcbo", "rcd"})
NEUTRAL_GUESTS = frozenset({"switch_disconnector", "circuit_breaker"})  # untagged; tagged, any but an aux contact


def _is_n(text: str) -> bool:
    return text.strip().strip("\"'״׳”“").strip() == "N"


def absorb_neutral(
    detections: list[Detection], spans: list[TextSpan], cfg: AssociationConfig = DEFAULT
) -> dict[str, str]:
    """A 1P+N breaker's neutral contact, drawn on its own N line beside it (NEVIS-1 F3–F5): absorbed into the tagged
    breaker it sits level with, so it is no device of its own (S13 decision, S12 backlog). Untagged, or tagged
    with the breaker's own tag. Returns absorbed det id → host det id."""
    hosts = [d for d in detections if d.family in NEUTRAL_HOSTS and d.designator and d.role == "device"]
    n_spans = [s for s in spans if _is_n(s.text)]
    out: dict[str, str] = {}
    for g in detections:
        if g.det_id in out.values() or g.family == "aux_contact":
            continue
        if g.designator is None and g.family not in NEUTRAL_GUESTS:
            continue
        best: tuple[float, str] | None = None
        for h in hosts:
            if h.det_id == g.det_id or (g.designator and g.designator != h.designator):
                continue
            top, bottom = max(g.bbox[1], h.bbox[1]), min(g.bbox[3], h.bbox[3])
            overlap = bottom - top
            if overlap < 0.5 * min(g.bbox[3] - g.bbox[1], h.bbox[3] - h.bbox[1]):
                continue
            sideways = gap(g.bbox, h.bbox)
            if sideways > cfg.neutral_reach * height(h, cfg):
                continue
            if not any(gap(g.bbox, s.bbox) <= radius(g, cfg) for s in n_spans):
                continue
            if best is None or sideways < best[0]:
                best = (sideways, h.det_id)
        if best is not None:
            out[g.det_id] = best[1]
    return out
