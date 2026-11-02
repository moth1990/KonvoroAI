"""`make fixture-audit`: the 26-993 audit as the pipeline makes it on replay, written as the seed's fixture (S16
decision 2). The audit screen's E2E tests and its fidelity shots read it, so they never wait for stages 1–4.

Runs the eval's way (`konboro_eval`, replay cassettes, `Pipeline.run_inline`): the drawing and the factory's quote
10271 go up through `drawings.create_upload` as an audit, stages 1–4 and the audit step run, and every row they
wrote is dumped to `konboro/devtools/fixtures/audit_993.json`. The seed (`fixtures.audit_993`) loads it under fresh
ids. Page images go to `audit_993_pages/`, rendered from the PDF with the title block blanked: it names the
designer, the draftsman and the approver, which no tenant may hold. Neither file of the upload is kept.

Run it again after a change to stages 1–4 or the audit moves 26-993's result; `make eval` says when it does.
"""

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
from PIL import Image, ImageDraw
from sqlalchemy import inspect, select
from sqlalchemy.orm import DeclarativeBase

from konboro.db import models as m
from konboro.db.session import tenant_session
from konboro.devtools.fixtures.audit_993 import FIXTURE, PAGE_IMAGES, PAGE_PX, PLACEHOLDER_TENANT, PLACEHOLDER_USER
from konboro.pipeline.coordinator import Pipeline
from konboro.services import drawings
from konboro.services.llm import eval_providers
from konboro.services.queue import Queue, StageMessage
from konboro.services.storage import Storage

from .normalizers import GOLDEN
from .run import CASSETTES, add_tenant, eval_settings, prepare

DRAWING = "26-993"
QUOTE = "actual_quote_10271.pdf"
SKIPPED = {"tenant_id", "created_at", "updated_at", "storage_key", "render_key", "tiles_prefix", "output_key"}
# Stage 1's title block fields that name no person (golden/26-993/README.md: the people are never kept)
TITLE_STRIP = 0.78  # the share of the page's height above the title block
# More to blank, as shares of the page (x0, y0, x1, y1): the front view's label with the factory's name and phones.
# No customer, factory or person name from a real drawing goes into a tenant (as for NURSERY-1).
NAME_BOXES = {2: [(0.29, 0.12, 0.53, 0.26)]}
TITLE_BLOCK_KEEP = {"drawing_number", "panel_name", "date", "revision", "sheet", "sheet_count", "project_name"}


def rows(objs: list[Any]) -> list[dict[str, Any]]:
    out = []
    for obj in objs:
        row = {}
        for attr in inspect(obj).mapper.column_attrs:
            if attr.key in SKIPPED:
                continue
            value = getattr(obj, attr.key)
            row[attr.key] = str(value) if isinstance(value, Decimal) else value
        out.append(row)
    return out


def _scrub(title_block: dict[str, Any] | None) -> dict[str, Any] | None:
    return {k: v for k, v in title_block.items() if k in TITLE_BLOCK_KEEP} if title_block else title_block


