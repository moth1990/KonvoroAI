"""The review screen's product picker and the actions that use it (09 §6.4, §6.6, §7.4, §7.8, §7.13; S23b).

- **Search** (`search`): the master catalog and the factory's own products together, by description, SKU and maker,
  filtered to a family when the line has one. Priced products come first, each with the factory's price or none
  (S23b decision 2). Code only: no model sees the query or a price.
- **An attribute** (`set_attribute`, 09 §7.4): current or breaking capacity, set by the user. Stage 5 runs again for
  the line's component in code, with the same brand and the reading's confidence penalty removed, and never asks the
  model (S23b decision 3): when the rules leave several candidates, the first is taken, yellow, and the others become
  alternatives. Then stages 6 and 7. The edit is for the one line (S23b decision 4).
- **A missing line** (`candidates`, `resolve_missing`, 09 §7.8): up to three products by what was read beside it, from
  the same code; or one picked in the search. The line becomes an approved component line, its values from the drawing
  kept. "אין כאן רכיב" is `review.delete`.
- **A missed component** (`mark_component`, 09 §6.6): a rectangle on a page and a product. A manual line with the
  rectangle as its box, in the panel whose area on the page holds the rectangle's centre, else the active one; the
  rectangle's crop is kept as a detector example (03 §11) in the family's default class (S23b decision 5).
- **A brand discount from a row** (`set_brand_discount`, 09 §7.13): saved as the factory's brand discount (07 §7.2
  priority 2), and this quote's lines of the brand with no price of their own are priced by it. Other drafts don't
  change by themselves (07 §7.2.3).

Each action keeps what undo needs in its correction event, as S23's do (`review.undo`).
"""

import io
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from PIL import Image
from sqlalchemy import func, select

from konboro.contracts.matching import ComponentMatch
from konboro.contracts.merge import AttributeValue, Component, MissingInstance
from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.pipeline.association import schemas
from konboro.pipeline.audit.differences import describe
from konboro.pipeline.bom.terms import UNTYPED
from konboro.pipeline.detection.library import FAMILIES
from konboro.pipeline.matching import catalog, factory, match, notes
from konboro.pipeline.pricing import load as pricing_load
from konboro.pipeline.pricing.edits import Rematch, Replaced
from konboro.pipeline.pricing.lines import alternative, confidence_reason, match_reasons, values_of
from konboro.services import price_list as pl
from konboro.services.review import (
    Ctx,
    Done,
    ReviewError,
    _children,
    _edit,
    _event,
    _json,
    _line,
    _restore_of,
    key_of,
    now,
    refresh,
)
from konboro.services.storage import drawing_key

EDITABLE = ("current_a", "breaking_capacity_ka")  # 09 §6.4: current and breaking capacity, from a list
LIMITS = {"current_a": Decimal(6300), "breaking_capacity_ka": Decimal(200)}
# The S09 review fixture keeps the prototype's keys and texts ("current": "160A"); the schema's are stage 4's.
FIXTURE_KEYS = {
    "current": "current_a",
    "poles": "poles",
    "curve": "curve",
    "breaking_capacity_ka": "breaking_capacity_ka",
}
READ_SOURCES = ("drawing", "cad_attrib", "graphic", "shared_label", "bom", "user")
NUMBER = re.compile(r"(\d+(?:\.\d+)?)")
MIN_MARK_PT = 10  # 09 §6.6: a smaller rectangle is not a mark
SEARCH_LIMIT = 30
CANDIDATES = 3


def _number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


# --- what the picker lists -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Choice:
    """One product the picker offers: a catalog item (`cat:`) or a price-list product (`prd:`)."""

    ref: str
    description: str
    sku: str | None
    manufacturer: str | None
    family: str | None
    catalog_item_id: str | None
    product_id: str | None
    unit_price: Decimal | None  # the factory's sale price today; None: "אין מחיר"

    def replaced(self) -> Replaced:
        return Replaced(self.sku, self.manufacturer, self.description, self.catalog_item_id, self.product_id)


