"""The review screen's actions (09 §7, S23): what each one changes, what runs again on the server, what it writes for
the learning loop (09 §10), and how it is undone (09 §7.11).

Every action is one transaction on the quote's current version, which must be a draft: a sent version never changes
(07 §7.7), so every action on one is a 409. Each action:
1. keeps what it is about to change (the lines, the findings, the price-list product, the match memory) in its
   correction event, under `before.restore`, so undo can put it back;
2. changes the lines' carried state (`approved_at`, `deleted_at`, `override`, `edits`) or the price list;
3. runs stages 6 and 7 again (`refresh`): the rules on the panels an edit touched (06 §6.3), when it changed what
   the validator reads; then stage 7, with every line the action did not touch keeping its price (07 §7.2.3);
4. writes its correction event (09 §10) and answers with a toast and the event id, for "בטל".

A drawing with stage outputs is priced by the whole engine (`pricing.run.price_drawing`), so derived items and labor
follow the edit. A quote with none (the review fixture, a quote built by hand) is priced from its stored lines
(`pricing.stored`). Runs inside `tenant_session`; the explicit `tenant_id` filters are a second guard.
"""

import contextlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.contracts.matching import CatalogItemSnapshot, MatchingResult
from konboro.contracts.merge import AttributeValue, MergeResult
from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.pipeline.pricing import load as pricing_load
from konboro.pipeline.pricing import run as pricing
from konboro.pipeline.pricing import stored
from konboro.pipeline.pricing.edits import Replaced
from konboro.services import match_memory, validation
from konboro.services import price_list as pl
from konboro.services.storage import Storage

DismissReason = Literal["intended", "checker_wrong", "other"]
DISMISS_TEXT = {"intended": "מכוון", "checker_wrong": "הבודק טעה", "other": "אחר", "approved": "אושר ידנית"}

DECIMALS = ("qty", "unit_cost", "unit_price_raw", "unit_price", "line_cost", "line_total", "margin_pct")
TIMES = ("approved_at", "deleted_at")
LINE_STATE = (
    *DECIMALS,
    *TIMES,
    "line_type",  # a missing line resolved is a component line (09 §7.8)
    "sku",
    "description",
    "manufacturer",
    "catalog_item_id",
    "product_id",
    "unit",
    "cost_source",
    "price_status",
    "margin_rule",
    "rounding",
    "alternatives",
    "status",
    "status_reasons",
    "issue_ids",
    "override",
    "edits",
)


class ReviewError(Exception):
    def __init__(self, status: int, code: str, loc: Sequence[str | int] = (), kind: str | None = None) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.details = [{"loc": ["body", *loc], "type": kind or code}] if loc else None


@dataclass(frozen=True)
class Actor:
    tenant_id: str
    user_id: str


@dataclass(frozen=True)
class Done:
    """What the screen says after the action (09 §7.11's toast), and the event that undoes it."""

    message: str
    event_id: str | None = None
    count: int = 1
    sanity: dict[str, Any] | None = None  # 10 §8, after a typed cost


@dataclass
class Ctx:
    session: Session
    storage: Storage
    actor: Actor
    quote: m.Quote
    version: m.QuoteVersion
    _outputs: pricing.Outputs | bool | None = field(default=False, repr=False)

    @property
    def tid(self) -> str:
        return self.actor.tenant_id

    def outputs(self) -> pricing.Outputs | None:
        """The drawing's stage 1, 4, 5 and 6 results; None for a quote with no drawing, or one never piped."""
        if self._outputs is False:
            self._outputs = None
            if self.quote.drawing_id:
                with contextlib.suppress(LookupError):
                    self._outputs = pricing.read_outputs(self.session, self.storage, self.tid, self.quote.drawing_id)
        return self._outputs  # type: ignore[return-value]

    def lines(self, live: bool = True) -> list[m.QuoteLine]:
        q = select(m.QuoteLine).where(
            m.QuoteLine.tenant_id == self.tid, m.QuoteLine.quote_version_id == self.version.id
        )
        if live:
            q = q.where(m.QuoteLine.deleted_at.is_(None))
        return list(self.session.scalars(q.order_by(m.QuoteLine.position)))


# --- the quote and its lines ----------------------------------------------------------------------------------------


def open_draft(session: Session, storage: Storage, actor: Actor, quote_id: str) -> Ctx:
    quote = session.scalar(select(m.Quote).where(m.Quote.tenant_id == actor.tenant_id, m.Quote.id == quote_id))
    if quote is None:
        raise ReviewError(404, "not_found")
    version = session.scalar(
        select(m.QuoteVersion).where(
            m.QuoteVersion.tenant_id == actor.tenant_id,
            m.QuoteVersion.quote_id == quote.id,
            m.QuoteVersion.version == quote.current_version,
        )
    )
    if version is None:
        raise ReviewError(404, "not_found")
    if version.status == "sent":
        raise ReviewError(409, "quote_sent")
    return Ctx(session, storage, actor, quote, version)


def _line(ctx: Ctx, line_id: str, live: bool = True) -> m.QuoteLine:
    q = select(m.QuoteLine).where(
        m.QuoteLine.tenant_id == ctx.tid,
        m.QuoteLine.quote_version_id == ctx.version.id,
        m.QuoteLine.id == line_id,
    )
    q = q.where(m.QuoteLine.deleted_at.is_(None) if live else m.QuoteLine.deleted_at.is_not(None))
    row = ctx.session.scalar(q)
    if row is None:
        raise ReviewError(404, "not_found")
    return row


