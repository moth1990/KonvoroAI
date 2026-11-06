"""Home screen data: recent quotes and the "waiting for you" card (prototype `vHome`, `vHomeChat`)."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from konboro.domain.permissions import Permission
from konboro.services import flags, home, home_route
from konboro.services import llm as llm_service
from konboro_llm import LLMClient

from ..deps import Actor, require, require_flag
from ..errors import ERROR_RESPONSES
from ..schemas import HomeRouteIn, HomeRouteOut, HomeSummaryOut, QuoteList, QuoteListItem

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


@router.post("/home/route", dependencies=[Depends(require_flag("home_chat"))])
def route_request(actor: QuotesReader, body: HomeRouteIn, request: Request) -> HomeRouteOut:
    """13 §4.3: where a request typed on the chat home goes. A suggestion, never an action: the screen navigates, or
    shows the question and its choices."""
    llm = LLMClient(
        request.app.state.llm_providers, on_call=llm_service.usage_recorder(request.app.state.engine, actor.tenant_id)
    )
    on = flags.tenant_flags(actor.session, actor.tenant_id)
    out = home_route.route(actor.session, llm, actor.tenant_id, body.text, on)
    return HomeRouteOut.model_validate(asdict(out))
