"""What the drawing shows that the system did not read, or read only in part (13 §4.4, prototype `UNRESOLVED` and
`boxesFor`): the review screen's "לא פוענח" layer, behind `unresolved_overlay`.

Four kinds, each with its box on its page (PDF points, origin top left, 00 §6.2), read in code from what stages 3–6
and the quote already hold:
- `unknown_symbol`: a stage-3 detection with status `unknown` (03 §4.4, §6) that stage 4 made no instance of, unless
  a component marked in draw mode covers it (09 §6.6).
- `orphan_text`: a stage-3 orphan text (03 §3.6) that no stage-4 instance read. Stage 3 keeps as orphans only the
  spans stage 2 tagged as a device's value ("C16", "30mA", "3X25A"), so wire and terminal numbers never reach the
  layer (S26 decision 4). One that became a missing line is the line's, not the layer's.
- `partial`: one box per drawn instance of a live, unapproved component line whose product is not identified: stage 5
  found none, several or a conflict and the user chose none, or its current or poles were not read from the drawing
  (missing, or inferred from the circuit). A missing price or a filled-in kA is not a reading problem (S26
  decision 7).
- `front_only`: an open `FRONT_VIEW_DESIGNATOR_MISSING` finding (06, S21 decision 11) with its box.

A spot that the user resolves (an approval, a chosen product, a dismissed finding, a marked component) drops off the
next read.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.contracts.detection import DetectionResult
from konboro.contracts.matching import ComponentMatch, MatchingResult
from konboro.contracts.merge import MergeResult
from konboro.db import models as m
from konboro.pipeline.association.schemas import NEVER_DEFAULT
from konboro.pipeline.association.schemas import load as load_schemas
from konboro.pipeline.validation.model import compress
from konboro.services import quotes as qs
from konboro.services.storage import Storage

UNKNOWN_SYMBOL, ORPHAN_TEXT, PARTIAL, FRONT_ONLY = "unknown_symbol", "orphan_text", "partial", "front_only"
KINDS = (UNKNOWN_SYMBOL, FRONT_ONLY, ORPHAN_TEXT, PARTIAL)  # the more specific first, for `one_per_place`
FRONT_VIEW_MISSING = "FRONT_VIEW_DESIGNATOR_MISSING"

# 07 §7.5's match reasons that leave the product unknown; `model_not_written` is the review fixture's (S09)
NOT_IDENTIFIED = {
    "unmatched": "אין דגם",
    "model_not_written": "אין דגם",
    "ambiguous": "כמה מוצרים מתאימים",
    "conflict": "ערכים סותרים",
}
NOT_READ = {"current_a": "הזרם לא כתוב", "poles": "מספר הקטבים לא כתוב"}
# 05's sources that are not a reading of this drawing: inferred from the circuit, or a default (never for current
# and poles, 05 §4.4, so one here is a bug upstream and still not a reading)
UNREAD_SOURCES = {"inferred", "tenant_default", "system_default"}
COVERED_SHARE = 0.5  # a marked component's box covering this share of an unknown symbol resolves it


@dataclass(frozen=True)
class Spot:
    kind: str
    page_id: str
    bbox: list[float]
    note: str  # the box's tooltip, as the prototype's `title`
    line_id: str | None = None
    finding_id: str | None = None


def read_spots(session: Session, storage: Storage, tenant_id: str, quote_id: str) -> list[Spot] | None:
    """The current version's spots in page order, or None when the tenant has no such quote (the API's 404)."""
    row = session.execute(
        select(m.Quote, m.QuoteVersion)
        .join(
            m.QuoteVersion,
            (m.QuoteVersion.tenant_id == m.Quote.tenant_id)
            & (m.QuoteVersion.quote_id == m.Quote.id)
            & (m.QuoteVersion.version == m.Quote.current_version),
        )
        .where(m.Quote.tenant_id == tenant_id, m.Quote.id == quote_id)
    ).first()
    if row is None:
        return None
    quote, version = row
    if not quote.drawing_id:
        return []
    outputs = _outputs(session, storage, tenant_id, quote.drawing_id)
    detections: DetectionResult | None = outputs.get(3)
    merge: MergeResult | None = outputs.get(4)
    matching: MatchingResult | None = outputs.get(5)
    lines = qs.live_lines(session, version)

    spots = (
        _unknown_symbols(detections, merge, lines)
        + _orphan_texts(detections, merge)
        + _partial(session, tenant_id, lines, matching)
        + _front_only(session, version)
    )
    page_no = dict(
        session.execute(
            select(m.Page.id, m.Page.page_no).where(
                m.Page.tenant_id == tenant_id, m.Page.drawing_id == quote.drawing_id
            )
        ).all()
    )
    return sorted(
        one_per_place([s for s in spots if s.page_id in page_no]),
        key=lambda s: (page_no[s.page_id], s.bbox[1], s.bbox[0]),
    )


STAGE_MODELS: dict[int, type[Any]] = {3: DetectionResult, 4: MergeResult, 5: MatchingResult}


def _outputs(session: Session, storage: Storage, tenant_id: str, drawing_id: str) -> dict[int, Any]:
    """Stages 3–5 as they last wrote them; a stage with no output is left out (the review fixture has stage 3 only)."""
    keys = session.execute(
        select(m.StageRun.stage, m.StageRun.output_key).where(
            m.StageRun.tenant_id == tenant_id,
            m.StageRun.drawing_id == drawing_id,
            m.StageRun.stage.in_(tuple(STAGE_MODELS)),
            m.StageRun.output_key.is_not(None),
        )
    ).all()
    return {stage: STAGE_MODELS[stage].model_validate_json(storage.get(tenant_id, str(key))) for stage, key in keys}


# --- the four kinds -------------------------------------------------------------------------------------------------


def _unknown_symbols(
    detections: DetectionResult | None, merge: MergeResult | None, lines: list[m.QuoteLine]
) -> list[Spot]:
    if detections is None:
        return []
    made = {i.det_id for i in merge.instances} if merge else set()
    marked = [b for ln in lines if ln.line_type == "manual" for b in ln.boxes if b.get("bbox")]
    out = []
    for page in detections.pages:
        for d in page.detections:
            if d.status != "unknown" or d.det_id in made:
                continue
            box = list(d.bbox)
            if any(b["page_id"] == d.page_id and covered(box, b["bbox"]) for b in marked):
                continue
            note = "סימן שלא זיהינו. לא בספריית הסימנים"
            out.append(Spot(UNKNOWN_SYMBOL, d.page_id, box, f"{d.designator}: {note}" if d.designator else note))
    return out


def _orphan_texts(detections: DetectionResult | None, merge: MergeResult | None) -> list[Spot]:
    if detections is None:
        return []
    read = {s for i in (merge.instances if merge else []) for a in i.attributes.values() for s in a.span_ids}
    missing = [(x.page_id, list(x.bbox)) for x in (merge.missing if merge else [])]
    out = []
    for page in detections.pages:
        for o in page.orphan_texts:
            box = list(o.bbox)
            if o.span_id in read or any(p == page.page_id and covered(box, b) for p, b in missing):
                continue
            out.append(Spot(ORPHAN_TEXT, page.page_id, box, f'"{o.text}": ערך חשמלי שלא שויך לאף רכיב'))
    return out


def _partial(session: Session, tenant_id: str, lines: list[m.QuoteLine], matching: MatchingResult | None) -> list[Spot]:
    settings = session.get(m.TenantSettings, tenant_id)
    auxiliary = set(settings.auxiliary_families) if settings else set()
    candidates = [
        ln
        for ln in lines
        if ln.line_type == "component" and ln.component_id and ln.parent_line_id is None and ln.approved_at is None
    ]
    components = {
        c.id: c
        for c in session.scalars(
            select(m.Component).where(
                m.Component.tenant_id == tenant_id, m.Component.id.in_({ln.component_id for ln in candidates})
            )
        )
    }
    matches = {x.component_id: x for x in matching.matches} if matching else {}
    schemas = load_schemas(session) if matching else None
    out = []
    for ln in candidates:
        c = components.get(ln.component_id or "")
        if c is None or c.match_status == "auxiliary" or c.family in auxiliary:
            continue
        edits = ln.edits or {}
        why = [] if edits.get("replaced") or edits.get("resolved") else _not_identified(ln)
        user = edits.get("attrs") or {}
        if c.id in matches and schemas is not None:
            needed = [n for n in schemas.required(c.family) if n in NEVER_DEFAULT and n not in user]
            why += [NOT_READ[n] for n in needed if _unread(matches[c.id], n)]
        elif any(_match_value(r) == "inferred_attribute" for r in ln.status_reasons):
            why.append("הוסק מהמעגל")  # no stage-5 output (the review fixture): the line's reason says it
        if not why:
            continue
        if ln.unit_price is None:
            why.append("אין מחיר")
        who = compress(list(c.designators)) or ln.description
        note = f"{who}: {_and(why)}"
        out += [Spot(PARTIAL, i["page_id"], list(i["bbox"]), note, line_id=ln.id) for i in c.instances if i.get("bbox")]
    return out


def _front_only(session: Session, version: m.QuoteVersion) -> list[Spot]:
    rows = session.scalars(
        select(m.Finding).where(
            m.Finding.tenant_id == version.tenant_id,
            m.Finding.quote_version_id == version.id,
            m.Finding.status == "open",
            m.Finding.code == FRONT_VIEW_MISSING,
        )
    )
    return [
        Spot(FRONT_ONLY, f.page_id, list(f.bbox), f.values.get("title") or f.message, finding_id=f.id)
        for f in rows
        if f.page_id and f.bbox
    ]


# --- helpers --------------------------------------------------------------------------------------------------------


def _match_value(reason: dict[str, Any]) -> Any:
    return reason.get("value") if reason.get("source") == "match" else None


def _not_identified(ln: m.QuoteLine) -> list[str]:
    values = [_match_value(r) for r in ln.status_reasons]
    return [NOT_IDENTIFIED[v] for v in values if isinstance(v, str) and v in NOT_IDENTIFIED][:1]


def _unread(match: ComponentMatch, name: str) -> bool:
    used = match.attributes_used.get(name)
    return used is None or used.value is None or used.source in UNREAD_SOURCES


def _and(words: list[str]) -> str:
    """Hebrew's "ו" joins the last: "אין דגם ואין מחיר"."""
    unique = list(dict.fromkeys(words))
    if len(unique) == 1:
        return unique[0]
    return ", ".join(unique[:-1]) + " ו" + unique[-1]


def one_per_place(spots: list[Spot]) -> list[Spot]:
    """One box per place: a spot in the same place as one kept before it (each covers most of the other) is left
    out, in the order of `KINDS`. On a pipeline drawing an orphan text is far from every symbol by definition
    (03 §3.6), so this only keeps two labels off one box when hand-made data puts them there."""
    kept: list[Spot] = []
    for s in sorted(spots, key=lambda s: KINDS.index(s.kind)):
        if not any(k.page_id == s.page_id and covered(s.bbox, k.bbox) and covered(k.bbox, s.bbox) for k in kept):
            kept.append(s)
    return kept


def covered(box: list[float], by: list[float]) -> bool:
    """`by` covers at least `COVERED_SHARE` of `box`."""
    w = min(box[2], by[2]) - max(box[0], by[0])
    h = min(box[3], by[3]) - max(box[1], by[1])
    area = (box[2] - box[0]) * (box[3] - box[1])
    return w > 0 and h > 0 and area > 0 and w * h >= COVERED_SHARE * area