def _children(ctx: Ctx, row: m.QuoteLine) -> list[m.QuoteLine]:
    return [r for r in ctx.lines() if r.parent_line_id == row.id]


def key_of(row: m.QuoteLine) -> str:
    return stored.key_of(row)


def now() -> datetime:
    return datetime.now(UTC)


# --- undo state -----------------------------------------------------------------------------------------------------


def _json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def snap_lines(rows: Iterable[m.QuoteLine]) -> dict[str, dict[str, Any]]:
    return {r.id: {f: _json(getattr(r, f)) for f in LINE_STATE} for r in rows}


def snap_findings(rows: Iterable[m.Finding]) -> dict[str, dict[str, Any]]:
    return {f.id: {"status": f.status, "dismissal": f.dismissal} for f in rows}


def snap_product(session: Session, tenant_id: str, product_id: str | None) -> dict[str, Any] | None:
    if product_id is None:
        return None
    p = session.get(m.Product, product_id)
    if p is None or p.tenant_id != tenant_id:
        return None
    suppliers = session.scalars(
        select(m.ProductSupplier).where(
            m.ProductSupplier.tenant_id == tenant_id, m.ProductSupplier.product_id == product_id
        )
    )
    return {
        "product_id": p.id,
        "fields": {f: pl.as_json(getattr(p, f)) for f in pl.PRODUCT_FIELDS},
        "suppliers": [pl.supplier_snapshot(r) for r in suppliers],
    }


def _restore_lines(ctx: Ctx, state: dict[str, dict[str, Any]]) -> None:
    for line_id, values in state.items():
        row = ctx.session.get(m.QuoteLine, line_id)
        if row is None or row.tenant_id != ctx.tid or row.quote_version_id != ctx.version.id:
            continue  # gone with a recalculation: nothing to put back
        for f, v in values.items():
            if f in DECIMALS:
                v = Decimal(v) if v is not None else None
            elif f in TIMES:
                v = datetime.fromisoformat(v) if v is not None else None
            setattr(row, f, v)
    ctx.session.flush()


def _restore_findings(ctx: Ctx, state: dict[str, dict[str, Any]]) -> None:
    for finding_id, values in state.items():
        row = ctx.session.get(m.Finding, finding_id)
        if row is not None and row.tenant_id == ctx.tid:
            row.status, row.dismissal = values["status"], values["dismissal"]
    ctx.session.flush()


def _restore_product(ctx: Ctx, state: dict[str, Any]) -> None:
    actor = pl.Actor(ctx.tid, ctx.actor.user_id)
    if "created" in state:
        product = ctx.session.get(m.Product, state["created"])
        if product is None or product.tenant_id != ctx.tid:
            return
        users = list(
            ctx.session.scalars(
                select(m.QuoteLine).where(m.QuoteLine.tenant_id == ctx.tid, m.QuoteLine.product_id == product.id)
            )
        )
        if any(r.quote_version_id != ctx.version.id for r in users):
            return  # another quote priced from it since: it stays in the price list
        for r in users:
            r.product_id = None
        ctx.session.flush()
        snapshot = pl.product_snapshot(product)
        ctx.session.delete(product)  # its history goes with it (`price_history` cascades); this row says why
        ctx.session.flush()
        pl.log(
            ctx.session, actor, "deleted", snapshot, None, quote_id=ctx.quote.id, subject_key=f"product:{product.id}"
        )
        return
    fields = dict(state["fields"])
    fixed = fields.get("fixed_price")
    fields["fixed_price"] = Decimal(fixed) if fixed is not None else None
    rows = [
        pl.SupplierPriceIn(
            id=r["id"],
            supplier_id=r["supplier_id"],
            supplier_sku=r["supplier_sku"],
            unit_cost=Decimal(r["unit_cost"]),
            currency=r["currency"],
            lead_days=r["lead_days"],
            price_date=date.fromisoformat(r["price_date"]),
            valid_until=date.fromisoformat(r["valid_until"]) if r["valid_until"] else None,
            preferred=r["preferred"],
            source=r["source"],
        )
        for r in state["suppliers"]
    ]
    existing = {
        r.id
        for r in ctx.session.scalars(
            select(m.ProductSupplier).where(
                m.ProductSupplier.tenant_id == ctx.tid, m.ProductSupplier.product_id == state["product_id"]
            )
        )
    }
    rows = [r if r.id in existing else replace(r, id=None) for r in rows]  # one undone was deleted since
    pl.update_product(ctx.session, actor, state["product_id"], fields, rows, quote_id=ctx.quote.id)


def _restore_memory(ctx: Ctx, state: list[dict[str, Any]]) -> None:
    for r in state:
        row = ctx.session.get(m.MatchMemory, r["id"])
        if row is not None and row.tenant_id == ctx.tid:
            row.approved_count = r["approved_count"]
            row.last_used_at = datetime.fromisoformat(r["last_used_at"]) if r["last_used_at"] else None
    ctx.session.flush()


# --- events ---------------------------------------------------------------------------------------------------------