def _products(session: Any, tenant_id: str, family: str | None) -> list[pl.ProductView]:
    return pl.list_products(session, tenant_id, family=family)


def _choice_of_product(p: pl.ProductView) -> Choice:
    return Choice(
        ref=f"prd:{p.id}",
        description=p.display_name,
        sku=p.manufacturer_sku,
        manufacturer=p.brand,
        family=p.family,
        catalog_item_id=p.catalog_item_id,
        product_id=p.id,
        unit_price=p.unit_price,
    )


def _choice_of_item(item: m.CatalogItem, product: pl.ProductView | None) -> Choice:
    """A catalog item, with the price of the factory's product for it when there is one."""
    return Choice(
        ref=f"prd:{product.id}" if product else f"cat:{item.id}",
        description=pricing_load.describe(item),
        sku=item.sku,
        manufacturer=item.brand,
        family=item.family,
        catalog_item_id=item.id,
        product_id=product.id if product else None,
        unit_price=product.unit_price if product else None,
    )


def _words(q: str) -> list[str]:
    return [w.casefold() for w in q.split() if w.strip()]


def _hits(words: Sequence[str], *texts: str | None) -> bool:
    hay = " ".join(t for t in texts if t).casefold()
    compact = hay.replace(" ", "")
    return all(w in hay or w.replace(" ", "") in compact for w in words)


def search(session: Any, tenant_id: str, q: str | None, family: str | None = None) -> list[Choice]:
    """09 §6.6 step 3, §6.4 "מוצר אחר…": every word in the description, SKU, maker or series. A catalog item the
    factory has a product for is listed once, with the product's price."""
    words = _words(q or "")
    products = _products(session, tenant_id, family)
    by_item = {p.catalog_item_id: p for p in products if p.catalog_item_id}
    items_q = select(m.CatalogItem).where(m.CatalogItem.status == "active")
    if family:
        items_q = items_q.where(m.CatalogItem.family == family)
    out: list[Choice] = []
    for item in session.scalars(items_q.order_by(m.CatalogItem.brand, m.CatalogItem.sku)):
        text = pricing_load.describe(item)
        if _hits(words, text, item.sku, item.brand, item.series, item.model_code):
            out.append(_choice_of_item(item, by_item.get(item.id)))
    for p in products:
        if p.catalog_item_id:
            continue  # listed with its catalog item
        if _hits(words, p.display_name, p.manufacturer_sku, p.brand):
            out.append(_choice_of_product(p))
    out.sort(key=lambda c: (c.unit_price is None, c.description.casefold(), c.ref))
    return out[:SEARCH_LIMIT]


def choice(session: Any, tenant_id: str, ref: str) -> Choice:
    """The product a ref names, for an action: 422 when it names nothing the tenant can pick."""
    kind, _, ident = ref.partition(":")
    if kind == "cat":
        item = session.get(m.CatalogItem, ident)
        if item is not None:
            product = next(
                (p for p in _products(session, tenant_id, item.family) if p.catalog_item_id == item.id), None
            )
            return _choice_of_item(item, product)
    if kind == "prd":
        row = session.get(m.Product, ident)
        if row is not None and row.tenant_id == tenant_id:
            view = pl.get_product(session, tenant_id, ident)
            return _choice_of_product(view)
    raise ReviewError(422, "validation_error", ("ref",), "unknown_product")


# --- stage 5 again, in code (05, S23b decision 3) ------------------------------------------------------------------


def _inputs(ctx: Ctx, components: Iterable[Component]) -> match.Inputs:
    cat = catalog.load(ctx.session)
    out = ctx.outputs()
    return match.Inputs(
        catalog=cat,
        factory=factory.load(ctx.session, ctx.tid, cat, ctx.quote.customer_id),
        schemas=schemas.load(ctx.session),
        notes=notes.read(out.intake.context_artifacts if out else []),
        components={c.component_id: c for c in components},
        ask=None,  # no model from a review route: the rules' first candidate, yellow (match._ambiguous)
    )


