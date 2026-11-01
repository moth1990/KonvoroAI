"""A symbol found on a page, before it becomes a `Detection`, and 3.5 (03 §3.5): one copy per symbol, and its owner
tile.

Tiles overlap by more than the largest symbol (02 §2.6), so one symbol is found in two to four tiles. Copies of the
same family whose page boxes overlap (IoU above `dedup_iou`, or one covering most of the other: the model boxes a
symbol a little differently in each tile) are one symbol. The most confident whole copy stays; the others' tiles go
to `seen_in_tile_ids`. A copy cut by a tile edge loses to a whole one.

The owner tile (03 §3.5 item 3) holds the box whole and is the one where it lies farthest from the tile's edges.
Stage 4 reads each symbol once, in its owner tile.
"""

from dataclasses import dataclass, field
from typing import Any

from konboro.contracts.common import Bbox

from ..extraction.geometry import contains, intersection, iou, overlap_of_smaller, union
from .config import DetectionConfig


@dataclass
class Candidate:
    bbox: Bbox  # page points
    family: str
    symbol_class: str
    role: str
    detector_score: float
    class_score: float
    method: str = "llm_vision"
    tag: str | None = None  # what the model read next to it; code links a span (designators.py)
    box_text: str | None = None
    orientation: int = 0
    tile_id: str = ""  # where this copy was seen
    cut: bool = False
    seen_in: list[str] = field(default_factory=list)
    needs_decision: str | None = None  # why it goes to the disambiguation call (03 §3.4)
    candidates: list[tuple[str, float]] = field(default_factory=list)  # class_candidates
    llm_decision: dict[str, Any] | None = None
    designator: str | None = None
    designator_span_id: str | None = None
    flags: list[str] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        """03 §6.3, with the interim method (S12): the first look's rating stands for both scores."""
        if self.method == "llm_vision":
            return self.detector_score
        if self.method == "orphan_recovery":
            return self.detector_score * 0.9
        return self.detector_score * self.class_score  # detector_llm: detector × the disambiguation's confidence

    @property
    def height(self) -> float:
        return max(self.bbox[2] - self.bbox[0], self.bbox[3] - self.bbox[1])


def same_symbol(a: Candidate, b: Candidate, cfg: DetectionConfig) -> bool:
    """Same family and overlapping (03 §3.5). Two more cases, whatever the families: boxes that mostly coincide
    (one place holds one symbol; the model named it differently in two tiles, 6199-2-50's main breaker), and the same
    tag end to end on one wire (a breaker's cross drawn apart from its blade, NEVIS-1)."""
    if iou(a.bbox, b.bbox) > cfg.dedup_iou:
        return True
    if bool(a.tag) and a.tag == b.tag and _along(a.bbox, b.bbox, cfg.dedup_touch_pt):
        return True
    return a.family == b.family and overlap_of_smaller(a.bbox, b.bbox) >= cfg.dedup_overlap


def _along(a: Bbox, b: Bbox, touch: float) -> bool:
    """Two boxes on one wire, end to end: they overlap across (most of the narrower) and nearly touch along."""

    def shared(lo0: float, hi0: float, lo1: float, hi1: float) -> float:
        return max(0.0, min(hi0, hi1) - max(lo0, lo1)) / max(1e-6, min(hi0 - lo0, hi1 - lo1))

    vertical = shared(a[0], a[2], b[0], b[2]) >= 0.5 and max(a[1], b[1]) - min(a[3], b[3]) <= touch
    horizontal = shared(a[1], a[3], b[1], b[3]) >= 0.5 and max(a[0], b[0]) - min(a[2], b[2]) <= touch
    return vertical or horizontal


def deduplicate(found: list[Candidate], cfg: DetectionConfig) -> tuple[list[Candidate], int]:
    """One candidate per symbol, the best copy kept, every copy's tile in `seen_in`. Returns (kept, removed). A
    symbol boxed in two parts (same tag, end to end) keeps the box around both."""
    kept: list[Candidate] = []
    for c in sorted(found, key=lambda c: (c.cut, -c.confidence, c.tile_id)):
        twin = next((k for k in kept if same_symbol(k, c, cfg)), None)
        if twin is None:
            c.seen_in = [c.tile_id] if c.tile_id else []
            kept.append(c)
            continue
        parts = iou(twin.bbox, c.bbox) <= cfg.dedup_iou and overlap_of_smaller(twin.bbox, c.bbox) < cfg.dedup_overlap
        if parts and not c.cut:  # matched end to end: the symbol is both boxes
            twin.bbox = union([twin.bbox, c.bbox])
        if c.symbol_class not in (cls for cls, _ in twin.candidates):  # another reading of the same symbol
            twin.candidates.append((c.symbol_class, c.class_score))
        if c.tile_id and c.tile_id not in twin.seen_in:
            twin.seen_in.append(c.tile_id)
    return kept, len(found) - len(kept)


def owner_tile(box: Bbox, tiles: list[tuple[str, Bbox]]) -> str | None:
    """The tile holding the box whole, farthest from its edges; the most overlapping tile when none holds it whole
    (a symbol larger than the overlap)."""
    whole = [(tid, t) for tid, t in tiles if contains(t, box)]
    if whole:
        return max(whole, key=lambda it: _margin(box, it[1]))[0]
    best = max(tiles, key=lambda it: intersection(box, it[1]), default=None)
    return best[0] if best and intersection(box, best[1]) > 0 else None


def _margin(box: Bbox, tile: Bbox) -> float:
    return min(box[0] - tile[0], box[1] - tile[1], tile[2] - box[2], tile[3] - box[3])


def gap(a: Bbox, b: Bbox) -> float:
    """The distance between two boxes (0 when they touch or overlap)."""
    dx = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
    return float((dx * dx + dy * dy) ** 0.5)


def centre(b: Bbox) -> tuple[float, float]:
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
