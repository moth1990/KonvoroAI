"""The customer PDF's template on the settings screen (13 §4.1, §6 item 2; S26 decision 1): the factory's details,
terms, the SKU setting and its logo. Behind `export_doc`, like the export itself: off, the routes don't exist."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile

from konboro.domain.permissions import Permission
from konboro.services import document_template as dt
from konboro.services.storage import Storage

from ..deps import Actor, require, require_flag
from ..errors import ERROR_RESPONSES, ApiError
from ..schemas import CompanyDetails, DocumentSettingsIn, DocumentSettingsOut

FLAG = "export_doc"
LOGO_URL_SECONDS = 300

router = APIRouter(
    prefix="/settings/document",
    tags=["settings"],
    responses=ERROR_RESPONSES,
    dependencies=[Depends(require_flag(FLAG))],
)
Reader = Annotated[Actor, Depends(require(Permission.SETTINGS_READ))]
Writer = Annotated[Actor, Depends(require(Permission.SETTINGS_WRITE))]


def document_out(actor: Actor, storage: Storage) -> DocumentSettingsOut:
    t = dt.read(actor.session, actor.tenant_id)
    logo = bool(t.logo_key) and storage.exists(actor.tenant_id, str(t.logo_key))
    return DocumentSettingsOut(
        company=CompanyDetails(name=t.name, company_id=t.company_id, address=t.address, phone=t.phone),
        terms=t.terms,
        show_sku=t.show_sku,
        logo_url=storage.presigned_get(actor.tenant_id, t.logo_key, LOGO_URL_SECONDS) if logo and t.logo_key else None,
    )


@router.get("")
def get_document(actor: Reader, request: Request) -> DocumentSettingsOut:
    return document_out(actor, request.app.state.storage)


@router.put("")
def put_document(body: DocumentSettingsIn, actor: Writer, request: Request) -> DocumentSettingsOut:
    dt.save(actor.session, actor.tenant_id, body.company.model_dump(), body.terms, body.show_sku)
    return document_out(actor, request.app.state.storage)


@router.put("/logo")
def put_logo(
    actor: Writer, request: Request, file: Annotated[UploadFile, File(description="PNG or JPEG, up to 1 MB")]
) -> DocumentSettingsOut:
    data = file.file.read(dt.LOGO_MAX_BYTES + 1)
    try:
        dt.set_logo(actor.session, request.app.state.storage, actor.tenant_id, data)
    except dt.LogoError as e:
        raise ApiError(422, e.code) from e
    return document_out(actor, request.app.state.storage)


@router.delete("/logo")
def delete_logo(actor: Writer, request: Request) -> DocumentSettingsOut:
    dt.clear_logo(actor.session, request.app.state.storage, actor.tenant_id)
    return document_out(actor, request.app.state.storage)