def _fixture_value(name: str, value: Any) -> Any:
    """The fixture's "160A" or "6kA" as stage 4 writes it (160, 6); poles and curve as they are."""
    if name in ("current_a", "breaking_capacity_ka") and isinstance(value, str):
        found = NUMBER.search(value)
        return _number(Decimal(found.group(1))) if found else None
    if name == "poles" and isinstance(value, str) and value.isdigit():
        return int(value)
    return value


def component_of(ctx: Ctx, row: m.QuoteLine) -> Component | None:
    """The line's component as stage 4 wrote it; for a quote with no stage outputs (the fixture), from its row."""
    out = ctx.outputs()
    if out is not None and row.component_id:
        found = next((c for c in out.merge.components if c.component_id == row.component_id), None)
        if found is not None:
            return found
    cmp = ctx.session.get(m.Component, row.component_id) if row.component_id else None
    if cmp is None or cmp.tenant_id != ctx.tid:
        return None
    attrs: dict[str, AttributeValue] = {}
    for key, a in (cmp.attributes or {}).items():
        name = FIXTURE_KEYS.get(key, key)
        source = a.get("source") if a.get("source") in READ_SOURCES else "drawing"
        value = _fixture_value(name, a.get("value"))
        attrs[name] = AttributeValue.model_construct(value=value, source=source, confidence=a.get("confidence"))
    return Component.model_construct(
        component_id=cmp.id,
        drawing_id=cmp.drawing_id,
        panel_id=cmp.panel_id or "",
        family=cmp.family,
        symbol_class=UNTYPED,
        attributes=attrs,
        explicit_texts=[str(t) for t in cmp.explicit_texts],
        brand_hint=cmp.brand_hint,
        quantity=int(cmp.quantity),
        designators=list(cmp.designators),
        parent_designators=[],
        circuit_context=None,
        multiplicity_inherited=False,
        supply_scope=cmp.supply_scope,
        source_det_ids=[],
        instance_ids=[],
        confidence=cmp.confidence if cmp.confidence is not None else 1.0,
        status="accepted",
    )


def _match_one(ctx: Ctx, component: Component) -> tuple[ComponentMatch, match.Inputs]:
    out = ctx.outputs()
    others = list(out.merge.components) if out else []
    inp = _inputs(ctx, [*others, component])
    pr = match.prepare(component, inp, {}, {})
    return match.finish(component, match.decide_prepared(pr, inp), inp.cfg), inp


def rematch(ctx: Ctx, row: m.QuoteLine, values: dict[str, Any]) -> Rematch:
    """09 §7.4: the component with the user's values (`user`), the reading's confidence penalty removed, the line's
    brand asked for; what stage 5 then chooses for it, and the reasons it gives the line."""
    component = component_of(ctx, row)
    if component is None:
        raise ReviewError(422, "validation_error", ("line_id",), "no_component")
    attrs = dict(component.attributes)
    for name, value in values.items():
        attrs[name] = AttributeValue(value=value, source="user", confidence=1.0)
    component = component.model_copy(
        update={"attributes": attrs, "confidence": 1.0, "brand_hint": row.manufacturer or component.brand_hint}
    )
    x, inp = _match_one(ctx, component)
    if x.chosen_sku is None:
        reasons = [{"source": "match", "value": "not_in_catalog", "status": "red"}]
    else:
        reasons = [confidence_reason(x.confidence), *match_reasons(x)]
    item = x.catalog_item
    return Rematch(
        sku=x.chosen_sku,
        manufacturer=item.manufacturer if item else None,
        description=item.description
        if item
        else describe(component.family, component.symbol_class, values_of(component)),
        catalog_item_id=match.item_of(x, inp.catalog),
        reasons=tuple(reasons),
        alternatives=tuple(alternative(a) for a in x.alternatives),
        explanation=x.reason or None,
    )


