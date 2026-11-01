"""A page's Deep Zoom pyramid for the review screen's drawing viewer (09 §6.5, 12 §6; OpenSeadragon reads it).

OpenSeadragon asks for `page.dzi`, then `page_files/{level}/{col}_{row}.png`, with the bearer token on every request
(`ajaxHeaders`). Another tenant's page, a page stage 2 has not rendered, and a tile outside the pyramid are all 404.
Behind `review_screen` until S23, like the screen (S09 decision 2).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request, Response

from konboro.domain.permissions import Permission
from konboro.services import viewer
from konboro.services.storage import Storage

from ..deps import Actor, require, require_flag
from ..errors import ERROR_RESPONSES, ApiError

router = APIRouter(tags=["pages"], responses=ERROR_RESPONSES, dependencies=[Depends(require_flag("review_screen"))])

Reader = Annotated[Actor, Depends(require(Permission.DRAWINGS_READ))]
PageId = Annotated[str, Path(pattern=r"^pg_[0-9A-Z]{26}$")]

# The pyramid of a page never changes (services/viewer.py), and it is the tenant's own: cache it in the browser only.
CACHE = {"Cache-Control": "private, max-age=86400, immutable"}
_PNG: dict[int | str, dict[str, Any]] = {200: {"content": {"image/png": {}}, "description": "One tile"}}
_DZI: dict[int | str, dict[str, Any]] = {
    200: {"content": {"application/xml": {}}, "description": "The Deep Zoom descriptor"}
}


def _pyramid(actor: Actor, page_id: str) -> viewer.Pyramid:
    p = viewer.pyramid(actor.session, actor.tenant_id, page_id)
    if p is None:
        raise ApiError(404, "not_found")
    return p


@router.get("/pages/{page_id}/dz/page.dzi", response_class=Response, responses=_DZI)
def page_dzi(actor: Reader, page_id: PageId, request: Request) -> Response:
    storage: Storage = request.app.state.storage
    p = _pyramid(actor, page_id)
    return Response(storage.get(actor.tenant_id, p.key("page.dzi")), media_type="application/xml", headers=CACHE)


@router.get("/pages/{page_id}/dz/page_files/{level}/{col}_{row}.png", response_class=Response, responses=_PNG)
def page_tile(
    actor: Reader,
    page_id: PageId,
    level: Annotated[int, Path(ge=0, le=30)],
    col: Annotated[int, Path(ge=0)],
    row: Annotated[int, Path(ge=0)],
    request: Request,
) -> Response:
    storage: Storage = request.app.state.storage
    body = viewer.tile(storage, request.app.state.tile_indexes, _pyramid(actor, page_id), level, col, row)
    if body is None:
        raise ApiError(404, "not_found")
    return Response(body, media_type="image/png", headers=CACHE)
