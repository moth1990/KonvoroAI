"""`explain_line` (08 §6.4), the code around the sub-agent (`konboro_llm.stages.line_explanation`).

1. **The trace.** What `get_line_details` shows, without the price trace or any money reference (00 §7: the
   sub-agent gets no amounts), with the line's instances named `I1…` and the texts beside it `S1…`.
2. **The crop.** One crop of the page that holds most of the line's instances, around them with a margin, each
   instance framed in red. A line with no instance on the drawing (derived, labor, manual) gets no crop.
3. **The check.** Every line, instance and text the answer cites must be one it was given; the rest are dropped and
   logged as `invalid_ref`. A focus on an instance it was not given is dropped.
"""

import io
import logging
from collections import Counter
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.services.storage import Storage
from konboro_llm import ImageInput
from konboro_llm.stages.line_explanation import Cites, Focus, LineExplanation

log = logging.getLogger("konboro.chat")

MARGIN_PT = 60.0  # around the instances, so the circuit beside them shows
MIN_SIDE_PT = 220.0
MAX_SIDE_PX = 1568  # the vision model's useful size
FRAME = (220, 30, 30)
MONEY_KEYS = ("price_trace", "unit_price", "line_total", "unit_cost", "margin_pct")
READ = ("drawing", "cad_attrib", "graphic", "shared_label", "bom")


@dataclass(frozen=True)
class Located:
    instance_id: str
    page_id: str
    bbox: tuple[float, float, float, float]


def located(session: Session, tenant_id: str, line_id: str) -> list[Located]:
    """Where the line is on the drawing: its component's instances, or a line's own boxes (a missing or marked
    line, 09 §6.5), which have no instance id of their own."""
    row = session.get(m.QuoteLine, line_id)
    if row is None or row.tenant_id != tenant_id:
        return []
    cmp = session.get(m.Component, row.component_id) if row.component_id else None
    if cmp is not None and cmp.tenant_id == tenant_id:
        items = [(str(i.get("instance_id") or f"{line_id}#{n}"), i) for n, i in enumerate(cmp.instances or [])]
    else:
        items = [(f"{line_id}#{n}", b) for n, b in enumerate(row.boxes or [])]
    out = []
    for iid, i in items:
        box = i.get("bbox")
        if i.get("page_id") and box and len(box) == 4:
            x0, y0, x1, y1 = (float(v) for v in box)
            out.append(Located(iid, str(i["page_id"]), (x0, y0, x1, y1)))
    return out


def scrub(value: Any) -> Any:
    """No money reference and no price trace in what the sub-agent reads (00 §7)."""
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k not in MONEY_KEYS}
    if isinstance(value, list):
        return [scrub(v) for v in value if not (isinstance(v, str) and v.startswith("$"))]
    if isinstance(value, str) and value.startswith("$") and value[1:2].isalpha():
        return None
    return value


def trace(details: dict[str, Any], instances: list[tuple[str, int | None, bool]]) -> tuple[dict[str, Any], list[str]]:
    """The sub-agent's trace from `get_line_details`' output: no money, the instances by name with their page, and
    each text beside the component as `S1…`. Returns it and the span names."""
    out = scrub(details)
    texts = list((details.get("drawing_content") or {}).get("text_beside_it") or [])
    spans = [f"S{n}" for n in range(1, len(texts) + 1)]
    content = dict(out.get("drawing_content") or {})
    content["text_beside_it"] = [{"span": s, "text": t} for s, t in zip(spans, texts, strict=True)]
    out["drawing_content"] = content
    out["instances"] = [{"instance": name, "page_no": page, "in_image": shown} for name, page, shown in instances]
    return out, spans


def filled_in(details: dict[str, Any]) -> list[dict[str, Any]]:
    """The values that were not read from the drawing, so the coordinator says so even when the sub-agent does not
    (08 §6.4: "מבחין בין מה שנקרא לבין מה שהושלם")."""
    return [
        {"attribute": v["attribute"], "value": v["value"], "source": v["source"]}
        for v in details.get("values", [])
        if v.get("value") is not None and v.get("source") not in (*READ, "user", "missing", None)
    ]


