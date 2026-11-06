"""One quote for the review screen (09 §4–6, prototype `vReview`), and its actions (09 §7, S23, S23b). The
`review_screen` flag that gated it while it was built (S09 decision 2) came out when S23b finished it.

Every action answers with the quote as it now is, the toast's text and the event "בטל" takes back (`ActionOut`). A
sent version is never changed: every action on it is a 409 (07 §7.7).
"""

from collections.abc import Callable
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request

from konboro.domain.permissions import Permission, allowed
from konboro.domain.totals import QuoteSums, Sums
from konboro.services import onboarding, price_list, quote_versions, quotes, review, review_picker, unresolved
from konboro.services.storage import Storage

from ..deps import Actor, require, require_flag
from ..errors import ERROR_RESPONSES, ApiError
from ..schemas import (
    ActionOut,
    AlternativeIn,
    AttributeIn,
    CostEntryIn,
    DismissIn,
    LineBrandDiscountIn,
    LinePriceIn,
    LineSupplierIn,
    MarkIn,
    PriceEntryIn,
    ProductChoiceOut,
    ProductRefIn,
    QuantityIn,
    QuoteOut,
    RecalculationOut,
    RestoreIn,
    UnresolvedOut,
)

router = APIRouter(tags=["quotes"], responses=ERROR_RESPONSES)

Reader = Annotated[Actor, Depends(require(Permission.QUOTES_READ))]
Writer = Annotated[Actor, Depends(require(Permission.QUOTES_WRITE))]
Sender = Annotated[Actor, Depends(require(Permission.QUOTES_SEND))]
QuoteId = Annotated[str, Path(pattern=r"^quo_[0-9A-Z]{26}$")]
LineId = Annotated[str, Path(pattern=r"^ln_[0-9A-Z]{26}$")]
FindingId = Annotated[str, Path(pattern=r"^iss_[0-9A-Za-z]{20,32}$")]
EventId = Annotated[str, Path(pattern=r"^evt_[0-9A-Z]{26}$")]


@router.get("/quotes/{quote_id}")
def get_quote(actor: Reader, quote_id: QuoteId, request: Request) -> QuoteOut:
    """The quote's current version. Another tenant's quote is 404, the same as one that does not exist."""
    return quote_out(actor, quote_id, request.app.state.storage)


@router.get("/quotes/{quote_id}/unresolved", dependencies=[Depends(require_flag("unresolved_overlay"))])
def get_unresolved(actor: Reader, quote_id: QuoteId, request: Request) -> UnresolvedOut:
    """13 §4.4: what the drawing shows that the system did not read, or read only in part, for the current version.
    Behind `unresolved_overlay`: off, the route does not exist (13 §3)."""
    spots = unresolved.read_spots(actor.session, request.app.state.storage, actor.tenant_id, quote_id)
    if spots is None:
        raise ApiError(404, "not_found")
    return UnresolvedOut.model_validate({"spots": [s.__dict__ for s in spots]})


def act(actor: Actor, quote_id: str, request: Request, action: Callable[[review.Ctx], review.Done]) -> ActionOut:
    storage = request.app.state.storage
    try:
        ctx = review.open_draft(actor.session, storage, review.Actor(actor.tenant_id, actor.user_id), quote_id)
        done = action(ctx)
    except review.ReviewError as e:
        raise ApiError(e.status, e.code, e.details) from e
    except price_list.PriceListError as e:
        raise ApiError(e.status, e.code, e.details) from e
    return ActionOut(
        quote=quote_out(actor, quote_id, storage),
        message=done.message,
        event_id=done.event_id,
        count=done.count,
        sanity=done.sanity,
    )


# --- lines (09 §7.2–7.6) --------------------------------------------------------------------------------------------


@router.post("/quotes/{quote_id}/lines/{line_id}/approve")
def approve_line(actor: Writer, quote_id: QuoteId, line_id: LineId, request: Request) -> ActionOut:
    """09 §7.2: the line green, "אושר"; its open findings dismissed when every line they name is approved."""
    return act(actor, quote_id, request, lambda c: review.approve(c, line_id))


@router.delete("/quotes/{quote_id}/lines/{line_id}")
def delete_line(actor: Writer, quote_id: QuoteId, line_id: LineId, request: Request) -> ActionOut:
    """09 §7.6: out of the quote, its kit parts with it. A deleted derived line is not made again (07 §7.4)."""
    return act(actor, quote_id, request, lambda c: review.delete(c, line_id))


