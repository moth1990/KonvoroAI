"""The review screen's choices with `catalog_lines` on (S27b, 07 §7.1, 09 §6.4, §7.16, §7.17).

A line is one product in a panel and may hold several components. A choice of product is the components', kept on the
version by each component's line key (`quote_versions.component_edits`), not on the line: the choice moves a
component to its product's line, whose key and id are not the line it was on. Undo puts the whole map back
(`review._restore_of`). What the user does on the line itself (a quantity, a price, an approval, a delete) stays the
line's, as before.

- A nearest product, an alternative, "מוצר אחר…": for every component of the line, or for the designators picked
  (a split, 09 §7.17). They join that product's line, approved.
- "מוצר חדש": a factory product with the family's attributes and the app's name, then as above (09 §7.16).
- An attribute set by hand: stage 5 again for the line's components, in code (09 §7.4).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from konboro.db import models as m
from konboro.domain.flags import CATALOG_LINES, is_enabled
from konboro.pipeline.association import schemas as schemas_mod
from konboro.pipeline.matching import text
from konboro.pipeline.pricing.edits import Replaced
from konboro.services import flags
from konboro.services import price_list as pl

from .review import Ctx, Done, ReviewError, _event, _line, _restore_of, key_of, now, refresh

MAX_TEXT = 120


def on(ctx: Ctx) -> bool:
    return is_enabled(flags.tenant_flags(ctx.session, ctx.tid), CATALOG_LINES)


def _designators(ctx: Ctx) -> dict[str, list[str]]:
    out = ctx.outputs()
    return {c.component_id: list(c.designators) for c in out.merge.components} if out else {}


def member_keys(ctx: Ctx, row: m.QuoteLine, designators: Sequence[str] | None = None) -> list[str]:
    """The component keys a line stands for: a merged line's components (those with one of `designators`, when
    given), else the line's own key (a waiting component, a missing row)."""
    key = key_of(row)
    if not key.startswith("p:"):
        return [key]
    ids = list(row.component_ids or ([row.component_id] if row.component_id else []))
    if designators:
        tags = _designators(ctx)
        wanted = set(designators)
        ids = [c for c in ids if wanted & set(tags.get(c, []))]
        if not ids:
            raise ReviewError(422, "validation_error", ("designators",), "not_on_line")
    return [f"c:{c}" for c in ids]


def set_components(ctx: Ctx, keys: Iterable[str], **fields: Any) -> None:
    """The version's choice for each component key: what is given replaces what the key had for the same field;
    `None` removes it."""
    edits = {k: dict(v) for k, v in (ctx.version.component_edits or {}).items()}
    for k in keys:
        mine = edits.get(k, {})
        for name, value in fields.items():
            if value is None:
                mine.pop(name, None)
            else:
                mine[name] = value
        if mine:
            edits[k] = mine
        else:
            edits.pop(k, None)
    ctx.version.component_edits = edits
    ctx.session.flush()


def choose(
    ctx: Ctx,
    row: m.QuoteLine,
    replaced: Replaced,
    designators: Sequence[str] | None = None,
    event_type: str = "sku_replaced",
    after: dict[str, Any] | None = None,
    restore_extra: dict[str, Any] | None = None,
) -> Done:
    """A product for the line's components, or for the designators picked: they move to its line, approved."""
    keys = member_keys(ctx, row, designators)
    restore = _restore_of(ctx, [row], panels=[row.panel_id])
    restore.update(restore_extra or {})
    event = _event(
        ctx,
        event_type,
        line=row,
        before={"sku": row.sku, "description": row.description, "manufacturer": row.manufacturer},
        after={
            **replaced.as_json(),
            "components": keys,
            **({"designators": list(designators)} if designators else {}),
            **(after or {}),
        },
        restore=restore,
    )
    resolved = True if key_of(row).startswith("m:") else None
    set_components(
        ctx,
        keys,
        replaced=replaced.as_json(),
        match=None,
        attrs=None,
        resolved=resolved,
        approved_at=now().isoformat(),
    )
    refresh(ctx, reprice=[key_of(row)], revalidate=[row.panel_id])
    moved = len(keys)
    if designators:
        return Done(f"הועברו {moved} רכיבים ל: {replaced.description}", event.id, moved)
    return Done(f"נבחר: {replaced.description}", event.id, moved)


# --- "מוצר חדש" (09 §7.16) ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class NewProduct:
    attributes: dict[str, Any]
    brand: str
    model_code: str
    series: str | None = None
    sku: str | None = None


def _value(raw: Any) -> Any:
    """A value as stage 4 writes it (04 §6): a number when it is one, a boolean, else the text."""
    if isinstance(raw, bool | int | float):
        return raw
    s = str(raw).strip()
    if s in ("true", "false"):
        return s == "true"
    try:
        n = Decimal(s)
    except InvalidOperation:
        return s
    return int(n) if n == n.to_integral_value() else float(n)