def attribute_options(session: Any, families: Iterable[str]) -> dict[str, dict[str, list[str]]]:
    """The dropdown's values (09 §6.4): what the catalog has for each family, smallest first."""
    out: dict[str, dict[str, list[str]]] = {}
    wanted = sorted(set(families))
    if not wanted:
        return out
    for name in EDITABLE:
        value = m.CatalogItem.attributes[name].astext
        rows = session.execute(
            select(m.CatalogItem.family, value)
            .where(m.CatalogItem.family.in_(wanted), value.is_not(None), m.CatalogItem.status == "active")
            .group_by(m.CatalogItem.family, value)
        )
        for family, v in rows:
            try:
                number = Decimal(str(v))
            except ArithmeticError:
                continue
            out.setdefault(family, {}).setdefault(name, []).append(format(number.normalize(), "f"))
    for by_name in out.values():
        for name, values in by_name.items():
            by_name[name] = sorted(set(values), key=Decimal)
    return out


def set_attribute(ctx: Ctx, line_id: str, name: str, value: Decimal) -> Done:
    """09 §7.4: the value is the user's; stage 5 for the line, then the rules on its panel, then stage 7."""
    row = _line(ctx, line_id)
    if row.line_type != "component" or row.parent_line_id or not row.component_id:
        raise ReviewError(422, "validation_error", ("line_id",), "not_editable")
    if name not in EDITABLE:
        raise ReviewError(422, "validation_error", ("attribute",), "not_editable")
    if value <= 0 or value > LIMITS[name] or value.as_tuple().exponent < -1:  # type: ignore[operator]
        raise ReviewError(422, "validation_error", ("value",), "invalid")
    component = component_of(ctx, row)
    if component is None:
        raise ReviewError(422, "validation_error", ("line_id",), "no_component")
    edits = dict(row.edits or {})
    values = {**(edits.get("attrs") or {}), name: _number(value)}
    was = component.attributes.get(name)
    if (edits.get("attrs") or {}).get(name) == values[name]:
        return Done("הערך לא השתנה")
    rem = rematch(ctx, row, values)
    restore = _restore_of(ctx, [row, *_children(ctx, row)], panels=[row.panel_id])
    event = _event(
        ctx,
        "attribute_changed",
        line=row,
        before={
            name: (edits.get("attrs") or {}).get(name, was.value if was else None),
            "source": "user" if name in (edits.get("attrs") or {}) else (was.source if was else None),
            "confidence": was.confidence if was else None,
            "sku": row.sku,
        },
        after={name: values[name], "source": "user", "sku": rem.sku, "description": rem.description},
        restore=restore,
    )
    _edit(row, attrs=values, match=rem.as_json(), replaced=None)
    ctx.session.flush()
    refresh(ctx, reprice=[key_of(row)], revalidate=[row.panel_id])
    if rem.sku is None:
        return Done("אין בקטלוג מוצר עם הערכים האלה", event.id)
    return Done(f"הותאם מחדש: {rem.description}", event.id)


# --- a missing line (09 §7.8) ---------------------------------------------------------------------------------------


def _missing_of(ctx: Ctx, row: m.QuoteLine) -> MissingInstance | None:
    out = ctx.outputs()
    if out is None or not (row.line_key or "").startswith("m:"):
        return None
    instance_id = (row.line_key or "")[2:]
    return next((x for x in out.merge.missing if x.instance_id == instance_id), None)