@router.post("/quotes/{quote_id}/lines/restore")
def restore_lines(actor: Writer, quote_id: QuoteId, body: RestoreIn, request: Request) -> ActionOut:
    """09 §6.3 "החזר": deleted lines back."""
    return act(actor, quote_id, request, lambda c: review.restore_lines(c, body.line_ids))


@router.post("/quotes/{quote_id}/lines/{line_id}/qty")
def set_quantity(actor: Writer, quote_id: QuoteId, line_id: LineId, body: QuantityIn, request: Request) -> ActionOut:
    """09 §7.5: at least 1; the rules and stage 7 run again."""
    return act(actor, quote_id, request, lambda c: review.set_quantity(c, line_id, Decimal(body.qty)))


@router.post("/quotes/{quote_id}/lines/{line_id}/alternative")
def choose_alternative(
    actor: Writer, quote_id: QuoteId, line_id: LineId, body: AlternativeIn, request: Request
) -> ActionOut:
    """09 §7.3: the alternative on every line with the same signature, in every panel, each approved."""
    return act(actor, quote_id, request, lambda c: review.choose_alternative(c, line_id, body.index))


@router.post("/quotes/{quote_id}/findings/{finding_id}/dismiss")
def dismiss_finding(
    actor: Writer, quote_id: QuoteId, finding_id: FindingId, body: DismissIn, request: Request
) -> ActionOut:
    """09 §7.7, 06 §11: dismissed with a reason; its lines' colour follows."""
    return act(actor, quote_id, request, lambda c: review.dismiss_finding(c, finding_id, body.reason, body.text))


# --- the product picker (09 §6.4, §6.6, §7.4, §7.8; S23b) ----------------------------------------------------------


def _choices(found: list[review_picker.Choice]) -> list[ProductChoiceOut]:
    return [
        ProductChoiceOut(
            ref=c.ref,
            description=c.description,
            sku=c.sku,
            manufacturer=c.manufacturer,
            family=c.family,
            unit_price=c.unit_price,
        )
        for c in found
    ]


def _draft(actor: Actor, quote_id: str, request: Request) -> review.Ctx:
    try:
        return review.open_draft(
            actor.session, request.app.state.storage, review.Actor(actor.tenant_id, actor.user_id), quote_id
        )
    except review.ReviewError as e:
        raise ApiError(e.status, e.code, e.details) from e


@router.get("/quotes/{quote_id}/products")
def search_products(
    actor: Reader,
    quote_id: QuoteId,
    request: Request,
    q: Annotated[str | None, Query(max_length=100)] = None,
    family: Annotated[str | None, Query(max_length=64, pattern=r"^[a-z_]+$")] = None,
) -> list[ProductChoiceOut]:
    """09 §6.6 step 3, §6.4 "מוצר אחר…": the master catalog and the factory's products, priced ones first."""
    _draft(actor, quote_id, request)
    return _choices(review_picker.search(actor.session, actor.tenant_id, q, family))


@router.get("/quotes/{quote_id}/lines/{line_id}/candidates")
def missing_candidates(actor: Reader, quote_id: QuoteId, line_id: LineId, request: Request) -> list[ProductChoiceOut]:
    """09 §6.4: up to three products for a missing line, by what was read beside it (stage 5's code, no model)."""
    ctx = _draft(actor, quote_id, request)
    try:
        return _choices(review_picker.candidates(ctx, line_id))
    except review.ReviewError as e:
        raise ApiError(e.status, e.code, e.details) from e


@router.post("/quotes/{quote_id}/lines/{line_id}/attribute")
def set_attribute(actor: Writer, quote_id: QuoteId, line_id: LineId, body: AttributeIn, request: Request) -> ActionOut:
    """09 §7.4: current or breaking capacity set by hand; stage 5 for the line in code, then stages 6 and 7."""
    return act(
        actor, quote_id, request, lambda c: review_picker.set_attribute(c, line_id, body.attribute, Decimal(body.value))
    )


@router.post("/quotes/{quote_id}/lines/{line_id}/resolve")
def resolve_missing(
    actor: Writer, quote_id: QuoteId, line_id: LineId, body: ProductRefIn, request: Request
) -> ActionOut:
    """09 §7.8: a product for a missing line, which becomes an approved component line."""
    return act(actor, quote_id, request, lambda c: review_picker.resolve_missing(c, line_id, body.ref))


@router.post("/quotes/{quote_id}/marks")
def mark_component(actor: Writer, quote_id: QuoteId, body: MarkIn, request: Request) -> ActionOut:
    """09 §6.6: a component the detection missed, marked on the drawing: a manual line there."""
    return act(
        actor,
        quote_id,
        request,
        lambda c: review_picker.mark_component(c, body.page_id, body.bbox, body.ref, body.panel_id),
    )


