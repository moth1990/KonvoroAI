"""04 §5.3–5.5: which tiles go to the tile agent, what it is shown, and the code that checks its answer.

A tile goes to the agent (5.3) when a billable symbol it owns is not resolved by code, when it holds text with no
symbol near it that stage 3 handed on (`orphan_texts`), or always on a page read by OCR at low resolution. The agent
answers for the whole tile, so it can see the neighbours; code's assignment goes along as a proposal.

The check (5.5), for every value:
- the cited span is one we showed, and lies within 1.5 × `assoc_radius` of the symbol (or is a shared label for it);
- the value is really written in it: the grammar's reading of the span, for the symbol's family, contains the value
  (`citation_mismatch` otherwise, and the value is refused);
- `graphic` evidence for poles only, with a note;
- a span the agent gave to several symbols outside `shared_labels` stays with the nearest; the others lose it.
An answer that misses a symbol, answers one twice or names one we didn't show is refused as a whole and asked again
with the reason; after two refusals the fallback model is asked; after that the tile keeps code's assignment
(`fallback_geometric`, `agent_invalid_output`).
"""

import hashlib
import io
import json
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageDraw

from konboro.contracts.common import Bbox
from konboro.contracts.detection import Detection
from konboro.contracts.extraction import Tile
from konboro_llm import ImageInput, LLMClient, LLMError
from konboro_llm.stages import text_association
from konboro_llm.stages.text_association import TileAnswer

from .assign import Read, SharedLabel, Text, Value, gap, radius
from .config import DEFAULT, AssociationConfig
from .grammar import contains, parse, same
from .schemas import Schemas

log = logging.getLogger("konboro.pipeline.s4")

OWN = (220, 30, 30)
CONTEXT = (30, 90, 220)


@dataclass
class TileJob:
    tile: Tile
    own: list[Detection]
    context: list[Detection]
    texts: list[Text]
    reads: dict[str, Read]  # code's reading, the proposal
    origin_px: tuple[int, int]
    px_per_pt: float
    image_key: str = ""

    def to_px(self, b: Bbox) -> list[int]:
        ox, oy = self.origin_px
        return [
            round(b[0] * self.px_per_pt - ox),
            round(b[1] * self.px_per_pt - oy),
            round(b[2] * self.px_per_pt - ox),
            round(b[3] * self.px_per_pt - oy),
        ]

    def to_pt(self, b: list[float]) -> Bbox:
        ox, oy = self.origin_px
        return (
            round((b[0] + ox) / self.px_per_pt, 2),
            round((b[1] + oy) / self.px_per_pt, 2),
            round((b[2] + ox) / self.px_per_pt, 2),
            round((b[3] + oy) / self.px_per_pt, 2),
        )

    @property
    def own_ids(self) -> dict[str, str]:  # d1 → det id
        return {f"d{i}": d.det_id for i, d in enumerate(self.own, start=1)}

    @property
    def context_ids(self) -> dict[str, str]:  # c1 → det id
        return {f"c{i}": d.det_id for i, d in enumerate(self.context, start=1)}

    @property
    def span_ids(self) -> dict[str, str]:  # s1 → span id
        return {f"s{i}": t.id for i, t in enumerate(self.texts, start=1)}


def draw(tile_image: Image.Image, job: TileJob) -> Image.Image:
    """The tile with a numbered frame around every symbol (5.4): made for the call, never stored (04 §12)."""
    out = tile_image.convert("RGB").copy()
    pen = ImageDraw.Draw(out)
    for prefix, dets, colour in (("c", job.context, CONTEXT), ("d", job.own, OWN)):
        for i, d in enumerate(dets, start=1):
            x0, y0, x1, y1 = job.to_px(d.bbox)
            pen.rectangle((x0 - 2, y0 - 2, x1 + 2, y1 + 2), outline=colour, width=2)
            label = f"{prefix}{i}"
            ty = y0 - 13 if y0 >= 14 else y1 + 3
            pen.rectangle((x0 - 2, ty - 1, x0 + 7 * len(label) + 1, ty + 11), fill="white")
            pen.text((x0, ty), label, fill=colour)
    return out


