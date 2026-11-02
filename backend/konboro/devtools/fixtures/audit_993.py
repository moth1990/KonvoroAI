"""The 26-993 audit as a seeded fixture, so the audit screen (S16) never waits for the pipeline.

`audit_993.json` is what stages 1–4 and the audit step write for 26-993 and the factory's quote 10271 on replay
(S16 decision 2: the product's own result, BUG-031 included, not the golden labels). `python -m eval.audit_fixture`
(`make fixture-audit`) writes it again. Every row goes in under a fresh id, so each tenant gets its own copy and
its own decisions. The page images have the title block blanked; neither uploaded file is in S3.

Safe to rerun: a tenant that already has the fixture drawing is left alone.
"""

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from PIL import Image
from sqlalchemy import inspect, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.pipeline.extraction import deepzoom
from konboro.pipeline.extraction.config import DEFAULT as EXTRACTION
from konboro.pipeline.intake.pages import png
from konboro.pipeline.stages.s1_intake import THUMB_PX, thumbnail_key
from konboro.services.storage import Storage, drawing_key

FIXTURE = Path(__file__).with_name("audit_993.json")
PAGE_IMAGES = Path(__file__).with_name("audit_993_pages")
PAGE_PX = 1400  # as wide as the NURSERY-1 fixture's pages
MARKER = "fixture:26-993"  # drawings.trace_id of the fixture drawing
FLAG = "quote_audit"
PLACEHOLDER_TENANT, PLACEHOLDER_USER = "{tenant}", "{user}"

# (fixture key, model), in foreign-key order
TABLES: list[tuple[str, type[Any]]] = [
    ("project", m.Project),
    ("drawing", m.Drawing),
    ("files", m.DrawingFile),
    ("pages", m.Page),
    ("panels", m.Panel),
    ("components", m.Component),
    ("stage_runs", m.StageRun),
    ("audit", m.Audit),
    ("audit_quote_lines", m.AuditQuoteLine),
    ("audit_differences", m.AuditDifference),
]


def load() -> dict[str, list[dict[str, Any]]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _fresh_ids(fixture: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    """Every row id in the fixture → a new one with the same prefix (00 §6.1)."""
    return {
        row["id"]: new_id(row["id"].split("_", 1)[0])
        for _, rows in fixture.items()
        for row in rows
        if isinstance(row.get("id"), str)
    }


def _swap(value: Any, ids: dict[str, str]) -> Any:
    """`value` with every id (as a whole string, a list item or a dict key) replaced."""
    if isinstance(value, str):
        return ids.get(value, value)
    if isinstance(value, list):
        return [_swap(v, ids) for v in value]
    if isinstance(value, dict):
        return {ids.get(k, k): _swap(v, ids) for k, v in value.items()}
    return value


def _typed(model: type[Any], row: dict[str, Any]) -> dict[str, Any]:
    """JSON back to the columns' Python types: money and quantities as `Decimal`, never float (07)."""
    columns = {a.key: a.columns[0] for a in inspect(model).column_attrs}
    out = {}
    for key, value in row.items():
        kind = columns[key].type.python_type if value is not None else None
        if kind is Decimal:
            value = Decimal(value)
        elif kind is datetime and isinstance(value, str):
            value = datetime.fromisoformat(value)
        elif kind is date and isinstance(value, str):
            value = date.fromisoformat(value)
        out[key] = value
    return out


def enable_flag(session: Session, tenant_id: str) -> None:
    """Turns the audit on for a tenant that existed before the flag, as the NURSERY-1 fixture does."""
    session.execute(
        insert(m.TenantFeatureOverride)
        .values(tenant_id=tenant_id, flag_key=FLAG, enabled=True, reason="fixture")
        .on_conflict_do_nothing(index_elements=["tenant_id", "flag_key"])
    )


def seed_audit_993(session: Session, tenant_id: str, user_id: str, audit_id: str | None = None) -> str | None:
    """Writes the fixture's rows into `tenant_id` and returns the new audit's id; None when the tenant has it.
    `audit_id` fixes the audit's id (the E2E tenants, so a test can open it); every other id is new."""
    if session.scalar(select(m.Drawing.id).where(m.Drawing.tenant_id == tenant_id, m.Drawing.trace_id == MARKER)):
        return None
    fixture = load()
    ids = _fresh_ids(fixture) | {PLACEHOLDER_TENANT: tenant_id, PLACEHOLDER_USER: user_id}
    if audit_id is not None:
        ids[fixture["audit"][0]["id"]] = audit_id
    for key, model in TABLES:
        for row in fixture[key]:
            obj = model(**_typed(model, _swap(row, ids)))
            obj.tenant_id = tenant_id
            if key == "drawing":
                obj.trace_id, obj.created_by = MARKER, user_id
            if key == "files":
                obj.storage_key = drawing_key(tenant_id, obj.drawing_id, "files", obj.id)  # never written
            session.add(obj)
        session.flush()
    return ids[fixture["audit"][0]["id"]]


def seed_audit_993_pages(session: Session, storage: Storage, tenant_id: str) -> int:
    """Each page's render, thumbnail and viewer pyramid in S3, where stage 2 would put them, as the NURSERY-1
    fixture does (`seed_nursery_pages`). Safe to rerun. Returns the number of pages written."""
    drawing_id = session.scalar(
        select(m.Drawing.id).where(m.Drawing.tenant_id == tenant_id, m.Drawing.trace_id == MARKER)
    )
    if drawing_id is None:
        return 0
    written = 0
    tile, overlap = EXTRACTION.dzi_tile_px, EXTRACTION.dzi_overlap_px
    for page in session.scalars(select(m.Page).where(m.Page.tenant_id == tenant_id, m.Page.drawing_id == drawing_id)):
        base = drawing_key(tenant_id, drawing_id, "pages", page.id) + "/"
        if page.tiles_prefix is not None and storage.exists(tenant_id, base + "dz/index.json"):
            continue
        image = Image.open(PAGE_IMAGES / f"p{page.page_no}.jpg").convert("RGB")
        thumb = image.copy()
        thumb.thumbnail((THUMB_PX, THUMB_PX))
        storage.put(tenant_id, thumbnail_key(tenant_id, drawing_id, page.id), png(thumb), "image/png")
        storage.put(tenant_id, base + "render.png", png(image), "image/png")
        storage.put(
            tenant_id,
            base + "dz/page.dzi",
            deepzoom.descriptor(image.width, image.height, tile, overlap),
            "application/xml",
        )
        packed, index = deepzoom.pack(image, tile, overlap)
        storage.put(tenant_id, base + "dz/tiles.bin", packed)
        storage.put(tenant_id, base + "dz/index.json", index, "application/json")
        page.render_key, page.tiles_prefix = base + "render.png", base + "tiles/"
        written += 1
    session.flush()
    return written