def _event(
    ctx: Ctx,
    type_: str,
    *,
    line: m.QuoteLine | None = None,
    line_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    restore: dict[str, Any] | None = None,
) -> m.CorrectionEvent:
    """09 §10. `restore` is what undo puts back; it rides in `before`. The trigger allows no change to an event but
    `undone`, so an event is written once, whole."""
    event = m.CorrectionEvent(
        id=new_id("evt"),
        tenant_id=ctx.tid,
        quote_id=ctx.quote.id,
        quote_version=ctx.version.version,
        user_id=ctx.actor.user_id,
        source="review_screen",
        type=type_,
        line_id=line.id if line else line_id,
        component_id=line.component_id if line else None,
        before={**(before or {}), **({"restore": restore} if restore is not None else {})},
        after=after,
        reason=reason,
    )
    ctx.session.add(event)
    ctx.session.flush()
    return event


def _restore_of(
    ctx: Ctx,
    rows: Iterable[m.QuoteLine],
    findings: Iterable[m.Finding] = (),
    product: dict[str, Any] | None = None,
    memory: list[dict[str, Any]] | None = None,
    panels: Iterable[str | None] = (),
) -> dict[str, Any]:
    out: dict[str, Any] = {"lines": snap_lines(rows), "findings": snap_findings(findings)}
    if product is not None:
        out["product"] = product
    if memory:
        out["memory"] = memory
    stage6 = sorted({p for p in panels if p})
    if stage6:
        out["revalidate"] = stage6
    out["deleted_line_keys"] = list((ctx.version.snapshot or {}).get("deleted_line_keys", []))
    return out


# --- stages 6 and 7 again -------------------------------------------------------------------------------------------


def edited_outputs(ctx: Ctx, out: pricing.Outputs) -> tuple[MergeResult, MatchingResult]:
    """Stage 4 and 5's results as the estimator left them, for the rules (06 §6.3): a quantity, a deleted line's
    component gone, an alternative's SKU. The stored results stay as the pipeline wrote them."""
    rows = ctx.lines(live=False)
    deleted = {r.component_id for r in rows if r.deleted_at and r.component_id and not r.parent_line_id} - {
        r.component_id for r in rows if not r.deleted_at and r.component_id
    }
    heads = {r.component_id: r for r in rows if not r.deleted_at and r.component_id and not r.parent_line_id}
    components = []
    for c in out.merge.components:
        if c.component_id in deleted:
            continue
        edits = (heads[c.component_id].edits or {}) if c.component_id in heads else {}
        update: dict[str, Any] = {}
        if edits.get("qty"):
            update["quantity"] = int(Decimal(edits["qty"]))
        if edits.get("attrs"):  # 09 §7.4: the user's value, which the rules read (C50 → C20)
            attrs = dict(c.attributes)
            for name, value in edits["attrs"].items():
                attrs[name] = AttributeValue(value=value, source="user", confidence=1.0)
            update["attributes"] = attrs
        components.append(c.model_copy(update=update) if update else c)
    matches = []
    for x in out.matching.matches:
        e = (heads[x.component_id].edits or {}) if x.component_id in heads else {}
        rep = e.get("replaced") or e.get("match")
        if rep and rep.get("sku"):
            item = ctx.session.scalar(select(m.CatalogItem).where(m.CatalogItem.sku == rep["sku"]).limit(1))
            snapshot = (
                CatalogItemSnapshot(
                    sku=item.sku,
                    manufacturer=item.brand,
                    series=item.series,
                    description=rep["description"],
                    attributes=item.attributes,
                )
                if item
                else None
            )
            x = x.model_copy(update={"chosen_sku": rep["sku"], "catalog_item": snapshot, "method": "user"})
        matches.append(x)
    merge = out.merge.model_copy(update={"components": components})
    return merge, out.matching.model_copy(update={"matches": matches})


def refresh(ctx: Ctx, reprice: Iterable[str] = (), revalidate: Iterable[str | None] = ()) -> None:
    """Stage 6 on the panels in `revalidate`, then stage 7, with the lines whose keys are in `reprice` priced from
    the list and every other line keeping its price."""
    keys = frozenset(reprice)
    out = ctx.outputs()
    if out is None:
        stored.reprice(ctx.session, ctx.quote, ctx.version, keys)
        return
    drawing = ctx.session.get_one(m.Drawing, ctx.quote.drawing_id)
    panels = sorted({p for p in revalidate if p})
    if panels:
        merge, matching = edited_outputs(ctx, out)
        for panel_id in panels:
            validation.revalidate_panel(
                ctx.session, ctx.storage, ctx.tid, drawing.id, panel_id, merge=merge, matching=matching
            )
        out = pricing.read_outputs(ctx.session, ctx.storage, ctx.tid, drawing.id)
        ctx._outputs = out
    pricing.price_drawing(ctx.session, ctx.tid, drawing, out, ctx.quote.name, keep=keys)


# --- line actions (09 §7.2–7.6) -------------------------------------------------------------------------------------


def _open_findings(ctx: Ctx) -> list[m.Finding]:
    return list(
        ctx.session.scalars(
            select(m.Finding).where(
                m.Finding.tenant_id == ctx.tid,
                m.Finding.quote_version_id == ctx.version.id,
                m.Finding.status == "open",
            )
        )
    )