@router.post("/quotes/{quote_id}/lines/{line_id}/brand-discount")
def set_brand_discount(
    actor: Writer, quote_id: QuoteId, line_id: LineId, body: LineBrandDiscountIn, request: Request
) -> ActionOut:
    """09 §7.13: "כל המוצרים של X: מחירון יצרן פחות __%", from an unpriced line."""
    return act(
        actor, quote_id, request, lambda c: review_picker.set_brand_discount(c, line_id, Decimal(body.discount_pct))
    )


# --- prices, costs, suppliers (09 §7.13–7.15) -----------------------------------------------------------------------


@router.post("/quotes/{quote_id}/lines/{line_id}/price")
def change_line_price(
    actor: Writer, quote_id: QuoteId, line_id: LineId, body: LinePriceIn, request: Request
) -> ActionOut:
    """A line's sale price changed in the review screen (07 §7.2.3, 09 §7.14): for this quote only, or in the price
    list too."""
    return act(
        actor, quote_id, request, lambda c: review.change_price(c, line_id, Decimal(body.unit_price), body.scope)
    )


@router.post("/quotes/{quote_id}/lines/{line_id}/price-entry")
def enter_price(actor: Writer, quote_id: QuoteId, line_id: LineId, body: PriceEntryIn, request: Request) -> ActionOut:
    """A price typed in the row of a line with none (S23 decision 3)."""
    return act(actor, quote_id, request, lambda c: review.enter_price(c, line_id, Decimal(body.unit_price), body.save))


@router.post("/quotes/{quote_id}/lines/{line_id}/cost")
def enter_cost(actor: Writer, quote_id: QuoteId, line_id: LineId, body: CostEntryIn, request: Request) -> ActionOut:
    """09 §6.4 "שמור עלות": to the price list, for every line of the product (09 §7.13)."""
    return act(
        actor, quote_id, request, lambda c: review.enter_cost(c, line_id, Decimal(body.unit_cost), body.supplier)
    )


@router.post("/quotes/{quote_id}/lines/{line_id}/list-price")
def take_list_price(actor: Writer, quote_id: QuoteId, line_id: LineId, request: Request) -> ActionOut:
    """07 §7.2.3 "עדכן בהצעה": the price list's price today."""
    return act(actor, quote_id, request, lambda c: review.take_list_price(c, line_id))


@router.post("/quotes/{quote_id}/lines/{line_id}/supplier")
def choose_supplier(
    actor: Writer, quote_id: QuoteId, line_id: LineId, body: LineSupplierIn, request: Request
) -> ActionOut:
    """09 §7.15: another of the product's suppliers, for this quote only."""
    return act(actor, quote_id, request, lambda c: review.choose_supplier(c, line_id, body.supplier_price_id))


@router.post("/quotes/{quote_id}/lines/{line_id}/supplier/preferred")
def make_preferred(actor: Writer, quote_id: QuoteId, line_id: LineId, request: Request) -> ActionOut:
    """09 §7.15 "הפוך למועדף במחירון"."""
    return act(actor, quote_id, request, lambda c: review.make_preferred(c, line_id))


# --- undo, versions -------------------------------------------------------------------------------------------------


@router.post("/quotes/{quote_id}/undo/{event_id}")
def undo(actor: Writer, quote_id: QuoteId, event_id: EventId, request: Request) -> ActionOut:
    """09 §7.11: takes the action back. After sending, nothing before it is undone."""
    return act(actor, quote_id, request, lambda c: review.undo(c, event_id))


def _versions(actor: Actor, quote_id: str, request: Request, call: Callable[[], Any]) -> QuoteOut:
    try:
        call()
    except quote_versions.VersionError as e:
        raise ApiError(e.status, e.code) from e
    return quote_out(actor, quote_id, request.app.state.storage)


@router.post("/quotes/{quote_id}/send")
def send_quote(actor: Sender, quote_id: QuoteId, request: Request) -> QuoteOut:
    """09 §7.12: the version locked (07 §7.7). The only action with no undo."""
    who = quote_versions.Actor(actor.tenant_id, actor.user_id)
    return _versions(actor, quote_id, request, lambda: quote_versions.send(actor.session, who, quote_id))


@router.post("/quotes/{quote_id}/versions")
def open_next_version(actor: Sender, quote_id: QuoteId, request: Request) -> QuoteOut:
    """ "פתח גרסה N+1": a draft copy of the sent version, which stays as it was sent."""
    who = quote_versions.Actor(actor.tenant_id, actor.user_id)
    return _versions(actor, quote_id, request, lambda: quote_versions.open_next(actor.session, who, quote_id))


