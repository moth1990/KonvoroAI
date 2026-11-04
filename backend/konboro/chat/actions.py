"""The chat's change types (08 §6.7) as review actions: each writes its correction event with `before.restore`, so the
review screen's undo takes it back, and asks for stages 5–7 through `review.refresh` (held back while a proposal
runs, `review.Deferred`). The types the review screen already has (quantity, delete, attribute, a price for this
quote) are its own functions; these are the ones it has no button for.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from sqlalchemy import func, select

from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.domain.pricing import rounding
from konboro.pipeline.pricing.edits import Replaced
from konboro.services import review
from konboro.services import review_picker as picker
from konboro.services.review import Ctx, Done, ReviewError

HUNDRED = Decimal(100)
MAX_DISCOUNT = Decimal(50)  # percent; a bigger customer discount is a typo until a setting says otherwise


def catalog_brand(ctx: Ctx, wanted: str) -> str | None:
    """The catalog's spelling of a brand the estimator wrote ("שניידר" is not a brand name; "schneider" is)."""
    w = wanted.strip().casefold()
    brands = [b for (b,) in ctx.session.execute(select(m.CatalogItem.brand).distinct()) if b]
    exact = next((b for b in brands if b.casefold() == w), None)
    if exact:
        return exact
    # "Schneider Electric" for the catalog's "Schneider", "schneider" for "Schneider Electric"
    return next((b for b in brands if b.casefold().startswith(w) or w.startswith(b.casefold())), None)


def replace_products(ctx: Ctx, pairs: list[tuple[m.QuoteLine, Replaced]], kind: str) -> Done:
    """09 §7.3's `sku_replaced` for each line, for this quote only (08 §7.4): the product the line had becomes an
    alternative, the line is approved, stages 6 and 7 on what it touched."""
    if not pairs:
        return Done("אין שורות להחלפה", None, 0)
    rows = [r for r, _ in pairs]
    everything = [*rows, *(c for r in rows for c in review._children(ctx, r))]
    restore = review._restore_of(ctx, everything, panels=[r.panel_id for r in rows])
    group = new_id("evt")
    first: m.CorrectionEvent | None = None
    at = review.now()
    for row, rep in pairs:
        event = review._event(
            ctx,
            "sku_replaced",
            line=row,
            before={"sku": row.sku, "description": row.description, "manufacturer": row.manufacturer},
            after={**rep.as_json(), "group": group, "via": kind},
            restore=restore if first is None else None,
        )
        first = first or event
        previous = {"sku": row.sku, "manufacturer": row.manufacturer, "description": row.description}
        row.alternatives = [*(a for a in row.alternatives if a.get("sku") != rep.sku), previous]
        review._edit(row, replaced=rep.as_json(), match=None)
        row.approved_at = at
    ctx.session.flush()
    review.refresh(ctx, reprice=[review.key_of(r) for r in rows], revalidate=[r.panel_id for r in rows])
    assert first is not None  # noqa: S101
    return Done(f"הוחלפו {len(pairs)} שורות", first.id, len(pairs))


def item_for_sku(ctx: Ctx, sku: str) -> picker.Choice | None:
    """A catalog item or price-list product with exactly this SKU; the factory's product first."""
    want = sku.strip().casefold()
    found = [c for c in picker.search(ctx.session, ctx.tid, sku) if (c.sku or "").casefold() == want]
    return found[0] if found else None


def add_line(ctx: Ctx, choice: picker.Choice, qty: int, panel_id: str | None) -> Done:
    """08 §6.7 `add_line`: a manual line in the panel, priced from the list (`line_type` = `manual`)."""
    if qty < 1 or qty > 100000:
        raise ReviewError(422, "validation_error", ("qty",), "invalid")
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
        catalog_item_id=choice.catalog_item_id,
        product_id=choice.product_id,
        sku=choice.sku,
        description=choice.description,
        manufacturer=choice.manufacturer,
        qty=Decimal(qty),
        status="red",
        status_reasons=[],
        edits={"qty": str(qty)} if qty != 1 else {},
        boxes=[],
    )
    ctx.session.add(row)
    ctx.session.flush()
    restore = review._restore_of(ctx, [])
    restore["created_lines"] = [line_id]
    event = review._event(
        ctx,
        "component_marked",
        line=row,
        after={**choice.replaced().as_json(), "panel_id": panel_id, "qty": qty, "family": choice.family, "via": "chat"},
        restore=restore,
    )
    review.refresh(ctx, reprice=[review.key_of(row)], revalidate=[panel_id])
    return Done(f"נוסף: {choice.description}", event.id)


def _rounding(ctx: Ctx) -> rounding.Rounding:
    settings = ctx.session.get(m.TenantSettings, ctx.tid)
    return rounding.mode(settings.rounding if settings else None)


def price_for_margin(
    cost: Decimal, pct: Decimal, kind: Literal["markup", "margin"], mode: rounding.Rounding
) -> Decimal:
    """07 §7.3's two formulas, in code: markup on cost, or margin on the price."""
    if kind == "markup":
        raw = cost * (1 + pct / HUNDRED)
    else:
        if pct >= HUNDRED:
            raise ReviewError(422, "validation_error", ("pct",), "invalid")
        raw = cost / (1 - pct / HUNDRED)
    return rounding.round_price(raw.quantize(Decimal("0.0001"), ROUND_HALF_UP), mode)


def set_line_margin(ctx: Ctx, line_id: str, pct: Decimal, kind: Literal["markup", "margin"]) -> Done:
    """08 §6.7 `set_line_margin`: the price that gives the line this margin on its cost, for this quote only (an
    override, like 09 §7.14's "רק בהצעה הזו"). A line with no cost cannot have one."""
    row = review._line(ctx, line_id)
    if row.unit_cost is None or row.unit_cost <= 0:
        raise ReviewError(422, "validation_error", ("line_id",), "no_cost")
    if pct < 0 or pct > 1000:
        raise ReviewError(422, "validation_error", ("pct",), "invalid")
    return review.change_price(ctx, line_id, price_for_margin(row.unit_cost, pct, kind, _rounding(ctx)), "quote")


def set_discount(ctx: Ctx, pct: Decimal) -> Done:
    """08 §6.7 `set_customer_discount`: on the quote, not on line prices (07 §7.6); always this quote only (08 §7.4)."""
    if pct < 0 or pct > MAX_DISCOUNT:
        raise ReviewError(422, "validation_error", ("pct",), "invalid")
    new = (pct / HUNDRED).quantize(Decimal("0.0001")) if pct else None
    old = ctx.version.discount_pct
    if new == old:
        return Done("ההנחה לא השתנתה")
    restore = review._restore_of(ctx, [])
    restore["discount_pct"] = str(old) if old is not None else None
    event = review._event(
        ctx,
        "discount_set",
        before={"discount_pct": str(old) if old is not None else None},
        after={"discount_pct": str(new) if new is not None else None},
        restore=restore,
    )
    ctx.version.discount_pct = new
    ctx.session.flush()
    review.refresh(ctx)
    return Done("ההנחה עודכנה", event.id)
