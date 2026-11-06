"""The factory's template for the customer PDF (13 §4.1 "לוגו, פרטים, תנאים", §6 item 2; S26 decision 1): its
details, its terms, whether SKUs show (07 §12 "מק"ט לפי הגדרת המפעל"), and its logo. Kept in
`tenant_settings.document`; the logo itself in S3 under the tenant's `branding/`, through `services/storage.py`.

A logo is a PNG or a JPEG of at most 1 MB, told by its bytes and opened with Pillow: an SVG can carry script into the
Chromium that prints the PDF, so it is refused.
"""

import io
from dataclasses import dataclass
from typing import Any

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.services.storage import Storage, tenant_prefix

LOGO_MAX_BYTES = 1024 * 1024
LOGO_MAX_PX = 4000  # either side; a bigger one is a photo, not a logo
LOGO_TYPES = {b"\x89PNG\r\n\x1a\n": ("image/png", "png"), b"\xff\xd8\xff": ("image/jpeg", "jpg")}
DETAIL_FIELDS = ("name", "company_id", "address", "phone")


class LogoError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code  # logo_type, logo_too_large


@dataclass(frozen=True)
class Template:
    name: str
    company_id: str | None = None
    address: str | None = None
    phone: str | None = None
    terms: str | None = None
    show_sku: bool = False  # the prototype's document has no SKU column
    logo_key: str | None = None
    logo_type: str | None = None


def read(session: Session, tenant_id: str) -> Template:
    """The template as saved; the factory's own name until it writes another."""
    tenant = session.get_one(m.Tenant, tenant_id)
    row = session.get(m.TenantSettings, tenant_id)
    doc: dict[str, Any] = dict(row.document) if row else {}
    company = doc.get("company") or {}
    logo = doc.get("logo") or {}
    return Template(
        name=company.get("name") or tenant.name,
        company_id=company.get("company_id") or None,
        address=company.get("address") or None,
        phone=company.get("phone") or None,
        terms=doc.get("terms") or None,
        show_sku=bool(doc.get("show_sku", False)),
        logo_key=logo.get("key"),
        logo_type=logo.get("content_type"),
    )


def _row(session: Session, tenant_id: str) -> m.TenantSettings:
    row = session.get(m.TenantSettings, tenant_id)
    if row is None:
        row = m.TenantSettings(tenant_id=tenant_id)
        session.add(row)
        session.flush()
        session.refresh(row)
    return row


def save(session: Session, tenant_id: str, details: dict[str, str | None], terms: str | None, show_sku: bool) -> None:
    """The details, terms and SKU setting; the logo stays as it is. Blank is not set."""
    row = _row(session, tenant_id)
    doc = dict(row.document)
    doc["company"] = {k: (details.get(k) or "").strip() or None for k in DETAIL_FIELDS}
    doc["terms"] = (terms or "").strip() or None
    doc["show_sku"] = show_sku
    row.document = doc
    session.flush()


def logo_kind(data: bytes) -> tuple[str, str]:
    """(content type, extension) of a PNG or JPEG under the size limit, or `LogoError`."""
    if len(data) > LOGO_MAX_BYTES:
        raise LogoError("logo_too_large")
    kind = next((v for magic, v in LOGO_TYPES.items() if data.startswith(magic)), None)
    if kind is None:
        raise LogoError("logo_type")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
            w, h = image.size
    except (UnidentifiedImageError, OSError, SyntaxError) as e:
        raise LogoError("logo_type") from e
    if max(w, h) > LOGO_MAX_PX:
        raise LogoError("logo_too_large")
    return kind


def set_logo(session: Session, storage: Storage, tenant_id: str, data: bytes) -> None:
    content_type, ext = logo_kind(data)
    row = _row(session, tenant_id)
    doc = dict(row.document)
    old = (doc.get("logo") or {}).get("key")
    key = f"{tenant_prefix(tenant_id)}branding/logo.{ext}"
    storage.put(tenant_id, key, data, content_type)
    if old and old != key:
        storage.delete(tenant_id, old)
    doc["logo"] = {"key": key, "content_type": content_type}
    row.document = doc
    session.flush()


def clear_logo(session: Session, storage: Storage, tenant_id: str) -> None:
    row = _row(session, tenant_id)
    doc = dict(row.document)
    key = (doc.pop("logo", None) or {}).get("key")
    if key:
        storage.delete(tenant_id, key)
    row.document = doc
    session.flush()


def logo_bytes(storage: Storage, tenant_id: str, template: Template) -> bytes | None:
    """The logo for the PDF, or None when there is none or it is gone from storage."""
    if not template.logo_key or not storage.exists(tenant_id, template.logo_key):
        return None
    return storage.get(tenant_id, template.logo_key)