def _signature(ctx: Ctx, row: m.QuoteLine) -> str | None:
    out = ctx.outputs()
    if out is None or not row.component_id:
        return None
    match = next((x for x in out.matching.matches if x.component_id == row.component_id), None)
    return match.signature if match else None


def approve(ctx: Ctx, line_id: str) -> Done:
    """09 §7.2: green with "אושר"; the line's open findings are dismissed as "אושר ידנית" once every line they name
    is approved; the match memory that chose the line is strengthened (05 §11)."""
    row = _line(ctx, line_id)
    if row.line_type == "missing":
        raise ReviewError(422, "validation_error", ("line_id",), "missing_line")  # pick a product (09 §7.8, S23b)
    if row.approved_at is not None:
        return Done("השורה כבר מאושרת")
    approved = {r.id for r in ctx.lines() if r.approved_at} | {row.id}
    findings = [
        f for f in _open_findings(ctx) if f.source != "pricing" and row.id in f.line_ids and set(f.line_ids) <= approved
    ]
    sig, memory = _signature(ctx, row), []
    if sig and row.sku:
        memory = [
            {"id": r.id, "approved_count": r.approved_count, "last_used_at": _json(r.last_used_at)}
            for r in match_memory.rows_for(ctx.session, ctx.tid, sig, row.sku, ctx.quote.customer_id)
        ]
    restore = _restore_of(ctx, [row], findings, memory=memory)
    event = _event(
        ctx,
        "row_confirmed",
        line=row,
        before={"status": row.status, "status_reasons": row.status_reasons},
        after={"status": "green", "sku": row.sku, "signature": sig},
        restore=restore,
    )
    row.approved_at = now()
    for f in findings:
        f.status = "dismissed"
        f.dismissal = {"reason": "approved", "by": ctx.actor.user_id, "at": now().isoformat(), "event_id": event.id}
    if sig and row.sku:
        match_memory.approve_all(ctx.session, ctx.tid, sig, row.sku, ctx.quote.customer_id)
    ctx.session.flush()
    refresh(ctx)
    return Done(f"אושר: {row.description}", event.id)


def delete(ctx: Ctx, line_id: str) -> Done:
    """09 §7.6: the line leaves the quote, its kit parts with it. A derived line is not made again by a
    recalculation (07 §7.4)."""
    row = _line(ctx, line_id)
    children = _children(ctx, row)
    derived = row.line_type in ("derived", "labor")
    restore = _restore_of(ctx, [row, *children], panels=[] if derived else [row.panel_id])
    before: dict[str, Any] = {"description": row.description, "qty": _json(row.qty), "line_type": row.line_type}
    if row.line_type == "missing":  # "אין כאן רכיב": a negative example for the detector (09 §7.6, 03 §11)
        before |= {"boxes": row.boxes, "negative_example": True}
    event = _event(ctx, "derived_removed" if derived else "row_deleted", line=row, before=before, restore=restore)
    at = now()
    for r in (row, *children):
        r.deleted_at = at
    ctx.session.flush()
    refresh(ctx, revalidate=[] if derived else [row.panel_id])
    if row.line_type == "missing":
        return Done("השורה נמחקה: אין כאן רכיב", event.id)
    return Done("הפריט הנלווה הוסר מההצעה" if derived else "השורה נמחקה", event.id)


def restore_lines(ctx: Ctx, line_ids: Sequence[str]) -> Done:
    """09 §6.3 "X פריטים נלווים הוסרו" → "החזר": deleted lines back, as they were."""
    if not line_ids:
        raise ReviewError(422, "validation_error", ("line_ids",), "missing")
    rows = [_line(ctx, i, live=False) for i in dict.fromkeys(line_ids)]
    keys = {r.line_key for r in rows if r.line_key}
    restore = _restore_of(ctx, rows, panels=[r.panel_id for r in rows if r.line_type not in ("derived", "labor")])
    event = _event(
        ctx,
        "derived_restored",
        after={"line_ids": [r.id for r in rows], "descriptions": [r.description for r in rows]},
        restore=restore,
    )
    for r in rows:
        r.deleted_at = None
    snapshot = dict(ctx.version.snapshot or {})
    snapshot["deleted_line_keys"] = [k for k in snapshot.get("deleted_line_keys", []) if k not in keys]
    ctx.version.snapshot = snapshot
    ctx.session.flush()
    refresh(ctx, revalidate=restore.get("revalidate", []))
    n = len(rows)
    return Done("הפריט הוחזר להצעה" if n == 1 else f"{n} פריטים הוחזרו להצעה", event.id, n)


def _edit(row: m.QuoteLine, **changes: Any) -> None:
    edits = dict(row.edits or {})
    for k, v in changes.items():
        if v is None:
            edits.pop(k, None)
        else:
            edits[k] = v
    row.edits = edits