def candidates(ctx: Ctx, line_id: str) -> list[Choice]:
    """09 §6.4: up to three products by what was read beside the missing symbol, from stage 5's code; none for a quote
    with no stage outputs (the picker's search is still there)."""
    row = _line(ctx, line_id)
    if row.line_type != "missing":
        raise ReviewError(422, "validation_error", ("line_id",), "not_missing")
    x = _missing_of(ctx, row)
    if x is None:
        return []
    component = Component.model_construct(
        component_id=f"cmp_{x.instance_id[4:]}",
        drawing_id=ctx.quote.drawing_id or "",
        panel_id=x.panel_id or "",
        family=x.family,
        symbol_class=UNTYPED,
        attributes=dict(x.attributes),
        explicit_texts=[],
        brand_hint=None,
        quantity=1,
        designators=[],
        parent_designators=[],
        circuit_context=None,
        multiplicity_inherited=False,
        supply_scope="in_panel",
        source_det_ids=[],
        instance_ids=[x.instance_id],
        confidence=1.0,
        status="accepted",
    )
    found, inp = _match_one(ctx, component)
    wanted: list[tuple[str, str]] = []
    if found.catalog_item is not None and found.chosen_sku:
        wanted.append((found.catalog_item.manufacturer or "", found.chosen_sku))
    wanted += [(a.manufacturer or "", a.sku) for a in found.alternatives if a.sku]
    products = _products(ctx.session, ctx.tid, x.family)
    by_item = {p.catalog_item_id: p for p in products if p.catalog_item_id}
    out: list[Choice] = []
    for brand, sku in wanted:
        item = next((i for i in inp.catalog.by_sku.get(catalog.norm_sku(sku), []) if i.brand == brand), None)
        row_ = ctx.session.get(m.CatalogItem, item.id) if item else None
        if row_ is not None and all(c.catalog_item_id != row_.id for c in out):
            out.append(_choice_of_item(row_, by_item.get(row_.id)))
        if len(out) == CANDIDATES:
            break
    return out


def resolve_missing(ctx: Ctx, line_id: str, ref: str) -> Done:
    """09 §7.8: the product picked; the line becomes an approved component line, its values from the drawing kept.
    `missing_resolved` is a positive example for the detector (03 §11)."""
    row = _line(ctx, line_id)
    if row.line_type != "missing":
        raise ReviewError(422, "validation_error", ("line_id",), "not_missing")
    picked = choice(ctx.session, ctx.tid, ref)
    rep = picked.replaced()
    restore = _restore_of(ctx, [row], panels=[row.panel_id])
    event = _event(
        ctx,
        "missing_resolved",
        line=row,
        before={"line_type": "missing", "explanation": row.explanation, "boxes": row.boxes},
        after={**rep.as_json(), "family": picked.family, "positive_example": True},
        restore=restore,
    )
    _edit(row, replaced=rep.as_json(), resolved=True)
    row.approved_at = now()
    ctx.session.flush()
    refresh(ctx, reprice=[key_of(row)], revalidate=[row.panel_id])
    return Done(f"נוסף: {picked.description}", event.id)


# --- a missed component (09 §6.6) -----------------------------------------------------------------------------------


def default_class(family: str | None) -> str | None:
    """S23b decision 5: the symbol library's first class for the family."""
    return next((f.classes[0][0] for f in FAMILIES if f.family == family and f.classes), None)


def _inside(point: tuple[float, float], box: Sequence[float]) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def panel_at(panels: Sequence[m.Panel], page_id: str, bbox: Sequence[float], active: str | None) -> str | None:
    """09 §6.6 step 5: the panel whose area on the page holds the rectangle's centre; else the active panel, else the
    page's only panel."""
    centre = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
    on_page = [p for p in panels if page_id in (p.page_ids or [])]
    for p in on_page:
        boxes = (p.bboxes or {}).get(page_id) or []
        if boxes and isinstance(boxes[0], int | float):
            boxes = [boxes]
        if any(_inside(centre, b) for b in boxes):
            return p.id
    ids = {p.id for p in panels}
    if active in ids:
        return active
    return on_page[0].id if len(on_page) == 1 else (panels[0].id if panels else None)


def crop_png(render: bytes, page_width_pt: float, bbox: Sequence[float]) -> bytes:
    """The rectangle cut from the page's render (00 §6.2: PDF points, origin top left), with a little margin."""
    with Image.open(io.BytesIO(render)) as img:
        scale = img.width / page_width_pt
        pad = 4
        box = (
            max(0, int((bbox[0] - pad) * scale)),
            max(0, int((bbox[1] - pad) * scale)),
            min(img.width, int((bbox[2] + pad) * scale) + 1),
            min(img.height, int((bbox[3] + pad) * scale) + 1),
        )
        out = io.BytesIO()
        img.crop(box).save(out, "PNG")
        return out.getvalue()


