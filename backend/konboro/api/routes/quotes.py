"""One quote for the review screen (09 §4–6, prototype `vReview`). Behind `review_screen` until S23 (S09 decision 2)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request

from konboro.domain.permissions import Permission
from konboro.domain.totals import QuoteSums, Sums
from konboro.services import quotes
from konboro.services.storage import Storage

from ..deps import Actor, require, require_flag
from ..errors import ERROR_RESPONSES, ApiError
from ..schemas import QuoteOut

router = APIRouter(tags=["quotes"], responses=ERROR_RESPONSES)

Reader = Annotated[Actor, Depends(require(Permission.QUOTES_READ))]
QuoteId = Annotated[str, Path(pattern=r"^quo_[0-9A-Z]{26}$")]


@router.get("/quotes/{quote_id}", dependencies=[Depends(require_flag("review_screen"))])
def get_quote(actor: Reader, quote_id: QuoteId, request: Request) -> QuoteOut:
    """The quote's current version. Another tenant's quote is 404, the same as one that does not exist."""
    view = quotes.read_quote(actor.session, actor.tenant_id, quote_id)
    if view is None:
        raise ApiError(404, "not_found")
    storage: Storage = request.app.state.storage
    nested = ("panels", "totals", "findings", "pages")
    fields = {k: getattr(view, k) for k in QuoteOut.model_fields if k not in nested}
    return QuoteOut.model_validate(
        {
            **fields,
            "findings": [f.__dict__ for f in view.findings],
            "panels": [
                {
                    "panel_id": p.panel_id,
                    "name": p.name,
                    "lines": [_line(ln) for ln in p.lines],
                    "totals": _sums(p.sums),
                }
                for p in view.panels
            ],
            "totals": _totals(view.totals),
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


def _line(ln: quotes.LineView) -> dict[str, Any]:
    return {**ln.__dict__, "sources": [s.__dict__ for s in ln.sources], "boxes": [b.__dict__ for b in ln.boxes]}


def _sums(s: Sums) -> dict[str, Any]:
    return {
        "cost_total": s.cost_total,
        "price_total": s.price_total,
        "line_counts": s.line_counts,
        "unpriced_count": s.unpriced_count,
        "uncosted_count": s.uncosted_count,
    }


def _totals(q: QuoteSums) -> dict[str, Any]:
    return {
        **_sums(q.sums),
        "discount_pct": q.discount_pct,
        "discount": q.discount,
        "net_total": q.net_total,
        "margin_abs": q.margin_abs,
        "margin_pct": q.margin_pct,
        "vat_rate": q.vat_rate,
        "vat": q.vat,
        "gross_total": q.gross_total,
    }