def set_quantity(ctx: Ctx, line_id: str, qty: Decimal) -> Done:
    """09 §7.5: at least 1. The rules run again (a BOM count may now agree), then stage 7."""
    row = _line(ctx, line_id)
    if row.line_type not in ("component", "manual") or row.parent_line_id:
        raise ReviewError(422, "validation_error", ("line_id",), "fixed_quantity")
    if qty < 1 or qty != qty.to_integral_value() or qty > 100000:
        raise ReviewError(422, "validation_error", ("qty",), "invalid")
    if qty == row.qty:
        return Done("הכמות לא השתנתה")
    restore = _restore_of(ctx, [row, *_children(ctx, row)], panels=[row.panel_id])
    event = _event(
        ctx,
        "quantity_changed",
        line=row,
        before={"qty": _json(row.qty)},
        after={"qty": str(qty)},
        restore=restore,
    )
    _edit(row, qty=str(qty))
    ctx.session.flush()
    refresh(ctx, revalidate=[row.panel_id])
    return Done(f"הכמות עודכנה: {qty}", event.id)


def _same_signature(ctx: Ctx, row: m.QuoteLine) -> list[m.QuoteLine]:
    """09 §7.3: the lines with the same signature in the drawing, in every panel. Without stage 5's results, the
    lines with the same SKU and wording."""
    rows = [r for r in ctx.lines() if r.line_type == "component" and not r.parent_line_id]
    out = ctx.outputs()
    if out is not None and row.component_id:
        sig = {x.component_id: x.signature for x in out.matching.matches}
        mine = sig.get(row.component_id)
        if mine:
            return [r for r in rows if r.component_id and sig.get(r.component_id) == mine]
    return [r for r in rows if r.id == row.id or (r.sku == row.sku and r.description == row.description)]


def _alternative_description(session: Session, alt: dict[str, Any]) -> tuple[str, str | None]:
    sku = alt.get("sku")
    item = session.scalar(select(m.CatalogItem).where(m.CatalogItem.sku == sku).limit(1)) if sku else None
    if item is not None:
        return pricing_load.describe(item), item.id
    text = str(alt.get("description") or sku or "")
    return text.split(" · ")[0], None


def choose_alternative(ctx: Ctx, line_id: str, index: int) -> Done:
    """09 §7.3: the alternative's SKU on every line with the same signature, each approved; stages 6 and 7 on what
    it touched. `sku_replaced` per line, for this quote only: nothing is remembered for the factory (08 §7.4)."""
    row = _line(ctx, line_id)
    if not 0 <= index < len(row.alternatives):
        raise ReviewError(422, "validation_error", ("index",), "invalid")
    alt = dict(row.alternatives[index])
    description, item_id = _alternative_description(ctx.session, alt)
    replaced = Replaced(alt.get("sku"), alt.get("manufacturer"), description, item_id)
    targets = _same_signature(ctx, row)
    rows = [*targets, *(c for t in targets for c in _children(ctx, t))]
    restore = _restore_of(ctx, rows, panels=[t.panel_id for t in targets])
    group = new_id("evt")  # one action, one event per line (09 §10): undo takes them all back
    first = None
    at = now()
    for t in targets:
        event = _event(
            ctx,
            "sku_replaced",
            line=t,
            before={"sku": t.sku, "description": t.description, "manufacturer": t.manufacturer},
            after={
                "sku": replaced.sku,
                "description": replaced.description,
                "manufacturer": replaced.manufacturer,
                "group": group,
            },
            restore=restore if first is None else None,
        )
        first = first or event
        # the product it had becomes an alternative, so the estimator can go back to it
        previous = {"sku": t.sku, "manufacturer": t.manufacturer, "description": t.description}
        others = [
            a for i, a in enumerate(t.alternatives) if i != index and (not a.get("sku") or a["sku"] != replaced.sku)
        ]
        t.alternatives = [*others, previous]
        _edit(t, replaced=replaced.as_json())
        t.approved_at = at
    ctx.session.flush()
    refresh(ctx, reprice=[key_of(t) for t in targets], revalidate=[t.panel_id for t in targets])
    n = len(targets)
    assert first is not None  # noqa: S101  # targets holds the line itself
    return Done(
        f"הוחלף ב-{n} שורות זהות" if n > 1 else f"הוחלף: {row.description} ← {replaced.description}", first.id, n
    )


def dismiss_finding(ctx: Ctx, finding_id: str, reason: DismissReason, text: str | None) -> Done:
    """09 §7.7, 06 §11: the finding leaves its lines, and their colour follows. Pricing's findings are not dismissed:
    a price answers them."""
    finding = ctx.session.scalar(
        select(m.Finding).where(
            m.Finding.tenant_id == ctx.tid,
            m.Finding.quote_version_id == ctx.version.id,
            m.Finding.id == finding_id,
            m.Finding.status == "open",
        )
    )
    if finding is None:
        raise ReviewError(404, "not_found")
    if finding.source == "pricing":
        raise ReviewError(422, "validation_error", ("finding_id",), "pricing_finding")
    if reason == "other" and not (text or "").strip():
        raise ReviewError(422, "validation_error", ("text",), "missing")
    restore = _restore_of(ctx, [], [finding])
    event = _event(
        ctx,
        "issue_dismissed",
        before={"status": "open", "code": finding.code},
        after={"rule_id": finding.rule_id or finding.code, "reason": reason, "severity": finding.severity},
        reason=(text or "").strip() or DISMISS_TEXT[reason],
        restore=restore,
        line_id=finding.line_ids[0] if finding.line_ids else None,
    )
    finding.status = "dismissed"
    finding.dismissal = {
        "reason": reason,
        "text": (text or "").strip() or None,
        "by": ctx.actor.user_id,
        "at": now().isoformat(),
        "event_id": event.id,
    }
    ctx.session.flush()
    refresh(ctx)
    return Done("הממצא נדחה", event.id)