def mark_component(ctx: Ctx, page_id: str, bbox: Sequence[float], ref: str, active_panel_id: str | None = None) -> Done:
    """09 §6.6: a manual line with an instance at the rectangle; the crop is a detector example (03 §11)."""
    if ctx.quote.drawing_id is None:
        raise ReviewError(422, "validation_error", ("page_id",), "no_drawing")
    page = ctx.session.get(m.Page, page_id)
    if page is None or page.tenant_id != ctx.tid or page.drawing_id != ctx.quote.drawing_id:
        raise ReviewError(404, "not_found")
    if page.route != "process" or not page.render_key or not page.width_pt or not page.height_pt:
        raise ReviewError(422, "validation_error", ("page_id",), "not_parsed")
    x0, y0, x1, y1 = (float(v) for v in bbox)
    if not (0 <= x0 < x1 <= page.width_pt + 0.5 and 0 <= y0 < y1 <= page.height_pt + 0.5):
        raise ReviewError(422, "validation_error", ("bbox",), "outside_page")
    if x1 - x0 < MIN_MARK_PT or y1 - y0 < MIN_MARK_PT:
        raise ReviewError(422, "validation_error", ("bbox",), "too_small")
    box = [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)]
    picked = choice(ctx.session, ctx.tid, ref)
    panels = list(
        ctx.session.scalars(
            select(m.Panel).where(m.Panel.tenant_id == ctx.tid, m.Panel.drawing_id == ctx.quote.drawing_id)
        )
    )
    panel_id = panel_at(panels, page_id, box, active_panel_id)
    position = ctx.session.scalar(
        select(func.max(m.QuoteLine.position)).where(
            m.QuoteLine.tenant_id == ctx.tid, m.QuoteLine.quote_version_id == ctx.version.id
        )
    )
    line_id = new_id("ln")
    row = m.QuoteLine(
        id=line_id,
        tenant_id=ctx.tid,
        quote_version_id=ctx.version.id,
        panel_id=panel_id,
        position=(position or 0) + 1,
        line_key=f"u:{line_id}",
        line_group="outputs",
        line_type="manual",
        catalog_item_id=picked.catalog_item_id,
        product_id=picked.product_id,
        sku=picked.sku,
        description=picked.description,
        manufacturer=picked.manufacturer,
        qty=Decimal(1),
        status="red",
        status_reasons=[],
        boxes=[{"page_id": page_id, "bbox": box}],
    )
    ctx.session.add(row)
    ctx.session.flush()
    crop: dict[str, Any] | None = None
    cls = default_class(picked.family)
    if cls is not None and ctx.session.get(m.SymbolClass, cls) is not None:
        crop_id = new_id("trf")
        image_key = drawing_key(ctx.tid, ctx.quote.drawing_id, "marks", f"{crop_id}.png")
        ctx.storage.put(
            ctx.tid,
            image_key,
            crop_png(ctx.storage.get(ctx.tid, page.render_key), page.width_pt, box),
            "image/png",
        )
        ctx.session.add(
            m.TenantReferenceCrop(
                id=crop_id,
                tenant_id=ctx.tid,
                symbol_class=cls,
                scope="drawing",
                drawing_id=ctx.quote.drawing_id,
                image_key=image_key,
                source="user_correction",
            )
        )
        ctx.session.flush()
        crop = {"id": crop_id, "image_key": image_key}
    restore = _restore_of(ctx, [])
    restore["created_lines"] = [line_id]
    if crop:
        restore["crop"] = crop
    event = _event(
        ctx,
        "component_marked",
        line=row,
        after={
            "page_id": page_id,
            "bbox": box,
            "panel_id": panel_id,
            **picked.replaced().as_json(),
            "family": picked.family,
            "symbol_class": cls,
            "crop_id": crop["id"] if crop else None,
        },
        restore=restore,
    )
    refresh(ctx, reprice=[key_of(row)], revalidate=[panel_id])
    return Done(f"נוסף ידנית: {picked.description}", event.id)