def generate(golden: Path = GOLDEN) -> dict[str, Any]:
    settings = eval_settings()
    engine = prepare()
    storage = Storage(settings)
    storage.reset_local_bucket()
    pipeline = Pipeline(settings, engine, storage, Queue(settings), llm_providers=eval_providers("replay", CASSETTES))
    tenant_id, user_id = add_tenant(engine)
    folder = golden / DRAWING
    with tenant_session(tenant_id, engine) as s:
        # the file and project names the eval uploads under, so every request matches its cassette
        new = drawings.create_upload(
            s,
            storage,
            tenant_id=tenant_id,
            user_id=user_id,
            files=[(f"{DRAWING}.pdf", (folder / f"{DRAWING}.pdf").read_bytes())],
            project_name=DRAWING,
            audited_quote=(QUOTE, (folder / QUOTE).read_bytes()),
        )
        drawing_id, trace_id = new.drawing.id, str(new.drawing.trace_id)
    pipeline.run_inline(StageMessage(drawing_id=drawing_id, tenant_id=tenant_id, stage=1, trace_id=trace_id))

    with tenant_session(tenant_id, engine) as s:

        def of(model: type[DeclarativeBase], *order: Any) -> list[Any]:
            q = select(model).where(model.drawing_id == drawing_id)  # type: ignore[attr-defined]
            return list(s.scalars(q.order_by(*order)))

        drawing = s.scalars(select(m.Drawing).where(m.Drawing.id == drawing_id)).one()
        assert drawing.status == "ready", drawing.issues  # noqa: S101
        audit = s.scalars(select(m.Audit).where(m.Audit.drawing_id == drawing_id)).one()
        project = s.scalars(select(m.Project).where(m.Project.id == drawing.project_id)).one()
        fixture: dict[str, Any] = {
            "project": rows([project]),
            "drawing": rows([drawing]),
            "files": rows(list(s.scalars(select(m.DrawingFile).where(m.DrawingFile.drawing_id == drawing_id)))),
            "pages": rows(of(m.Page, m.Page.page_no)),
            "panels": rows(of(m.Panel, m.Panel.id)),
            "components": rows(of(m.Component, m.Component.id)),
            "stage_runs": rows(of(m.StageRun, m.StageRun.stage)),
            "audit": rows([audit]),
            "audit_quote_lines": rows(
                list(
                    s.scalars(
                        select(m.AuditQuoteLine)
                        .where(m.AuditQuoteLine.audit_id == audit.id)
                        .order_by(m.AuditQuoteLine.line_index)
                    )
                )
            ),
            "audit_differences": rows(
                list(
                    s.scalars(
                        select(m.AuditDifference)
                        .where(m.AuditDifference.audit_id == audit.id)
                        .order_by(m.AuditDifference.id)
                    )
                )
            ),
        }
    engine.dispose()

    # names as the prototype shows them (`vAudit`); no person from the title block
    fixture["project"][0]["name"] = "MAIN ELECTRICAL BOARD"
    for f in fixture["files"]:
        f["original_name"] = "Hatzaa_10271.pdf" if f["role"] == "audited_quote" else "MAIN_ELECTRICAL_BOARD.pdf"
    fixture["drawing"][0]["title_block"] = _scrub(fixture["drawing"][0]["title_block"])
    fixture["drawing"][0]["issues"] = []
    for p in fixture["pages"]:
        p["title_block"] = _scrub(p["title_block"])
    text = json.dumps(fixture, ensure_ascii=False, indent=1, default=str, sort_keys=True)
    text = text.replace(tenant_id, PLACEHOLDER_TENANT).replace(user_id, PLACEHOLDER_USER)
    return json.loads(text)  # type: ignore[no-any-return]


def render_pages(fixture: dict[str, Any], pdf: Path, out: Path) -> None:
    """Each page at `PAGE_PX` wide, its title block painted white. The boxes are stage 1's (`regions`); a page with
    none has its bottom strip blanked across the whole width, where this drawing's title block and the factory's
    name are."""
    out.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(str(pdf))
    for page in fixture["pages"]:
        n = page["page_no"]
        pdf_page = doc[n - 1]
        width_pt, height_pt = pdf_page.get_size()
        image = pdf_page.render(scale=PAGE_PX / width_pt).to_pil().convert("RGB")
        k = image.width / width_pt
        draw = ImageDraw.Draw(image)
        boxes = [r["bbox"] for r in page["regions"] if r.get("region_kind") == "title_block" and r.get("bbox")]
        if not boxes:
            boxes = [[0, height_pt * TITLE_STRIP, width_pt, height_pt]]
        boxes += [[a * width_pt, b * height_pt, c * width_pt, d * height_pt] for a, b, c, d in NAME_BOXES.get(n, [])]
        for x0, y0, x1, y1 in boxes:
            draw.rectangle([x0 * k, y0 * k, x1 * k, y1 * k], fill="white")
        image.save(out / f"p{n}.jpg", quality=82, optimize=True)
        Image.open(out / f"p{n}.jpg").verify()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the 26-993 audit fixture (S16)")
    parser.parse_args(argv)
    fixture = generate()
    FIXTURE.write_text(json.dumps(fixture, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    render_pages(fixture, GOLDEN / DRAWING / f"{DRAWING}.pdf", PAGE_IMAGES)
    s = fixture["audit"][0]["summary"]
    print(f"wrote {FIXTURE.name}: {len(fixture['audit_differences'])} differences, summary {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