# --- prices, costs and suppliers (09 §7.13–7.15, 07 §7.2.2–7.2.3) ---------------------------------------------------


def _same_product(ctx: Ctx, row: m.QuoteLine, product_id: str | None) -> list[m.QuoteLine]:
    """07 §7.2, 09 §7.13: a price entered for a product reaches every line of it, in every panel, kits included."""
    return [
        r
        for r in ctx.lines()
        if r.id == row.id or (product_id and r.product_id == product_id) or (row.sku and r.sku == row.sku)
    ]


def _family(ctx: Ctx, row: m.QuoteLine) -> str:
    if row.catalog_item_id:
        item = ctx.session.get(m.CatalogItem, row.catalog_item_id)
        if item is not None:
            return item.family
    if row.component_id:
        cmp = ctx.session.get(m.Component, row.component_id)
        if cmp is not None and cmp.family:
            return cmp.family
    return "other"


def _product_for(ctx: Ctx, row: m.QuoteLine) -> m.Product | None:
    """The line's product: its own, else the one with the line's SKU (07 §7.2: the identical product only)."""
    if row.product_id:
        return ctx.session.get(m.Product, row.product_id)
    if row.sku:
        return ctx.session.scalar(
            select(m.Product).where(m.Product.tenant_id == ctx.tid, m.Product.manufacturer_sku == row.sku)
        )
    return None


def _priced_text(amount: Decimal) -> str:
    return f"₪{amount.normalize():f}"


def _as_in(s: pl.SupplierPriceView, **changes: Any) -> pl.SupplierPriceIn:
    row = pl.SupplierPriceIn(
        id=s.id,
        supplier_id=s.supplier_id,
        supplier_sku=s.supplier_sku,
        unit_cost=s.unit_cost,
        currency=s.currency,
        lead_days=s.lead_days,
        price_date=s.price_date,
        valid_until=s.valid_until,
        preferred=s.preferred,
        source=s.source,
    )
    return replace(row, **changes)


def _link(lines: Sequence[m.QuoteLine], row: m.QuoteLine, product_id: str) -> None:
    for r in lines:
        if r.id == row.id or (row.sku and r.sku == row.sku):
            r.product_id = product_id


def enter_price(ctx: Ctx, line_id: str, unit_price: Decimal, save: bool) -> Done:
    """The row's price cell on a line with no price (prototype lines 879, 1566–1580; S23 decision 3). "שמור למחירון"
    on: the product is `fixed` at that price in the price list, made from the line when there is none, and every line
    of it in the quote is priced. Off: for this quote only, as an override."""
    row = _line(ctx, line_id)
    if row.unit_price is not None:
        raise ReviewError(409, "line_priced")
    pl.check_money(unit_price, ("unit_price",))
    if unit_price <= 0:
        raise ReviewError(422, "validation_error", ("unit_price",), "invalid_amount")
    actor = pl.Actor(ctx.tid, ctx.actor.user_id)
    if not save:
        event = _event(
            ctx,
            "price_entered",
            line=row,
            after={"unit_price": str(unit_price), "saved": False},
            restore=_restore_of(ctx, [row]),
        )
        row.override = {
            "scope": "quote",
            "unit_price": str(unit_price),
            "previous_price": None,
            "by": ctx.actor.user_id,
            "at": now().isoformat(),
        }
        ctx.session.flush()
        refresh(ctx)
        return Done("נשמר להצעה הזו בלבד", event.id)
    product = _product_for(ctx, row)
    lines = _same_product(ctx, row, product.id if product else None)
    restore = _restore_of(ctx, lines)
    if product is None:
        product_id = pl.create_product(
            ctx.session,
            actor,
            pl.ProductIn(
                display_name=row.description,
                family=_family(ctx, row),
                source="manual_entry",
                manufacturer_sku=row.sku,
                brand=row.manufacturer,
                sale_mode="fixed",
                fixed_price=unit_price,
                catalog_item_id=row.catalog_item_id,
            ),
            quote_id=ctx.quote.id,
        ).id
        restore["product"] = {"created": product_id}
    else:
        product_id = product.id
        restore["product"] = snap_product(ctx.session, ctx.tid, product_id)
        pl.update_product(
            ctx.session, actor, product_id, {"sale_mode": "fixed", "fixed_price": unit_price}, quote_id=ctx.quote.id
        )
    event = _event(
        ctx,
        "price_entered",
        line=row,
        after={"unit_price": str(unit_price), "saved": True, "product_id": product_id},
        restore=restore,
    )
    _link(lines, row, product_id)
    for r in lines:
        r.override = None
    ctx.session.flush()
    refresh(ctx, reprice=[key_of(r) for r in lines])
    return Done(f"נשמר במחירון: {row.description}, {_priced_text(unit_price)}", event.id, len(lines))