def image_key(page_key: str, job: TileJob) -> str:
    """What the drawn image is, for the cassette: the page, the tile and the frames."""
    frames = [("d", job.to_px(d.bbox)) for d in job.own] + [("c", job.to_px(d.bbox)) for d in job.context]
    digest = hashlib.sha256(json.dumps(frames).encode()).hexdigest()[:12]
    return f"{page_key}:assoc:{list(job.tile.bbox_px)}:{digest}"


def _box(job: TileJob, b: Bbox) -> str:
    return json.dumps(job.to_px(b))


def prompt_parts(job: TileJob, schemas: Schemas) -> dict[str, str]:
    span_short = {v: k for k, v in job.span_ids.items()}
    own = []
    for short, d in zip(job.own_ids, job.own, strict=True):
        tag = f", tag {d.designator}" if d.designator else ""
        names = ", ".join(schemas.names(d.family)) or "(nothing; multiplicity and texts only)"
        own.append(f"- {short}: {d.family} / {d.symbol_class}{tag}, box {_box(job, d.bbox)}, read: {names}")
    context = [
        f"- {short}: {d.family} / {d.symbol_class}"
        + (f", tag {d.designator}" if d.designator else "")
        + f", box {_box(job, d.bbox)}"
        for short, d in zip(job.context_ids, job.context, strict=True)
    ]
    spans = [f'- {span_short[t.id]}: "{t.span.text}" {_box(job, t.span.bbox)}' for t in job.texts]
    proposal = []
    for short, d in zip(job.own_ids, job.own, strict=True):
        r = job.reads.get(d.det_id)
        if r is None or not r.span_ids:
            proposal.append(f"- {short}: no text")
            continue
        cited = ", ".join(span_short[s] for s in r.span_ids if s in span_short)
        values = ", ".join(f"{k}={v.value}" for k, v in r.values.items())
        proposal.append(f"- {short}: {cited or 'no text'}" + (f" → {values}" if values else ""))
    return {
        "own": "\n".join(own),
        "context": "\n".join(context),
        "spans": "\n".join(spans),
        "proposal": "\n".join(proposal),
    }


# --- the check ----------------------------------------------------------------------------------------------------


@dataclass
class Checked:
    """The agent's answer for one tile, after the check: only what survived."""

    values: dict[str, dict[str, Value]] = field(default_factory=dict)  # det → attribute → value
    nulls: dict[str, set[str]] = field(default_factory=dict)  # det → attributes the agent says are not written
    multiplicity: dict[str, tuple[int, list[str]]] = field(default_factory=dict)  # det → count, spans
    brand_hint: dict[str, str] = field(default_factory=dict)
    explicit_texts: dict[str, list[str]] = field(default_factory=dict)
    shared_labels: list[SharedLabel] = field(default_factory=list)
    missed: list[dict[str, Any]] = field(default_factory=list)  # bbox (pt), family, span ids, reason
    unassigned: set[str] = field(default_factory=set)
    citation_mismatches: int = 0
    values_cited: int = 0  # values the agent cited a span for: the citation_mismatch rate's denominator
    rejected: list[str] = field(default_factory=list)  # why each refused value was refused, for the log


class Refused(Exception):
    """The answer as a whole can't be used (5.5 rows 1–2): asked again with this message."""


