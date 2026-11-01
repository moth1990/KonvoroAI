"""The classifier's answer, checked by code (00 §7.2, 01 §5.4).

The schema already holds the page kind to the closed list. Code then:
- turns grid boxes (0–1000 over the image) into PDF points on the upright page, and drops a box that is empty;
- keeps only title-block values that have a shape a title block can have (a date that is a real date), and turns
  blank strings into null, so a value with no evidence never passes as one (00 §5.3);
- turns the box frame when the model says the image was sideways.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from konboro.contracts.intake import PageKind, TitleBlock
from konboro_llm.stages.page_classification import ClassificationAnswer, TitleBlockAnswer

GRID = 1000.0
MIN_BOX_SHARE = 0.002  # a box smaller than this share of the grid on either side is noise


@dataclass
class FoundPanel:
    name: str | None
    bbox: tuple[float, float, float, float]  # points, top-left origin, on the upright page
    confidence: float


@dataclass
class FoundRegion:
    region_kind: str
    bbox: tuple[float, float, float, float]
    panel_ref: str | None
    confidence: float


@dataclass
class CheckedAnswer:
    page_kind: PageKind
    confidence: float
    orientation: int
    component_labels: str
    panels: list[FoundPanel] = field(default_factory=list)
    regions: list[FoundRegion] = field(default_factory=list)
    title_block: TitleBlock | None = None
    dropped: int = 0  # boxes that failed the check


def text_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def iso_date(value: str | None) -> str | None:
    """Only a real calendar date passes."""
    value = text_or_none(value)
    if value is None:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def title_block(answer: TitleBlockAnswer | None) -> TitleBlock | None:
    if answer is None:
        return None
    block = TitleBlock(
        project_name=text_or_none(answer.project_name),
        designer=text_or_none(answer.designer),
        panel_name=text_or_none(answer.panel_name),
        drawing_number=text_or_none(answer.drawing_number),
        revision=text_or_none(answer.revision),
        date=iso_date(answer.date),
        status=answer.status,
    )
    return block if any(v is not None for v in block.model_dump().values()) else None


def turned_size(size_pt: tuple[float, float], orientation: int) -> tuple[float, float]:
    w, h = size_pt
    return (h, w) if orientation in (90, 270) else (w, h)


def _box(grid_box: tuple[int, int, int, int], size_pt: tuple[float, float]) -> tuple[float, float, float, float] | None:
    x0, x1 = sorted((grid_box[0], grid_box[2]))
    y0, y1 = sorted((grid_box[1], grid_box[3]))
    if x1 - x0 < MIN_BOX_SHARE * GRID or y1 - y0 < MIN_BOX_SHARE * GRID:
        return None
    w, h = size_pt
    return (round(x0 * w / GRID, 1), round(y0 * h / GRID, 1), round(x1 * w / GRID, 1), round(y1 * h / GRID, 1))


def _turn_grid(box: tuple[int, int, int, int], orientation: int) -> tuple[int, int, int, int]:
    """A box seen on the sideways image, moved to the frame of the image turned `orientation` degrees clockwise."""
    x0, y0, x1, y1 = box
    g = int(GRID)
    if orientation == 90:
        return (g - y1, x0, g - y0, x1)
    if orientation == 180:
        return (g - x1, g - y1, g - x0, g - y0)
    if orientation == 270:
        return (y0, g - x1, y1, g - x0)
    return box


def check(answer: ClassificationAnswer, size_pt: tuple[float, float]) -> CheckedAnswer:
    """`size_pt` is the page as rendered for the model; boxes come back on the page after the model's turn."""
    turn = answer.orientation
    upright = turned_size(size_pt, turn)
    out = CheckedAnswer(
        page_kind=answer.page_kind,
        confidence=answer.page_kind_confidence,
        orientation=turn,
        component_labels=answer.component_labels,
        title_block=title_block(answer.title_block),
    )
    for p in answer.panels:
        box = _box(_turn_grid(p.bbox, turn), upright)
        if box is None:
            out.dropped += 1
            continue
        out.panels.append(FoundPanel(text_or_none(p.name), box, p.confidence))
    for r in answer.regions:
        box = _box(_turn_grid(r.bbox, turn), upright)
        if box is None:
            out.dropped += 1
            continue
        out.regions.append(FoundRegion(r.region_kind, box, text_or_none(r.panel_ref), r.confidence))
    return out


def stored(panels: list[FoundPanel], regions: list[FoundRegion]) -> list[dict[str, object]]:
    """`pages.regions`: everything the classifier found on the page, panels included (01 §5.4 `region_kind`
    `panel`), whatever the page's route. A page that moves to another route later rebuilds its panels from here."""
    out: list[dict[str, object]] = [
        {"region_kind": "panel", "bbox": list(p.bbox), "panel_name": p.name, "confidence": p.confidence} for p in panels
    ]
    out += [
        {"region_kind": r.region_kind, "bbox": list(r.bbox), "panel_name": r.panel_ref, "confidence": r.confidence}
        for r in regions
    ]
    return out


def from_stored(rows: list[dict[str, Any]]) -> tuple[list[FoundPanel], list[FoundRegion]]:
    panels, regions = [], []
    for r in rows:
        box = tuple(float(v) for v in r["bbox"])
        confidence = float(r.get("confidence") or 1.0)
        if r["region_kind"] == "panel":
            panels.append(FoundPanel(r.get("panel_name"), box, confidence))  # type: ignore[arg-type]
        else:
            regions.append(FoundRegion(r["region_kind"], box, r.get("panel_name"), confidence))  # type: ignore[arg-type]
    return panels, regions