def enter_cost(ctx: Ctx, line_id: str, unit_cost: Decimal, supplier: str | None) -> Done:
    """09 §6.4 "שמור עלות" (prototype `addcost`): the cost saved to the price list as the supplier's, for every line of
    the product. A product with no preferred supplier gets this one. A line with no product gets one, priced by the
    factory's margin rules."""
    row = _line(ctx, line_id)
    if row.parent_line_id and row.unit_price == 0:
        raise ReviewError(422, "validation_error", ("line_id",), "included")
    pl.check_money(unit_cost, ("unit_cost",))
    if unit_cost <= 0:
        raise ReviewError(422, "validation_error", ("unit_cost",), "invalid_amount")
    actor = pl.Actor(ctx.tid, ctx.actor.user_id)
    name = (supplier or "").strip() or None
    product = _product_for(ctx, row)
    lines = _same_product(ctx, row, product.id if product else None)
    restore = _restore_of(ctx, lines)
    typed = pl.SupplierPriceIn(
        unit_cost=unit_cost, price_date=pl.today(ctx.session, ctx.tid), supplier_name=name, source="manual_entry"
    )
    if product is None:
        product_id = pl.create_product(
            ctx.session,
            actor,
            pl.ProductIn(
                display_name=row.description,
                family=_family(ctx, row),
                source="manual_entry",
                manufacturer_sku=row.sku,
                brand=row.manufacturer,
                catalog_item_id=row.catalog_item_id,
                suppliers=[replace(typed, preferred=True)],
            ),
            quote_id=ctx.quote.id,
        ).id
        restore["product"] = {"created": product_id}
    else:
        product_id = product.id
        restore["product"] = snap_product(ctx.session, ctx.tid, product_id)
        supplier_id = pl.supplier_by_name(ctx.session, actor, name).id if name else None
        current = pl.get_product(ctx.session, ctx.tid, product_id).suppliers
        rows = [
            _as_in(x, unit_cost=unit_cost, price_date=typed.price_date, source="manual_entry")
            if x.supplier_id == supplier_id
            else _as_in(x)
            for x in current
        ]
        if not any(x.supplier_id == supplier_id for x in current):
            rows.append(
                replace(
                    typed, supplier_id=supplier_id, supplier_name=None, preferred=not any(r.preferred for r in rows)
                )
            )
        pl.update_product(ctx.session, actor, product_id, {}, rows, quote_id=ctx.quote.id)
    event = _event(
        ctx,
        "price_entered",
        line=row,
        after={"unit_cost": str(unit_cost), "supplier": name, "product_id": product_id},
        restore=restore,
    )
    _link(lines, row, product_id)
    ctx.session.flush()
    sanity = ctx.session.get_one(m.Product, product_id).sanity
    refresh(ctx, reprice=[key_of(r) for r in lines])
    return Done("העלות נשמרה במחירון", event.id, len(lines), sanity)


def change_price(ctx: Ctx, line_id: str, unit_price: Decimal, scope: Literal["quote", "catalog"]) -> Done:
    """09 §7.14, 07 §7.2.3: "רק בהצעה הזו" sets an override tagged "מחיר להצעה הזו"; "עדכן גם במחירון" makes the
    product `fixed` at the new price, with the quote in its history. Other quotes never change by themselves: a draft
    shows "מחיר חדש במחירון"."""
    row = _line(ctx, line_id)
    pl.check_money(unit_price, ("unit_price",))
    if unit_price <= 0:
        raise ReviewError(422, "validation_error", ("unit_price",), "invalid_amount")
    if scope == "catalog" and row.product_id is None:
        raise ReviewError(422, "validation_error", ("scope",), "no_product")
    if unit_price == row.unit_price:
        return Done("המחיר לא השתנה")
    restore = _restore_of(ctx, [row])
    if scope == "catalog":
        restore["product"] = snap_product(ctx.session, ctx.tid, row.product_id)
    event = _event(
        ctx,
        "price_changed",
        line=row,
        before={"unit_price": pl.as_json(row.unit_price), "override": row.override},
        after={"unit_price": pl.as_json(unit_price), "scope": scope},
        restore=restore,
    )
    if scope == "catalog":
        pl.update_product(
            ctx.session,
            pl.Actor(ctx.tid, ctx.actor.user_id),
            row.product_id,  # type: ignore[arg-type]
            {"sale_mode": "fixed", "fixed_price": unit_price},
            quote_id=ctx.quote.id,
        )
        row.override = None
        ctx.session.flush()
        refresh(ctx, reprice=[key_of(row)])
        return Done("עודכן במחירון. הצעות שנשלחו לא השתנו", event.id)
    row.override = {
        "scope": "quote",
        "unit_price": pl.as_json(unit_price),
        "previous_price": pl.as_json(row.unit_price),
        "by": ctx.actor.user_id,
        "at": now().isoformat(),
    }
    ctx.session.flush()
    refresh(ctx)
    return Done("המחיר שונה רק בהצעה הזו", event.id)


def take_list_price(ctx: Ctx, line_id: str) -> Done:
    """07 §7.2.3 "עדכן בהצעה": the line takes the price list's price today."""
    row = _line(ctx, line_id)
    if row.product_id is None:
        raise ReviewError(422, "validation_error", ("line_id",), "no_product")
    restore = _restore_of(ctx, [row])
    event = _event(
        ctx,
        "price_changed",
        line=row,
        before={"unit_price": pl.as_json(row.unit_price), "override": row.override},
        after={"scope": "price_list"},
        restore=restore,
    )
    row.override = None
    ctx.session.flush()
    refresh(ctx, reprice=[key_of(row)])
    return Done("המחיר עודכן מהמחירון", event.id)


