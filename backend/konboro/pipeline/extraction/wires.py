"""2.5 wire graph (02 §2.5), vector pages only: what is connected to what, as nodes and edges.

1. Wiring lines only: straight runs of lines and polylines, less
   - every stroke inside a text box: a letter drawn as lines on these drawings;
   - the frame: strokes wholly inside the page's border band (`BORDER_SHARE`), and lines that run across most of
     the page (`FRAME_SHARE`);
   - the title block stage 1 found.
   Rectangles are shapes, not wires. The panels' boxes from stage 1 are not a filter: they miss parts of drawings
   (BUG-019).
2. Ends within `TOLERANCE_PT` of each other are one node; an end that lands on another segment's middle splits it
   there, a T-junction. Lines that only cross are not connected (a drawing marks a joint with a dot).
3. Chains of nodes with two edges become one edge, so an edge runs from a junction or an end to the next. A
   connected piece smaller than a letter is dropped: a drawn letter the text boxes missed.
4. Links to symbols: none yet. 1.0 has no CAD blocks (2.0), and stage 3's detections come later (S12).
"""

import gzip
import itertools
import json
import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from konboro.contracts.common import Bbox

from .geometry import contains
from .vector import Path

TOLERANCE_PT = 0.5
BORDER_SHARE = 0.04  # of the page's width or height, on every side: the frame and its grid labels
FRAME_SHARE = 0.8  # a line longer than this share of the page's width or height is a frame or table line
SPECK_PT = 12.0  # a connected piece smaller than this both ways is a drawn letter OCR found no text for
TEXT_PAD_PT = 1.0
CELL_PT = 8.0  # the spatial grid's cell

Point = tuple[float, float]


@dataclass
class Graph:
    nodes: list[Point] = field(default_factory=list)
    edges: list[tuple[int, int, list[Point]]] = field(default_factory=list)  # from, to, the points between
    segments_in: int = 0

    def to_json(self) -> bytes:
        body = {
            "nodes": [[round(x, 2), round(y, 2)] for x, y in self.nodes],
            "edges": [
                {"a": a, "b": b, "pts": [[round(x, 2), round(y, 2)] for x, y in pts]} for a, b, pts in self.edges
            ],
            "block_links": [],
        }
        return gzip.compress(json.dumps(body, separators=(",", ":")).encode())


def wiring_segments(
    paths: list[Path],
    size: tuple[float, float],
    text_boxes: list[Bbox],
    title_blocks: Sequence[Bbox] = (),
) -> list[tuple[Point, Point]]:
    w, h = size
    inner = (BORDER_SHARE * w, BORDER_SHARE * h, (1 - BORDER_SHARE) * w, (1 - BORDER_SHARE) * h)
    padded = [(b[0] - TEXT_PAD_PT, b[1] - TEXT_PAD_PT, b[2] + TEXT_PAD_PT, b[3] + TEXT_PAD_PT) for b in text_boxes]
    padded += list(title_blocks)
    grid: dict[tuple[int, int], list[Bbox]] = defaultdict(list)
    for b in padded:
        for cell in _cells(b):
            grid[cell].append(b)
    out: list[tuple[Point, Point]] = []
    for p in paths:
        if p.kind == "rect":
            continue
        for start, end in itertools.pairwise(p.points):
            if start == end:
                continue
            seg = (min(start[0], end[0]), min(start[1], end[1]), max(start[0], end[0]), max(start[1], end[1]))
            in_border = seg[2] < inner[0] or seg[0] > inner[2] or seg[3] < inner[1] or seg[1] > inner[3]
            if in_border or seg[2] - seg[0] > FRAME_SHARE * w or seg[3] - seg[1] > FRAME_SHARE * h:
                continue
            if any(contains(t, seg) for cell in _cells(seg) for t in grid.get(cell, ())):
                continue
            out.append((start, end))
    return out


def _cells(b: Bbox) -> list[tuple[int, int]]:
    return [
        (i, j)
        for i in range(math.floor(b[0] / CELL_PT), math.floor(b[2] / CELL_PT) + 1)
        for j in range(math.floor(b[1] / CELL_PT), math.floor(b[3] / CELL_PT) + 1)
    ]


