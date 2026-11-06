"""The quote's documents (13 §4.1, behind `export_doc`; S26): its versions, the customer document's preview, the
customer PDF and the internal Excel, for any version (S26 decision 2). Off, the routes don't exist (13 §3).

The Excel has costs, margins and suppliers, so it also needs cost permission (07 §12); the PDF and its preview have
none of them. Each download writes a log line, which is how the flag is measured for now (13 §3 rule 4, S26 decision 6).
"""

import logging
from typing import Annotated
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Depends, Path, Request, Response

from konboro.domain.permissions import Permission
from konboro.services import document_template as dt
from konboro.services import export, export_pdf, export_xlsx

from ..deps import Actor, require, require_flag
from ..errors import ERROR_RESPONSES, ApiError
from ..schemas import DocumentOut, VersionOut
from .quotes import QuoteId

FLAG = "export_doc"
PDF = "application/pdf"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
log = logging.getLogger("konboro.export")

router = APIRouter(tags=["export"], responses=ERROR_RESPONSES, dependencies=[Depends(require_flag(FLAG))])
Reader = Annotated[Actor, Depends(require(Permission.QUOTES_READ))]
CostReader = Annotated[Actor, Depends(require(Permission.COSTS_READ))]
VersionNo = Annotated[int, Path(ge=1, le=10_000)]


def _doc(actor: Actor, quote_id: str, version: int) -> export.Document:
    doc = export.build(actor.session, actor.tenant_id, quote_id, version)
    if doc is None:
        raise ApiError(404, "not_found")
    return doc


def _attachment(body: bytes, media_type: str, name: str, ascii_name: str) -> Response:
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{urlquote(name)}"
    return Response(body, media_type=media_type, headers={"Content-Disposition": disposition})


def _logged(actor: Actor, doc: export.Document, kind: str) -> None:
    log.info(
        "export_doc download",
        extra={
            "tenant_id": actor.tenant_id,
            "user_id": actor.user_id,
            "quote_id": doc.quote_id,
            "version": doc.version,
            "format": kind,
        },
    )


@router.get("/quotes/{quote_id}/versions")
def list_versions(actor: Reader, quote_id: QuoteId) -> list[VersionOut]:
    """The quote's versions, newest first, for the export modal's selector."""
    rows = export.versions(actor.session, actor.tenant_id, quote_id)
    if rows is None:
        raise ApiError(404, "not_found")
    newest = max((v.version for v in rows), default=0)
    return [
        VersionOut(
            version=v.version,
            status=v.status,  # type: ignore[arg-type]
            quote_date=v.quote_date,
            sent_at=v.sent_at,
            current=v.version == newest,
        )
        for v in rows
    ]


@router.get("/quotes/{quote_id}/versions/{version}/document")
def get_document(actor: Reader, quote_id: QuoteId, version: VersionNo) -> DocumentOut:
    """The customer document of the version, as the PDF prints it (the modal's preview)."""
    doc = _doc(actor, quote_id, version)
    q = doc.totals
    sku = doc.template.show_sku
    return DocumentOut.model_validate(
        {
            "name": doc.name,
            "drawing_number": doc.drawing_number,
            "customer": doc.customer,
            "version": doc.version,
            "draft": doc.draft,
            "quote_date": doc.quote_date,
            "company": doc.template.name,
            "show_sku": sku,
            "sections": [
                {
                    "name": s.name,
                    "rows": [
                        {
                            "description": r.description,
                            "sku": r.sku if sku else None,
                            "qty": r.qty,
                            "unit_price": r.unit_price,
                            "line_total": r.line_total,
                        }
                        for r in s.rows
                    ],
                    "total": s.total,
                }
                for s in doc.sections
            ],
            "totals": {
                "price_total": q.sums.price_total,
                "discount_pct": q.discount_pct,
                "discount": q.discount,
                "net_total": q.net_total,
                "vat_rate": q.vat_rate,
                "vat": q.vat,
                "gross_total": q.gross_total,
            },
            "unpriced_count": doc.unpriced,
        }
    )


@router.get(
    "/quotes/{quote_id}/versions/{version}/export.pdf",
    response_class=Response,
    responses={200: {"content": {PDF: {}}, "description": "The customer PDF"}},
)
def export_pdf_route(actor: Reader, quote_id: QuoteId, version: VersionNo, request: Request) -> Response:
    """The customer PDF (07 §12): description, SKU by the factory's setting, quantity, prices, discount, VAT."""
    doc = _doc(actor, quote_id, version)
    storage = request.app.state.storage
    logo = dt.logo_bytes(storage, actor.tenant_id, doc.template)
    html = export_pdf.customer_html(doc, (logo, doc.template.logo_type or "image/png") if logo else None)
    body = export_pdf.render_pdf(html)
    _logged(actor, doc, "pdf")
    return _attachment(body, PDF, export.file_name(doc, "pdf"), f"quote-v{doc.version}.pdf")


@router.get(
    "/quotes/{quote_id}/versions/{version}/export.xlsx",
    response_class=Response,
    responses={200: {"content": {XLSX: {}}, "description": "The internal Excel"}},
)
def export_xlsx_route(actor: CostReader, quote_id: QuoteId, version: VersionNo) -> Response:
    """The internal Excel: every line with its cost, price source, colour and tags, the findings and the totals."""
    doc = _doc(actor, quote_id, version)
    body = export_xlsx.workbook(doc)
    _logged(actor, doc, "xlsx")
    return _attachment(body, XLSX, export.file_name(doc, "xlsx"), f"quote-v{doc.version}-internal.xlsx")