def _recalculation(actor: Actor, quote_id: str, request: Request, apply: bool) -> dict[str, Any]:
    try:
        return quote_versions.recalculate_draft(
            actor.session, request.app.state.storage, actor.tenant_id, quote_id, apply
        )
    except quote_versions.VersionError as e:
        raise ApiError(e.status, e.code) from e


@router.get("/quotes/{quote_id}/recalculation")
def preview_recalculation(actor: Reader, quote_id: QuoteId, request: Request) -> RecalculationOut:
    """07 §7.2.3: what "חישוב מחדש" would change. Nothing is written."""
    return RecalculationOut.model_validate(_recalculation(actor, quote_id, request, apply=False))


@router.post("/quotes/{quote_id}/recalculation")
def recalculate(actor: Writer, quote_id: QuoteId, request: Request) -> QuoteOut:
    """Every line of the draft priced from the list today, keeping the estimator's edits."""
    _recalculation(actor, quote_id, request, apply=True)
    return quote_out(actor, quote_id, request.app.state.storage)


# --- the read model -------------------------------------------------------------------------------------------------

COST_FIELDS = ("unit_cost", "line_cost", "margin_pct", "unit_margin", "cost_source")


def quote_out(actor: Actor, quote_id: str, storage: Storage) -> QuoteOut:
    view = quotes.read_quote(actor.session, actor.tenant_id, quote_id)
    if view is None:
        raise ApiError(404, "not_found")
    costs = allowed(actor.role, Permission.COSTS_READ)
    nested = ("panels", "totals", "findings", "pages", "can_see_costs", "first_quote")
    fields = {k: getattr(view, k) for k in QuoteOut.model_fields if k not in nested}
    return QuoteOut.model_validate(
        {
            **fields,
            "can_see_costs": costs,
            "first_quote": view.status == "draft" and onboarding.first_quote(actor.session, actor.tenant_id),
            "findings": [f.__dict__ for f in view.findings],
            "panels": [
                {
                    "panel_id": p.panel_id,
                    "name": p.name,
                    "lines": [_line(ln, costs) for ln in p.lines],
                    "totals": _sums(p.sums, costs),
                    "removed": [r.__dict__ for r in p.removed],
                }
                for p in view.panels
            ],
            "totals": _totals(view.totals, costs),
            "pages": [_page(p, storage, actor.tenant_id) for p in view.pages],
        }
    )


# The strip loads thumbnails lazily, maybe minutes after the quote (09 §14): an hour, and the screen refetches the
# quote when the window regains focus.
THUMBNAIL_URL_SECONDS = 3600


def _page(p: quotes.PageView, storage: Storage, tenant_id: str) -> dict[str, Any]:
    out = {k: v for k, v in p.__dict__.items() if k != "thumbnail_key"}
    out["panels"] = [pn.__dict__ for pn in p.panels]
    out["thumbnail_url"] = (
        storage.presigned_get(tenant_id, p.thumbnail_key, THUMBNAIL_URL_SECONDS) if p.thumbnail_key else None
    )
    return out


def _line(ln: quotes.LineView, costs: bool) -> dict[str, Any]:
    out = {
        **ln.__dict__,
        "sources": [s.__dict__ for s in ln.sources],
        "boxes": [b.__dict__ for b in ln.boxes],
        "suppliers": [s.__dict__ for s in ln.suppliers] if costs else [],
        "price_hints": [h.__dict__ for h in ln.price_hints],
    }
    if not costs:  # 09 §12: the server sends no cost at all, not a hidden one
        out |= dict.fromkeys(COST_FIELDS) | {"below_floor": False}
    return out


def _sums(s: Sums, costs: bool) -> dict[str, Any]:
    return {
        "cost_total": s.cost_total if costs else None,
        "price_total": s.price_total,
        "line_counts": s.line_counts,
        "unpriced_count": s.unpriced_count,
        "uncosted_count": s.uncosted_count,
    }


def _totals(q: QuoteSums, costs: bool) -> dict[str, Any]:
    return {
        **_sums(q.sums, costs),
        "discount_pct": q.discount_pct,
        "discount": q.discount,
        "net_total": q.net_total,
        "margin_abs": q.margin_abs if costs else None,
        "margin_pct": q.margin_pct if costs else None,
        "vat_rate": q.vat_rate,
        "vat": q.vat,
        "gross_total": q.gross_total,
    }