def _distance(p: Point, a: Point, b: Point) -> tuple[float, float]:
    """The distance from p to the segment ab, and where along it (0–1) the nearest point is."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2)) if length2 else 0.0
    nx, ny = a[0] + t * dx, a[1] + t * dy
    return math.hypot(p[0] - nx, p[1] - ny), t


def build(segments: list[tuple[Point, Point]]) -> Graph:
    graph = Graph(segments_in=len(segments))
    # 2a. split segments where another segment's end lands on their middle
    seg_grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, (a, b) in enumerate(segments):
        for cell in _cells((min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))):
            seg_grid[cell].append(i)
    cuts: dict[int, list[float]] = defaultdict(list)
    for a, b in segments:
        for end in (a, b):
            for i in {i for cell in _cells((end[0], end[1], end[0], end[1])) for i in seg_grid.get(cell, ())}:
                sa, sb = segments[i]
                d, t = _distance(end, sa, sb)
                length = math.hypot(sb[0] - sa[0], sb[1] - sa[1])
                if d <= TOLERANCE_PT and TOLERANCE_PT < t * length < length - TOLERANCE_PT:
                    cuts[i].append(t)
    pieces: list[tuple[Point, Point]] = []
    for i, (a, b) in enumerate(segments):
        ts = [0.0, *sorted(set(cuts.get(i, []))), 1.0]
        pts = [(a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])) for t in ts]
        pieces += list(itertools.pairwise(pts))
    # 2b. ends within the tolerance are one node
    node_grid: dict[tuple[int, int], list[int]] = defaultdict(list)

    def node(p: Point) -> int:
        cx, cy = math.floor(p[0] / TOLERANCE_PT), math.floor(p[1] / TOLERANCE_PT)
        for i in range(cx - 1, cx + 2):
            for j in range(cy - 1, cy + 2):
                for n in node_grid.get((i, j), ()):
                    q = graph.nodes[n]
                    if math.hypot(p[0] - q[0], p[1] - q[1]) <= TOLERANCE_PT:
                        return n
        graph.nodes.append(p)
        node_grid[(cx, cy)].append(len(graph.nodes) - 1)
        return len(graph.nodes) - 1

    raw_edges: set[tuple[int, int]] = set()
    for pa, pb in pieces:
        na, nb = node(pa), node(pb)
        if na != nb:
            raw_edges.add((min(na, nb), max(na, nb)))
    # 3. chains through two-edge nodes become one edge
    adjacent: dict[int, list[int]] = defaultdict(list)
    for ea, eb in raw_edges:
        adjacent[ea].append(eb)
        adjacent[eb].append(ea)
    seen: set[tuple[int, int]] = set()
    for ea, eb in sorted(raw_edges):
        if (ea, eb) in seen:
            continue
        chain = [ea, eb]
        seen.add((ea, eb))
        for forward in (True, False):
            while True:
                tip, before = (chain[-1], chain[-2]) if forward else (chain[0], chain[1])
                if len(adjacent[tip]) != 2:
                    break
                nxt = next(n for n in adjacent[tip] if n != before)
                key = (min(tip, nxt), max(tip, nxt))
                if key in seen or nxt in chain:
                    break
                seen.add(key)
                if forward:
                    chain.append(nxt)
                else:
                    chain.insert(0, nxt)
        graph.edges.append((chain[0], chain[-1], [graph.nodes[n] for n in chain[1:-1]]))
    graph.edges = _without_specks(graph)
    used = sorted({n for a, b, _ in graph.edges for n in (a, b)})
    index = {old: new for new, old in enumerate(used)}
    pts = graph.nodes
    graph.nodes = [pts[n] for n in used]
    graph.edges = [(index[a], index[b], mid) for a, b, mid in graph.edges]
    return graph


def _without_specks(graph: Graph) -> list[tuple[int, int, list[Point]]]:
    parent = list(range(len(graph.nodes)))

    def root(n: int) -> int:
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for a, b, _ in graph.edges:
        parent[root(a)] = root(b)
    boxes: dict[int, list[float]] = {}
    for a, b, mid in graph.edges:
        box = boxes.setdefault(root(a), [math.inf, math.inf, -math.inf, -math.inf])
        for x, y in [graph.nodes[a], graph.nodes[b], *mid]:
            box[0], box[1], box[2], box[3] = min(box[0], x), min(box[1], y), max(box[2], x), max(box[3], y)
    keep = {r for r, b in boxes.items() if b[2] - b[0] >= SPECK_PT or b[3] - b[1] >= SPECK_PT}
    return [e for e in graph.edges if root(e[0]) in keep]
