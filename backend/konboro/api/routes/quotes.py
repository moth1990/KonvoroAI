"""One quote for the review screen (09 §4–6, prototype `vReview`). Behind `review_screen` until S23 (S09 decision 2)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path

from konboro.domain.permissions import Permission
from konboro.domain.totals import QuoteSums, Sums
from konboro.services import quotes

from ..deps import Actor, require, require_flag
from ..errors import ERROR_RESPONSES, ApiError
from ..schemas import QuoteOut

router = APIRouter(tags=["quotes"], responses=ERROR_RESPONSES)

Reader = Annotated[Actor, Depends(require(Permission.QUOTES_READ))]
QuoteId = Annotated[str, Path(pattern=r"^quo_[0-9A-Z]{26}$")]


@router.get("/quotes/{quote_id}", dependencies=[Depends(require_flag("review_screen"))])
def get_quote(actor: Reader, quote_id: QuoteId) -> QuoteOut:
    """The quote's current version. Another tenant's quote is 404, the same as one that does not exist."""
    view = quotes.read_quote(actor.session, actor.tenant_id, quote_id)
    if view is None:
        raise ApiError(404, "not_found")
    fields = {k: getattr(view, k) for k in QuoteOut.model_fields if k not in ("panels", "totals", "findings")}
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
        }
    )


def _line(ln: quotes.LineView) -> dict[str, Any]:
    return {**ln.__dict__, "sources": [s.__dict__ for s in ln.sources]}


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