def crop(
    session: Session, storage: Storage, tenant_id: str, items: list[Located]
) -> tuple[ImageInput | None, list[str]]:
    """The crop around the instances on the page that has most of them, and the instances in it."""
    if not items:
        return None, []
    page_id = Counter(i.page_id for i in items).most_common(1)[0][0]
    page = session.get(m.Page, page_id)
    if page is None or page.tenant_id != tenant_id or not page.render_key or not page.width_pt or not page.height_pt:
        return None, []
    here = [i for i in items if i.page_id == page_id]
    x0 = min(i.bbox[0] for i in here) - MARGIN_PT
    y0 = min(i.bbox[1] for i in here) - MARGIN_PT
    x1 = max(i.bbox[2] for i in here) + MARGIN_PT
    y1 = max(i.bbox[3] for i in here) + MARGIN_PT
    for lo, hi, limit in ((0, 2, page.width_pt), (1, 3, page.height_pt)):  # at least MIN_SIDE_PT, on the page
        box = [x0, y0, x1, y1]
        grow = max(0.0, MIN_SIDE_PT - (box[hi] - box[lo])) / 2
        box[lo], box[hi] = max(0.0, box[lo] - grow), min(float(limit), box[hi] + grow)
        x0, y0, x1, y1 = box
    try:
        render = storage.get(tenant_id, page.render_key)
    except Exception:  # a page whose render is gone: the answer goes on from the trace
        log.warning("explain_line: no render for page %s", page_id)
        return None, []
    with Image.open(io.BytesIO(render)) as img:
        scale = img.width / page.width_pt
        part = img.convert("RGB").crop((int(x0 * scale), int(y0 * scale), int(x1 * scale) + 1, int(y1 * scale) + 1))
    draw = ImageDraw.Draw(part)
    width = max(2, round(2 * scale))
    for i in here:
        a, b, c, d = i.bbox
        draw.rectangle(
            ((a - x0) * scale - 3, (b - y0) * scale - 3, (c - x0) * scale + 3, (d - y0) * scale + 3),
            outline=FRAME,
            width=width,
        )
    if max(part.size) > MAX_SIDE_PX:
        k = MAX_SIDE_PX / max(part.size)
        part = part.resize((max(1, round(part.width * k)), max(1, round(part.height * k))), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    part.save(out, "PNG", optimize=True)
    drawing = session.get(m.Drawing, page.drawing_id)
    # what the pixels are, for the cassettes: the same fixture page and box on any seed (ids differ)
    key = f"line_explanation:{drawing.trace_id if drawing else ''}:p{page.page_no}:{x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f}"
    return ImageInput(out.getvalue(), "image/png", key=key), [i.instance_id for i in here]


@dataclass
class Checked:
    answer: LineExplanation
    invalid: list[str]


def check(answer: LineExplanation, lines: set[str], instances: set[str], spans: set[str]) -> Checked:
    """Only names the sub-agent was given (08 §8.2's rule, here for its citations)."""
    invalid: list[str] = []

    def keep(names: list[str], allowed: set[str]) -> list[str]:
        out = []
        for n in names:
            n = n.strip().upper()
            if n in allowed:
                if n not in out:
                    out.append(n)
            else:
                invalid.append(n)
        return out

    cites = Cites(
        line_ids=keep(answer.cites.line_ids, lines),
        instance_ids=keep(answer.cites.instance_ids, instances),
        span_ids=keep(answer.cites.span_ids, spans),
    )
    focus = Focus(instance_ids=keep(answer.focus.instance_ids, instances))
    if invalid:
        log.info("explain_line invalid_ref %s", invalid)
    return Checked(answer.model_copy(update={"cites": cites, "focus": focus}), invalid)