def check(
    answer: TileAnswer, job: TileJob, schemas: Schemas, families: set[str], cfg: AssociationConfig = DEFAULT
) -> Checked:
    own, context, spans = job.own_ids, job.context_ids, job.span_ids
    texts = {t.id: t for t in job.texts}
    dets = {d.det_id: d for d in job.own + job.context}
    seen: list[str] = [a.det for a in answer.instances]
    unknown = sorted(set(seen) - set(own))
    missing = sorted(set(own) - set(seen), key=lambda s: int(s[1:]))
    twice = sorted({s for s in seen if seen.count(s) > 1})
    problems = []
    if missing:
        problems.append(f"no answer for {', '.join(missing)}")
    if twice:
        problems.append(f"answered twice for {', '.join(twice)}")
    if unknown:
        problems.append(f"{', '.join(unknown)} are not symbols you answer for")
    if problems:
        raise Refused("; ".join(problems))

    out = Checked()
    shared_for: dict[str, set[str]] = defaultdict(set)  # det → spans of shared labels that apply to it
    for label in answer.shared_labels:
        span_ids = [spans[s] for s in label.span_ids if s in spans]
        applies = [own.get(x) or context.get(x) for x in label.applies_to]
        applies_ids = [a for a in applies if a]
        if not span_ids or len(applies_ids) < 2:
            continue
        keys = sorted(
            {
                r.key
                for s in span_ids
                for r in texts[s].readings
                for x in applies_ids
                if r.fits(dets[x].family) and r.key in schemas.names(dets[x].family)
            }
        )
        if not keys:
            out.rejected.append(f"shared label {label.span_ids}: nothing a symbol reads")
            continue
        out.shared_labels.append(SharedLabel(span_ids, sorted(applies_ids), keys, label.reason))
        for x in applies_ids:
            shared_for[x] |= set(span_ids)

    users: dict[str, list[str]] = defaultdict(list)  # span → dets whose values cite it
    for a in answer.instances:
        det_id = own[a.det]
        d = dets[det_id]
        names = set(schemas.names(d.family))
        reach = cfg.agent_radius_factor * radius(d, cfg)
        values: dict[str, Value] = {}
        nulls: set[str] = set()
        for attr in a.attributes:
            if attr.name not in names:
                continue
            if attr.value is None or attr.evidence is None:
                nulls.add(attr.name)
                continue
            if attr.evidence == "graphic":
                if attr.name != "poles" or not attr.graphic_note or not _poles(attr.value):
                    out.rejected.append(f"{a.det}.{attr.name}: graphic evidence is for poles only, with a note")
                    continue
                conf = min(attr.confidence if attr.confidence is not None else cfg.graphic_max, cfg.graphic_max)
                values["poles"] = Value(int(attr.value), "graphic", [], conf, 1.0, 1.0, attr.graphic_note)
                continue
            cited = [spans[s] for s in attr.span_ids if s in spans]
            out.values_cited += 1
            if not cited or len(cited) != len(attr.span_ids):
                out.rejected.append(f"{a.det}.{attr.name}: cites a span we didn't show")
                continue
            near = [s for s in cited if gap(d.bbox, texts[s].span.bbox) <= reach or s in shared_for[det_id]]
            if not near:
                out.rejected.append(f"{a.det}.{attr.name}: the cited span is too far from the symbol")
                continue
            value = _typed(attr.name, attr.value)
            proof = [s for s in near if contains(texts[s].span.text, d.family, attr.name, value)]
            joined = _joined(near, texts, d.family, attr.name, value) if not proof else None
            if joined is not None:  # one value written over several spans: "21" "22", "1" "0" "2"
                proof = near
            if not proof:
                out.citation_mismatches += 1
                out.rejected.append(f"{a.det}.{attr.name}={attr.value}: citation_mismatch")
                continue
            readings = [r for s in proof for r in parse(texts[s].span.text)] if joined is None else parse(joined)
            parse_conf = max(
                r.confidence for r in readings if r.key == attr.name and same(r.value, value) and r.fits(d.family)
            )
            span_conf = min(texts[s].span.confidence for s in proof)
            assoc = min(1.0, attr.confidence if attr.confidence is not None else 0.9)
            via_label = a.uses_shared_label and all(s in shared_for[det_id] for s in proof)
            source = "shared_label" if via_label else "drawing"
            values[attr.name] = Value(value, source, proof, parse_conf, assoc, span_conf)
            if source == "drawing":
                for s in proof:
                    users[s].append(det_id)
        out.values[det_id] = values
        out.nulls[det_id] = nulls
        out.multiplicity[det_id] = _multiplicity(a, spans, texts, d.family, out)
        if a.brand_hint and any(a.brand_hint.casefold() in t.span.text.casefold() for t in job.texts):
            out.brand_hint[det_id] = a.brand_hint
        out.explicit_texts[det_id] = [texts[spans[x]].span.text for x in a.explicit_texts if x in spans]

    # 5.5 last row: a span on several symbols without a shared label stays with the nearest
    for span_id, holders in users.items():
        if len(set(holders)) < 2:
            continue
        nearest = min(set(holders), key=lambda det: (gap(dets[det].bbox, texts[span_id].span.bbox), det))
        for det_id in set(holders) - {nearest}:
            for name, v in list(out.values[det_id].items()):
                if span_id in v.span_ids:
                    del out.values[det_id][name]
                    out.rejected.append(f"{det_id}.{name}: its span belongs to {nearest}")

    for m in answer.possible_missed:
        if len(m.bbox_tile_px) != 4 or m.family_guess not in families:
            continue
        out.missed.append(
            {
                "bbox": job.to_pt(_ordered(m.bbox_tile_px)),
                "family": m.family_guess,
                "span_ids": [spans[s] for s in m.span_ids if s in spans],
                "reason": m.reason,
            }
        )
    out.unassigned = {spans[u.span_id] for u in answer.unassigned_spans if u.span_id in spans}
    return out


