"""The circuit around a device, from stage 2's wire graph (02 §2.5), on vector pages: what lies below it on its
outgoing line, and what protects it from above (04 §5.1.1 rule 3, §5.8 item 4, 05 §5.5.1).

A walk starts at the wire ends inside the symbol's box and follows edges that run forward, down the page for a
symbol on a vertical line (orientation 0), to the right on a horizontal one. Where a line ends, a line that starts
within the tolerance of a point it passed carries on (25.26.100's wires start half a point off a breaker's end
circle, at no node of it; BUG-072). Entering another symbol's box records it
and goes on through it; a junction outside a symbol (three edges or more: a bus, a branch) ends the walk. Text beside
the line walked (a cable, a range of circuit numbers) belongs to the circuit: a protective device's cable is the one
written along its outgoing line before the next protective device (BUG-072, 05 §5.5.1's poles from the cable cores).

Without a wire graph (a scanned page, 02 §2.5 `not_supported`), there is no walk: no chains, no upstream device.
"""

import gzip
import itertools
import json
from collections import defaultdict
from dataclasses import dataclass, field

from konboro.contracts.common import Bbox
from konboro.contracts.detection import Detection

from .assign import Text, gap

Point = tuple[float, float]
TOLERANCE_PT = 2.0
GAP_PT = 3.0  # a line that starts this close to where another ended carries it on (BUG-072)
STUB_PT = 4.0  # a dead end this short is a tick drawn on the line, not a branch
MAX_STEPS = 400
TEXT_REACH_PT = 14.0  # a cable or a circuit number this close to the line walked
PROTECTIVE = frozenset({"circuit_breaker", "rcd", "rcbo", "fuse", "switch_disconnector"})
CELL = 20.0


