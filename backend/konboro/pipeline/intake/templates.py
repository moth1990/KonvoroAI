"""Factory template pages (01 §5.7): a page that matches a saved template is classified without a model call.

The fingerprint is an ink map: the page at 512 px, dark lines thickened a little, reduced to 64 × 64 cells, each
cell inked or blank. Two pages compare by the overlap of their inked cells (intersection over union), outside the
template's title block, which changes from project to project.

On the golden set, NEVIS-1 page 3 against NURSERY-1 page 3 (the same template) scores 0.76; NEVIS-1's template
pages score at most 0.58 against any other NURSERY-1 page. NURSERY-1 page 2 holds the same tables as NEVIS-1 page 2
in another layout (0.56), so it goes to the model, which is the safe side. The factory's technical-data form (page 1
of both) scores 0.999: a filled-in form looks like its blank. That is why only pages classified `factory_template`
become templates, never other kinds.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image, ImageFilter
from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.ids import new_id

GRID = 64
RENDER_PX = 512
INK_LEVEL = 235  # a cell is inked when its average grey is darker than this (0 black … 255 white)
MATCH = 0.70
DEFAULT_MASK = (0.0, 0.78, 1.0, 1.0)  # when the template page had no title block region: the bottom strip

Mask = tuple[float, float, float, float]  # x0, y0, x1, y1 as fractions of the page


def fingerprint(image: Image.Image) -> str:
    grey = image.convert("L")
    grey.thumbnail((RENDER_PX, RENDER_PX))
    cells = grey.filter(ImageFilter.MinFilter(3)).resize((GRID, GRID), Image.Resampling.BOX)
    bits = "".join("1" if int(v) < INK_LEVEL else "0" for v in cells.get_flattened_data())  # type: ignore[arg-type]
    return f"{int(bits, 2):0{GRID * GRID // 4}x}"


def _bits(fp: str) -> int:
    return int(fp, 16)


def _outside(mask: Mask) -> int:
    """A bitmask of the cells outside `mask`."""
    x0, y0, x1, y1 = (round(v * GRID) for v in mask)
    keep = 0
    for row in range(GRID):
        for col in range(GRID):
            if not (y0 <= row < y1 and x0 <= col < x1):
                keep |= 1 << (GRID * GRID - 1 - (row * GRID + col))
    return keep


def similarity(a: str, b: str, mask: Mask | None) -> float:
    keep = _outside(mask or DEFAULT_MASK)
    x, y = _bits(a) & keep, _bits(b) & keep
    union = (x | y).bit_count()
    return (x & y).bit_count() / union if union else 0.0


@dataclass(frozen=True)
class Template:
    id: str
    producer: str | None
    page_kind: str
    fingerprint: str
    mask: Mask | None


def best_match(fp: str, templates: Sequence[Template]) -> tuple[Template, float] | None:
    scored = [(t, similarity(fp, t.fingerprint, t.mask)) for t in templates]
    scored = [(t, s) for t, s in scored if s >= MATCH]
    return max(scored, key=lambda ts: ts[1]) if scored else None


def producer_key(designer: str | None) -> str | None:
    """Who made the drawing, normalized so the same company always gives the same key."""
    if not designer:
        return None
    return " ".join(designer.replace('"', "").replace("'", "").split()).casefold() or None


def save(
    session: Session, tenant_id: str, page_id: str, producer: str | None, fingerprint: str, mask: list[float] | None
) -> None:
    """Save a page as a template, once per fingerprint in the tenant."""
    exists = session.scalar(
        select(m.PageTemplate.id).where(
            m.PageTemplate.tenant_id == tenant_id, m.PageTemplate.fingerprint == fingerprint
        )
    )
    if exists is None:
        session.add(
            m.PageTemplate(
                id=new_id("tpl"),
                tenant_id=tenant_id,
                producer=producer,
                page_kind="factory_template",
                fingerprint=fingerprint,
                mask=mask,
                source_page_id=page_id,
            )
        )