def _joined(spans: list[str], texts: dict[str, Text], family: str, name: str, value: Any) -> str | None:
    """The cited spans read as one text, in reading order, joined by "/", "-" or a space: the joined text that says
    the value, or None."""
    if len(spans) < 2:
        return None
    ordered = sorted(spans, key=lambda s: (texts[s].span.bbox[0], texts[s].span.bbox[1]))
    words = [texts[s].span.text.strip() for s in ordered]
    for sep in ("/", "-", " "):
        for seq in (words, words[::-1]):
            text = sep.join(seq)
            if contains(text, family, name, value):
                return text
    return None


def _ordered(b: list[float]) -> list[float]:
    x0, x1 = sorted((b[0], b[2]))
    y0, y1 = sorted((b[1], b[3]))
    return [x0, y0, x1, y1]


def _poles(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and float(v).is_integer() and 1 <= v <= 4


def _typed(name: str, v: Any) -> Any:
    if isinstance(v, float) and v.is_integer() and name not in ("breaking_capacity_ka", "range_min_a", "range_max_a"):
        return int(v)
    if isinstance(v, str) and name in ("curve", "rcd_type", "trip_unit"):
        return v.strip().upper()
    return v


def _multiplicity(
    a: Any, spans: dict[str, str], texts: dict[str, Text], family: str, out: Checked
) -> tuple[int, list[str]]:
    count = a.multiplicity.count
    if count <= 1:
        return 1, []
    cited = [spans[s] for s in a.multiplicity.span_ids if s in spans]
    proof = [s for s in cited if contains(texts[s].span.text, family, "multiplicity", count)]
    out.values_cited += 1
    if not proof:
        out.citation_mismatches += 1
        out.rejected.append(f"{a.det}.multiplicity={count}: citation_mismatch")
        return 1, []
    return count, proof


# --- asking -------------------------------------------------------------------------------------------------------

Ask = Callable[[TileJob, Image.Image, dict[str, str], str, bool], TileAnswer]


def model_asker(llm: LLMClient, legend: str, tenant_id: str | None) -> Ask:
    def ask(job: TileJob, image: Image.Image, parts: dict[str, str], correction: str, fallback: bool) -> TileAnswer:
        buf = io.BytesIO()
        image.save(buf, "PNG", compress_level=6)  # made for one call, never stored: speed over size (BUG-028)
        result = text_association.associate(
            llm,
            ImageInput(buf.getvalue(), key=job.image_key),
            image.size,
            parts["own"],
            parts["context"],
            parts["spans"],
            parts["proposal"],
            legend,
            tenant_id,
            correction=correction,
            fallback=fallback,
        )
        return result.data

    return ask


@dataclass
class TileResult:
    checked: Checked | None  # None: the agent failed (fallback_geometric)
    calls: int


def run_tile(
    job: TileJob,
    image: Image.Image,
    ask: Ask,
    schemas: Schemas,
    families: set[str],
    cfg: AssociationConfig = DEFAULT,
) -> TileResult:
    """Ask, check; once more with the reason; then the fallback model; then give up (5.5)."""
    parts = prompt_parts(job, schemas)
    drawn = draw(image, job)
    correction = ""
    calls = 0
    for fallback in (False, False, True):
        calls += 1
        try:
            answer = ask(job, drawn, parts, correction, fallback)
        except LLMError as exc:
            log.warning("tile %s: the agent failed: %s", job.tile.tile_id, exc)
            if fallback:
                break
            continue
        try:
            return TileResult(check(answer, job, schemas, families, cfg), calls)
        except Refused as exc:
            correction = str(exc)
            log.info("tile %s: answer refused: %s", job.tile.tile_id, correction)
    return TileResult(None, calls)


def cut_tile(render: Image.Image, tile: Tile) -> Image.Image:
    from ..extraction.tiles import TileGeom, cut

    return cut(render, TileGeom(tile.row, tile.col, tile.bbox_px, tile.padding_px))
