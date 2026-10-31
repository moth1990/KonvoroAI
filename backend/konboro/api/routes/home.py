"""Home screen data: recent quotes and the "waiting for you" card (prototype `vHome`, `vHomeChat`)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from konboro.domain.permissions import Permission
from konboro.services import home

from ..deps import Actor, require
from ..errors import ERROR_RESPONSES
from ..schemas import HomeSummaryOut, QuoteList, QuoteListItem

router = APIRouter(tags=["home"], responses=ERROR_RESPONSES)

QuotesReader = Annotated[Actor, Depends(require(Permission.QUOTES_READ))]


@router.get("/quotes")
def list_quotes(actor: QuotesReader, limit: Annotated[int, Query(ge=1, le=50)] = 10) -> QuoteList:
    """The tenant's quotes, most recently changed first."""
    rows = home.recent_quotes(actor.session, actor.tenant_id, limit)
    return QuoteList(items=[QuoteListItem.model_validate(r, from_attributes=True) for r in rows])


@router.get("/home/summary")
def home_summary(actor: QuotesReader) -> HomeSummaryOut:
    return HomeSummaryOut.model_validate(home.summary(actor.session, actor.tenant_id), from_attributes=True)
