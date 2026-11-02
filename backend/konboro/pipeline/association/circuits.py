"""The circuit around a device, from stage 2's wire graph (02 §2.5), on vector pages: what lies below it on its
outgoing line, and what protects it from above (04 §5.1.1 rule 3, §5.8 item 4, 05 §5.5.1).

A walk starts at the wire ends inside the symbol's box and follows edges that run forward, down the page for a
symbol on a vertical line (orientation 0), to the right on a horizontal one. Entering another symbol's box records it
and goes on through it; a junction outside a symbol (three edges or more: a bus, a branch) ends the walk. Text beside
the line walked (a cable, a range of circuit numbers) belongs to the circuit.

Without a wire graph (a scanned page, 02 §2.5 `not_supported`), there is no walk: no chains, no upstream device.
"""

import gzip
import json
from collections import defaultdict
from dataclasses import dataclass, field

from konboro.contracts.common import Bbox
from konboro.contracts.detection import Detection

from .assign import Text, gap

Point = tuple[float, float]
TOLERANCE_PT = 2.0
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


def _axis(d: Detection) -> int:
    return 1 if d.orientation % 180 == 0 else 0  # forward is +y for a vertical line, +x for a horizontal one


def _inside(p: Point, b: Bbox, tol: float = TOLERANCE_PT) -> bool:
    return b[0] - tol <= p[0] <= b[2] + tol and b[1] - tol <= p[1] <= b[3] + tol


def walk(wires: Wires, start: Detection, detections: list[Detection], direction: int = 1) -> Walk:
    """From `start` along its line, forward (`direction` 1) or back (−1)."""
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
                entered = next((det for det, box in sorted(boxes.items()) if _inside(there, box)), None)
                if entered is not None:
                    if entered not in out.symbols:
                        out.symbols.append(entered)
                    current = boxes[entered]
                    inner = [x for x in wires.nodes_in(current) if x not in seen_nodes]
                    seen_nodes.update(inner)
                    nxt += [m, *inner]
                    continue
                out.points += [*pts, there]
                if len(wires.adjacent.get(m, [])) >= 3 and not _inside(there, current):
                    continue  # a junction: a bus or a branch ends the circuit
                nxt.append(m)
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
    if not w.points:
        return []
    out = []
    for t in texts:
        b = t.span.bbox
        if any(gap(b, (x, y, x, y)) <= TEXT_REACH_PT for x, y in w.points):
            out.append(t)
    return out