def undo_created(ctx: Ctx, restore: dict[str, Any]) -> None:
    """`review.undo` for a mark: the line it added leaves the quote, and the detector example goes with its crop."""
    at = now()
    for line_id in restore.get("created_lines", []):
        row = ctx.session.get(m.QuoteLine, line_id)
        if row is not None and row.tenant_id == ctx.tid and row.quote_version_id == ctx.version.id:
            row.deleted_at = at
    crop = restore.get("crop")
    if crop:
        found = ctx.session.get(m.TenantReferenceCrop, crop["id"])
        if found is not None and found.tenant_id == ctx.tid:
            ctx.session.delete(found)
        ctx.storage.delete(ctx.tid, crop["image_key"])
    ctx.session.flush()


# --- a brand discount from a row (09 §7.13) -------------------------------------------------------------------------


def _no_price_of_its_own(r: m.QuoteLine) -> bool:
    """A line a brand discount may price: no price, or one from a discount already; never one the user set."""
    return (
        not r.override
        and r.line_type in ("component", "manual")
        and r.price_status in (None, "missing", "discount_based")
    )


def set_brand_discount(ctx: Ctx, line_id: str, pct: Decimal) -> Done:
    """ "כל המוצרים של X: מחירון יצרן פחות __%": the factory's brand discount, and this quote's lines of the brand with
    no price of their own priced by it, yellow ("מחיר לפי הנחת מותג", 07 §7.5)."""
    row = _line(ctx, line_id)
    item = ctx.session.get(m.CatalogItem, row.catalog_item_id) if row.catalog_item_id else None
    if item is None or item.list_price is None:
        raise ReviewError(422, "validation_error", ("line_id",), "no_list_price")
    brand = item.brand
    targets = [
        r for r in ctx.lines() if (r.manufacturer or "").casefold() == brand.casefold() and _no_price_of_its_own(r)
    ]
    old = ctx.session.get(m.BrandDiscount, (ctx.tid, brand))
    restore = _restore_of(ctx, targets)
    restore["brand_discount"] = {"brand": brand, "pct": _json(old.discount_pct) if old else None}
    actor = pl.Actor(ctx.tid, ctx.actor.user_id)
    pl.set_brand_discount(ctx.session, actor, brand, pct, quote_id=ctx.quote.id)
    event = _event(
        ctx,
        "brand_discount_set",
        line=row,
        before={"brand": brand, "discount_pct": _json(old.discount_pct) if old else None},
        after={"brand": brand, "discount_pct": str(pct), "line_ids": [r.id for r in targets]},
        restore=restore,
    )
    refresh(ctx, reprice=[key_of(r) for r in targets])
    priced = sum(1 for r in ctx.lines() if r.id in {t.id for t in targets} and r.unit_price is not None)
    pct_text = format((pct * 100).normalize(), "f")
    if priced == 1:
        return Done(f"שורה אחת קיבלה מחיר: מחירון {brand} פחות {pct_text}%", event.id, 1)
    return Done(f"{priced} שורות קיבלו מחיר: מחירון {brand} פחות {pct_text}%", event.id, priced)


def undo_brand_discount(ctx: Ctx, state: dict[str, Any]) -> None:
    actor = pl.Actor(ctx.tid, ctx.actor.user_id)
    if state.get("pct") is None:
        if ctx.session.get(m.BrandDiscount, (ctx.tid, state["brand"])) is not None:
            pl.delete_brand_discount(ctx.session, actor, state["brand"])
    else:
        pl.set_brand_discount(ctx.session, actor, state["brand"], Decimal(state["pct"]), quote_id=ctx.quote.id)