@dataclass
class Wires:
    nodes: list[Point]
    edges: list[tuple[int, int, list[Point]]]
    adjacent: dict[int, list[int]] = field(default_factory=dict)  # node → edge indices
    grid: dict[tuple[int, int], list[int]] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: bytes) -> "Wires":
        raw = gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data
        body = json.loads(raw)
        nodes = [(float(x), float(y)) for x, y in body["nodes"]]
        edges = [(e["a"], e["b"], [(float(x), float(y)) for x, y in e.get("pts", [])]) for e in body["edges"]]
        return cls.build(nodes, edges)

    @classmethod
    def build(cls, nodes: list[Point], edges: list[tuple[int, int, list[Point]]]) -> "Wires":
        adjacent: dict[int, list[int]] = defaultdict(list)
        for i, (a, b, _) in enumerate(edges):
            adjacent[a].append(i)
            adjacent[b].append(i)
        grid: dict[tuple[int, int], list[int]] = defaultdict(list)
        for i, (x, y) in enumerate(nodes):
            grid[(int(x // CELL), int(y // CELL))].append(i)
        return cls(nodes, edges, dict(adjacent), dict(grid))

    def degree(self, n: int) -> int:
        """How many nodes a node joins. A circle drawn as two arcs between the same two nodes (25.26.100's breaker
        ends, BUG-072) is one way on, not a junction, and a short dead end is a tick on the line, not a branch."""
        x, y = self.nodes[n]
        out = set()
        for a, b, _ in (self.edges[e] for e in self.adjacent.get(n, [])):
            m = a if b == n else b
            mx, my = self.nodes[m]
            if len(self.adjacent.get(m, [])) == 1 and abs(mx - x) + abs(my - y) <= STUB_PT:
                continue
            out.add(m)
        return len(out)

    def nodes_in(self, b: Bbox, tol: float = TOLERANCE_PT) -> list[int]:
        x0, y0, x1, y1 = b[0] - tol, b[1] - tol, b[2] + tol, b[3] + tol
        out = []
        for gx in range(int(x0 // CELL), int(x1 // CELL) + 1):
            for gy in range(int(y0 // CELL), int(y1 // CELL) + 1):
                for i in self.grid.get((gx, gy), []):
                    x, y = self.nodes[i]
                    if x0 <= x <= x1 and y0 <= y <= y1:
                        out.append(i)
        return sorted(out)


@dataclass
class Walk:
    symbols: list[str] = field(default_factory=list)  # det ids met, in order
    points: list[Point] = field(default_factory=list)  # the line walked, outside symbols
    segments: list[tuple[Point, Point]] = field(default_factory=list)  # the same line, as straight pieces


def _axis(d: Detection) -> int:
    return 1 if d.orientation % 180 == 0 else 0  # forward is +y for a vertical line, +x for a horizontal one


def _inside(p: Point, b: Bbox, tol: float = TOLERANCE_PT) -> bool:
    return b[0] - tol <= p[0] <= b[2] + tol and b[1] - tol <= p[1] <= b[3] + tol


def walk(
    wires: Wires,
    start: Detection,
    detections: list[Detection],
    direction: int = 1,
    stop: frozenset[str] = frozenset(),
) -> Walk:
    """From `start` along its line, forward (`direction` 1) or back (−1). The walk records a symbol in `stop` (det
    ids) and goes no further through it."""
    axis = _axis(start)
    out = Walk()
    boxes = {d.det_id: d.bbox for d in detections if d.det_id != start.det_id}
    frontier = wires.nodes_in(start.bbox)
    seen_nodes = set(frontier)
    seen_edges: set[int] = set()
    current = start.bbox
    steps = 0
    while frontier and steps < MAX_STEPS:
        steps += 1
        nxt: list[int] = []
        for n in frontier:
            here = wires.nodes[n]
            for e in wires.adjacent.get(n, []):
                if e in seen_edges:
                    continue
                a, b, pts = wires.edges[e]
                m = b if a == n else a
                there = wires.nodes[m]
                if (there[axis] - here[axis]) * direction <= TOLERANCE_PT / 2 and not _inside(there, current):
                    continue  # not forward
                seen_edges.add(e)
                if m in seen_nodes:
                    continue
                seen_nodes.add(m)
                line = [here, *pts, there]
                out.segments += list(itertools.pairwise(line))  # up to the next symbol's box too
                entered = next((det for det, box in sorted(boxes.items()) if _inside(there, box)), None)
                if entered is not None:
                    if entered not in out.symbols:
                        out.symbols.append(entered)
                    if entered in stop:
                        continue
                    current = boxes[entered]
                    inner = [x for x in wires.nodes_in(current) if x not in seen_nodes]
                    seen_nodes.update(inner)
                    nxt += [m, *inner]
                    continue
                out.points += [*pts, there]
                if wires.degree(m) >= 3 and not _inside(there, current):
                    continue  # a junction: a bus or a branch ends the circuit
                nxt.append(m)
                if wires.degree(m) <= 1:  # the line ends here: does another start where it passed? (BUG-072)
                    for p in [*pts, there]:
                        for k in wires.nodes_in((p[0], p[1], p[0], p[1]), GAP_PT):
                            if k not in seen_nodes and (wires.nodes[k][axis] - here[axis]) * direction > 0:
                                seen_nodes.add(k)
                                out.segments.append((p, wires.nodes[k]))
                                nxt.append(k)
        frontier = nxt
    return out


def upstream(wires: Wires, d: Detection, detections: list[Detection]) -> Detection | None:
    """The protective device right above it on its line (05 §5.5.1: a contactor's current from its breaker)."""
    by_id = {x.det_id: x for x in detections}
    for det_id in walk(wires, d, detections, -1).symbols:
        x = by_id[det_id]
        if x.billable and x.family in PROTECTIVE:
            return x
    return None


def downstream(wires: Wires, d: Detection, detections: list[Detection]) -> tuple[list[Detection], Walk]:
    """The billable devices below it on its line, in order, and the walk."""
    by_id = {x.det_id: x for x in detections}
    w = walk(wires, d, detections, 1)
    return [by_id[i] for i in w.symbols if by_id[i].billable], w


def texts_on(w: Walk, texts: list[Text]) -> list[Text]:
    """Text written beside the line walked."""
    if not w.segments:
        return []
    out = []
    for t in texts:
        b = t.span.bbox
        if any(_to_segment(b, p, q) <= TEXT_REACH_PT for p, q in w.segments):
            out.append(t)
    return out


def _to_segment(b: Bbox, p: Point, q: Point) -> float:
    """A box's distance to a straight piece of wire (wires are drawn straight: across or along the page)."""
    x0, y0, x1, y1 = min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1])
    return gap(b, (x0, y0, x1, y1)) if x0 == x1 or y0 == y1 else min(gap(b, (*p, *p)), gap(b, (*q, *q)))


def cable_below(wires: Wires, d: Detection, detections: list[Detection], texts: list[Text]) -> Text | None:
    """BUG-072: the cable written along the device's outgoing line, before the next protective device (whose line
    that is), nearest the device: 25.26.100 writes "3X1.5 N2XY" halfway down to the outlet."""
    stop = frozenset(x.det_id for x in detections if x.det_id != d.det_id and x.family in PROTECTIVE)
    w = walk(wires, d, detections, 1, stop)
    cables = [t for t in texts_on(w, texts) if any(r.key == "cable_cores" for r in t.readings)]
    return min(cables, key=lambda t: (gap(t.span.bbox, d.bbox), t.id)) if cables else None
