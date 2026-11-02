"""04 §5.1.1 multiplicity and circuit numbers, and §5.1.2 supply scope. Code only.

Multiplicity, by where it is written:
1. in the device's own label ("16A MCB (x6)") → the device's count;
2. on the outgoing line or cable (the mark shares a line of text with a cable) → one device feeding N outlets: the
   count stays 1 and N is kept as the number of outlets;
3. a chain: a device right below a device with a count, on its line (the wire graph's walk), of another family (a
   contactor, an impulse relay under its breaker) takes the same count, `multiplicity_inherited`, confidence × 0.8.
   The walk stops at the next protective device: a bus feeding several breakers is not a chain.
4. the cross-check with the circuit numbers at the line's end ("36–40" is 5 outlets): the range written in the
   device's column below it. Equal → quantity confidence 1.0; a range with no multiplicity, or a different one →
   the row is yellow and stage 6 adds `QTY_RANGE_MISMATCH` (04 §5.1.1 item 4).

Supply scope: a phrase from the grammar's `scope_phrases` on a line of text near the symbol. The phrase belongs to
the nearest symbol of any kind: "הכנה בלבד" beside a generator (a load, not a quote line) leaves the changeover
switch next to it in the panel. Dashed frames (04 §5.1.2) need line styles from stage 2: backlog.
"""

from dataclasses import dataclass, field

from konboro.contracts.common import Bbox
from konboro.contracts.detection import Detection

from .assign import Text, centre, gap, height
from .config import DEFAULT, AssociationConfig
from .grammar import Grammar, load

SCOPES = ("other_location", "prepare_only", "by_others")


@dataclass
class Line:
    """Words on one baseline, joined."""

    texts: list[Text]
    bbox: Bbox

    @property
    def words(self) -> list[str]:
        return [w for t in self.texts for w in t.span.text.split()]

    @property
    def span_ids(self) -> list[str]:
        return [t.id for t in self.texts]


def lines(texts: list[Text], cfg: AssociationConfig = DEFAULT) -> list[Line]:
    out: list[Line] = []
    for t in sorted(texts, key=lambda t: (t.span.rotation, t.span.bbox[0], t.span.bbox[1], t.id)):
        b = t.span.bbox
        h = max(1.0, b[3] - b[1])
        for line in out:
            lb = line.bbox
            last = line.texts[-1].span
            if last.rotation != t.span.rotation:
                continue
            same_row = abs(centre(lb)[1] - centre(b)[1]) <= 0.5 * max(h, lb[3] - lb[1])
            near = max(b[0] - lb[2], lb[0] - b[2]) <= max(cfg.line_gap_pt, 1.5 * h)
            if same_row and near:
                line.texts.append(t)
                line.bbox = (min(lb[0], b[0]), min(lb[1], b[1]), max(lb[2], b[2]), max(lb[3], b[3]))
                break
        else:
            out.append(Line([t], b))
    return out


def _matches(phrase: str, words: list[str]) -> bool:
    """Every word of the phrase begins a word of the line ("הכנה ל" matches "הכנה לגנרטור"), any case."""
    folded = [w.casefold().strip("\"'.,:()") for w in words]
    return all(any(w.startswith(p) for w in folded) for p in phrase.casefold().split())


def scope_of(line: Line, grammar: Grammar | None = None) -> str | None:
    g = grammar or load()
    for scope in SCOPES:
        if any(_matches(p, line.words) for p in g.scope_phrases.get(scope, ())):
            return scope
    return None


@dataclass
class Scope:
    scope: str
    span_ids: list[str]
    text: str


def supply_scopes(
    detections: list[Detection], page_lines: list[Line], cfg: AssociationConfig = DEFAULT
) -> dict[str, Scope]:
    """det id → its scope, for the billable symbols a scope phrase belongs to."""
    out: dict[str, Scope] = {}
    for line in page_lines:
        scope = scope_of(line)
        if scope is None or not detections:
            continue
        nearest = min(detections, key=lambda d: (gap(d.bbox, line.bbox) / height(d, cfg), d.det_id))
        if gap(nearest.bbox, line.bbox) > cfg.scope_reach * height(nearest, cfg) or not nearest.billable:
            continue
        out.setdefault(nearest.det_id, Scope(scope, line.span_ids, " ".join(line.words)))
    return out


@dataclass
class Multiplicity:
    count: int = 1
    span_ids: list[str] = field(default_factory=list)
    outputs: int | None = None  # rule 2: the device feeds this many outlets
    inherited_from: str | None = None  # rule 3: the det id above it
    circuit_range: tuple[int, int] | None = None
    range_span_ids: list[str] = field(default_factory=list)

    @property
    def range_size(self) -> int | None:
        return self.circuit_range[1] - self.circuit_range[0] + 1 if self.circuit_range else None

    @property
    def mismatch(self) -> bool:
        """Rule 4: a range and a count that don't agree (or a range with no count)."""
        size = self.range_size
        if size is None:
            return False
        if self.outputs is not None:
            return self.outputs != size
        return self.count != size


def on_cable_line(span_id: str, page_lines: list[Line]) -> bool:
    """Rule 2: the mark shares its line of text with a cable."""
    for line in page_lines:
        if span_id in line.span_ids:
            return any(r.key == "cable_cores" for t in line.texts for r in t.readings)
    return False


def circuit_ranges(
    devices: list[Detection], texts: list[Text], cfg: AssociationConfig = DEFAULT
) -> dict[str, tuple[tuple[int, int], str]]:
    """Rule 4: each range of circuit numbers to the device whose column it is in, the nearest above it."""
    out: dict[str, tuple[tuple[int, int], str]] = {}
    for t in texts:
        r = next((r for r in t.readings if r.key == "circuit_range"), None)
        if r is None:
            continue
        cx, cy = centre(t.span.bbox)
        above = [
            d
            for d in devices
            if d.bbox[3] <= cy and d.bbox[0] - (d.bbox[2] - d.bbox[0]) <= cx <= d.bbox[2] + (d.bbox[2] - d.bbox[0])
        ]
        if not above:
            continue
        owner = min(above, key=lambda d: (abs(centre(d.bbox)[0] - cx), cy - d.bbox[3], d.det_id))
        if owner.det_id not in out:
            out[owner.det_id] = (r.value, t.id)
    return out