def _text(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return format(Decimal(str(v)).normalize(), "f")
    return str(v)


def name_of(family: str, symbol_class: str | None, brand: str, model: str, attrs: dict[str, Any]) -> str:
    """The app's wording, never typed (09 §7.16): `text.describe`, as every catalog item's."""
    return text.describe(family, symbol_class, brand, model, attrs)


def new_product(ctx: Ctx, line_id: str, body: NewProduct) -> Done:
    """09 §7.16: a factory product from a waiting line: its family, the family's attributes (filled from the drawing,
    as edited), brand and model required, the SKU optional; named the app's way. The line's components move to it,
    approved; with a brand and a SKU it is a candidate for the master catalog (10 §5.4). Undo deletes it unless
    another quote uses it."""
    row = _line(ctx, line_id)
    if not row.pending:
        raise ReviewError(409, "not_pending")
    family = _family_of(ctx, row)
    brand, model = body.brand.strip(), body.model_code.strip()
    if not brand or not model or len(brand) > MAX_TEXT or len(model) > MAX_TEXT:
        raise ReviewError(422, "validation_error", ("brand" if not brand else "model_code",), "required")
    schema = schemas_mod.load(ctx.session)
    known = set(schema.names(family))
    attrs = {k: _value(v) for k, v in body.attributes.items() if v not in (None, "") and k in known}
    missing = [n for n in schema.required(family) if n not in attrs]
    if missing:
        raise ReviewError(422, "validation_error", ("attributes", missing[0]), "required")
    sku = (body.sku or "").strip() or None
    symbol_class = _class_of(ctx, row)
    name = name_of(family, symbol_class, brand, model, attrs)
    actor = pl.Actor(ctx.tid, ctx.actor.user_id)
    product = pl.create_product(
        ctx.session,
        actor,
        pl.ProductIn(
            display_name=name,
            family=family,
            source="manual_entry",
            manufacturer_sku=sku,
            brand=brand,
            attributes=attrs,
            series=(body.series or "").strip() or None,
            model_code=model,
            symbol_class=symbol_class,
        ),
        quote_id=ctx.quote.id,
    )
    replaced = Replaced(sku or model, brand, name, None, product.id)
    return choose(
        ctx,
        row,
        replaced,
        event_type="product_created",
        after={"family": family, "attributes": attrs, "read": _read_values(ctx, row)},
        restore_extra={"product": {"created": product.id}},
    )


def _component(ctx: Ctx, row: m.QuoteLine) -> Any:
    out = ctx.outputs()
    if out is None:
        return None
    if (row.line_key or "").startswith("m:"):
        return next((x for x in out.merge.missing if x.instance_id == (row.line_key or "")[2:]), None)
    return next((c for c in out.merge.components if c.component_id == row.component_id), None)


def _family_of(ctx: Ctx, row: m.QuoteLine) -> str:
    found = _component(ctx, row)
    if found is None:
        raise ReviewError(422, "validation_error", ("line_id",), "no_component")
    return str(found.family)


def _class_of(ctx: Ctx, row: m.QuoteLine) -> str | None:
    found = _component(ctx, row)
    cls = getattr(found, "symbol_class", None)
    return None if cls in (None, "unknown") else str(cls)


def _read_values(ctx: Ctx, row: m.QuoteLine) -> dict[str, Any]:
    found = _component(ctx, row)
    if found is None:
        return {}
    return {k: a.value for k, a in found.attributes.items() if a.value is not None}


def preview(ctx: Ctx, line_id: str, body: NewProduct) -> str:
    """The name "מוצר חדש" would give, as the user fills the form (09 §7.16): nothing is saved."""
    row = _line(ctx, line_id)
    family = _family_of(ctx, row)
    known = set(schemas_mod.load(ctx.session).names(family))
    attrs = {k: _value(v) for k, v in body.attributes.items() if v not in (None, "") and k in known}
    return name_of(family, _class_of(ctx, row), body.brand.strip(), body.model_code.strip(), attrs)


def form(ctx: Ctx, line_id: str) -> dict[str, Any]:
    """What the form opens with (09 §7.16): the line's family, its schema's attributes with what was read, and which
    of them are required."""
    row = _line(ctx, line_id)
    if not row.pending:
        raise ReviewError(409, "not_pending")
    family = _family_of(ctx, row)
    schema = schemas_mod.load(ctx.session)
    read = _read_values(ctx, row)
    return {
        "family": family,
        "symbol_class": _class_of(ctx, row),
        "attributes": [
            {"name": a.name, "required": a.required, "value": _text(read.get(a.name))}
            for a in schema.attributes(family)
        ],
        "brand": row.manufacturer,
    }


def pending_count(rows: Iterable[m.QuoteLine]) -> int:
    return sum(1 for r in rows if r.pending and r.deleted_at is None)


def refuse_pending(ctx: Ctx, row: m.QuoteLine) -> None:
    """S27b decision 2 (07): a waiting line has no price until a product is chosen."""
    if row.pending and on(ctx):
        raise ReviewError(409, "pending_line")