def choose_supplier(ctx: Ctx, line_id: str, supplier_price_id: str) -> Done:
    """09 §7.15: the cost from another of the product's suppliers, in this quote only. The sale price changes only
    when a margin rule makes it from the cost (07 §7.2.2)."""
    row = _line(ctx, line_id)
    if row.product_id is None:
        raise ReviewError(422, "validation_error", ("line_id",), "no_product")
    sp = ctx.session.scalar(
        select(m.ProductSupplier).where(
            m.ProductSupplier.tenant_id == ctx.tid,
            m.ProductSupplier.product_id == row.product_id,
            m.ProductSupplier.id == supplier_price_id,
        )
    )
    if sp is None:
        raise ReviewError(422, "validation_error", ("supplier_price_id",), "not_found")
    restore = _restore_of(ctx, [row])
    event = _event(
        ctx,
        "supplier_selected",
        line=row,
        before={"supplier_id": (row.edits or {}).get("supplier_id"), "unit_cost": pl.as_json(row.unit_cost)},
        after={"supplier_id": sp.supplier_id, "supplier_price_id": sp.id, "preferred": sp.preferred},
        restore=restore,
    )
    _edit(row, supplier_id=None if sp.preferred else sp.supplier_id)
    ctx.session.flush()
    refresh(ctx, reprice=[key_of(row)])
    return Done("הספק הוחלף רק בהצעה הזו" if not sp.preferred else "חזרה לספק המועדף", event.id)


def make_preferred(ctx: Ctx, line_id: str) -> Done:
    """09 §7.15 "הפוך למועדף במחירון": the supplier chosen on the line becomes the product's preferred one. Sale prices
    do not change by themselves."""
    row = _line(ctx, line_id)
    supplier_id = (row.edits or {}).get("supplier_id")
    if row.product_id is None or supplier_id is None:
        raise ReviewError(422, "validation_error", ("line_id",), "no_supplier_chosen")
    current = pl.get_product(ctx.session, ctx.tid, row.product_id)
    restore = _restore_of(ctx, [row], product=snap_product(ctx.session, ctx.tid, row.product_id))
    event = _event(
        ctx,
        "supplier_selected",
        line=row,
        after={"supplier_id": supplier_id, "made_preferred": True},
        restore=restore,
    )
    rows = [_as_in(x, preferred=x.supplier_id == supplier_id) for x in current.suppliers]
    actor = pl.Actor(ctx.tid, ctx.actor.user_id)
    pl.update_product(ctx.session, actor, row.product_id, {}, rows, quote_id=ctx.quote.id)
    _edit(row, supplier_id=None)
    ctx.session.flush()
    refresh(ctx)
    return Done("הספק המועדף עודכן במחירון. מחירי המכירה לא השתנו", event.id)


# --- undo (09 §7.11) ------------------------------------------------------------------------------------------------


def undo(ctx: Ctx, event_id: str) -> Done:
    """Puts back what the action changed, marks its event `undone` (it no longer feeds the learning loop, 09 §10) and
    writes an `undo` event. Only actions on this draft: after sending, nothing before it is undone (09 §7.11)."""
    event = ctx.session.scalar(
        select(m.CorrectionEvent).where(
            m.CorrectionEvent.tenant_id == ctx.tid,
            m.CorrectionEvent.quote_id == ctx.quote.id,
            m.CorrectionEvent.id == event_id,
        )
    )
    if event is None:
        raise ReviewError(404, "not_found")
    restore = (event.before or {}).get("restore")
    if event.quote_version != ctx.version.version or restore is None or event.type == "undo":
        raise ReviewError(409, "not_undoable")
    if event.undone:
        raise ReviewError(409, "already_undone")
    _restore_lines(ctx, restore.get("lines", {}))
    _restore_findings(ctx, restore.get("findings", {}))
    if restore.get("product"):
        _restore_product(ctx, restore["product"])
    if restore.get("memory"):
        _restore_memory(ctx, restore["memory"])
    if restore.get("created_lines") or restore.get("brand_discount"):
        from konboro.services import review_picker  # it builds on this module

        review_picker.undo_created(ctx, restore)
        if restore.get("brand_discount"):
            review_picker.undo_brand_discount(ctx, restore["brand_discount"])
    snapshot = dict(ctx.version.snapshot or {})
    snapshot["deleted_line_keys"] = restore.get("deleted_line_keys", [])
    ctx.version.snapshot = snapshot
    event.undone = True
    group = (event.after or {}).get("group")
    if event.type == "sku_replaced" and group:  # one action wrote one event per line: all are undone together
        for other in ctx.session.scalars(
            select(m.CorrectionEvent).where(
                m.CorrectionEvent.tenant_id == ctx.tid,
                m.CorrectionEvent.quote_id == ctx.quote.id,
                m.CorrectionEvent.type == "sku_replaced",
                m.CorrectionEvent.after["group"].astext == group,
                m.CorrectionEvent.undone.is_(False),
            )
        ):
            other.undone = True
    ctx.session.flush()
    mark = _event(ctx, "undo", after={"event_id": event.id, "type": event.type}, line_id=event.line_id)
    refresh(ctx, revalidate=restore.get("revalidate", []))
    return Done("הפעולה בוטלה", mark.id)
