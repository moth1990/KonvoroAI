"""The API that Playwright runs against: `python -m konboro.devtools.e2e` (started by playwright.config.ts).

It recreates the `konboro_e2e` database, migrates it, loads plans, flags and fixed E2E tenants, and serves
the API on port 8001 (KONBORO_E2E_API_PORT) for the web app on port 5181 (KONBORO_E2E_WEB_PORT), with a pipeline
worker in a thread on its own `e2e-` queues.

Flags are read-only through the API (S03 decision), so each state a test needs is its own tenant with its own
dev login. frontend/e2e/fixtures.ts lists the same emails.
"""

import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, SecretStr
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.orm import Session

from konboro.db.admin import database_dsn, fresh_database
from konboro.db.ids import new_id
from konboro.db.models import (
    Audit,
    AuditDifference,
    Drawing,
    KnowledgeCandidate,
    MarginRule,
    Project,
    QuotaUsage,
    Quote,
    QuoteLine,
    QuoteVersion,
    Tenant,
    TenantFeatureOverride,
    TenantSettings,
    User,
)
from konboro.db.seed import FLAGS, link_demo_catalog, seed_global, seed_price_list
from konboro.db.session import app_engine
from konboro.devtools.fixtures.audit_993 import seed_audit_993, seed_audit_993_pages
from konboro.devtools.fixtures.nursery import (
    seed_earlier_quote,
    seed_missing_line,
    seed_nursery,
    seed_nursery_detections,
    seed_nursery_pages,
)
from konboro.devtools.fixtures.queue import seed_queue
from konboro.domain.flags import CATALOG_LINES
from konboro.pipeline.context import StageContext
from konboro.pipeline.extraction.config import ExtractionConfig
from konboro.pipeline.stages import Stage, s2_extraction
from konboro.services.storage import Storage
from konboro.settings import Settings

DATABASE = "konboro_e2e"
PASSWORD = "konboro-e2e-password"  # noqa: S105 (a test value for the local E2E API only)


@dataclass(frozen=True)
class E2eTenant:
    number: int
    email: str
    home_chat: bool
    used: int  # of the trial plan's 50
    sample_data: bool
    nursery: bool = False  # the review screen's fixture quote (S09); read-only, so one tenant serves both projects
    audit: bool = False  # the 26-993 audit fixture (S16), under `audit_id`
    prices: bool = False  # the demo price list (S19), before the NURSERY fixture so its lines use the products
    off: tuple[str, ...] = ()  # flags this tenant has off; every other flag is on
    missing: bool = False  # a missing line in the NURSERY draft (S23b): the fixture has none of its own
    # S24: an established factory has answered the two questions and sent quotes; a new one (`terms=False`) has not,
    # so it lands on /welcome and its first quote shows the banner (10 §5.1–5.2).
    terms: bool = True
    queue: bool = False  # the prototype's six approval-queue candidates (devtools/fixtures/queue.py)
    earlier: bool = False  # a sent quote before NURSERY, for the chat's compare with another quote (S25b)
    # S27b: `catalog_lines` changes the lines of every quote the pipeline prices, so only its own tenants have it on
    lines: bool = False

    @property
    def tenant_id(self) -> str:
        return f"tnt_01JD0E2E{self.number:018d}"

    @property
    def user_id(self) -> str:
        return f"usr_01JD0E2E{self.number:018d}"

    @property
    def audit_id(self) -> str:
        return f"aud_01JD0E2E{self.number:018d}"


TENANTS = (
    E2eTenant(1, "chat@e2e.konboro.local", home_chat=True, used=12, sample_data=True),
    E2eTenant(2, "classic@e2e.konboro.local", home_chat=False, used=12, sample_data=True),
    E2eTenant(3, "near@e2e.konboro.local", home_chat=False, used=43, sample_data=False),  # 86%: quota_near
    E2eTenant(4, "full@e2e.konboro.local", home_chat=False, used=50, sample_data=False),  # quota_reached
    # Uploads change the quota, and the desktop and mobile projects run at the same time: one tenant each.
    E2eTenant(5, "upload-desktop@e2e.konboro.local", home_chat=False, used=12, sample_data=False),
    E2eTenant(6, "upload-mobile@e2e.konboro.local", home_chat=False, used=12, sample_data=False),
    # The done-step screenshots: one tenant per scheme and project, so each shot is the tenant's only upload, a fresh
    # decode with a fixed count. In a shared tenant it was a reuse or not by test order (BUG-016).
    E2eTenant(7, "done-light-desktop@e2e.konboro.local", home_chat=False, used=12, sample_data=False),
    E2eTenant(8, "done-dark-desktop@e2e.konboro.local", home_chat=False, used=12, sample_data=False),
    E2eTenant(9, "done-light-mobile@e2e.konboro.local", home_chat=False, used=12, sample_data=False),
    E2eTenant(10, "done-dark-mobile@e2e.konboro.local", home_chat=False, used=12, sample_data=False),
    # with the demo price list since S23, as the prototype has one: the detail's prices, costs and suppliers
    E2eTenant(11, "review@e2e.konboro.local", home_chat=False, used=12, sample_data=False, nursery=True, prices=True),
    # BOM uploads (S14), apart from the drawing uploads so neither changes the other's quota counts.
    E2eTenant(12, "bom-desktop@e2e.konboro.local", home_chat=False, used=12, sample_data=False),
    E2eTenant(13, "bom-mobile@e2e.konboro.local", home_chat=False, used=12, sample_data=False),
    # The audit (S16): decisions change the fixture audit and uploads the quota, so one tenant per project; the
    # screenshots read a third that nothing changes.
    E2eTenant(14, "audit-desktop@e2e.konboro.local", home_chat=False, used=12, sample_data=False, audit=True),
    E2eTenant(15, "audit-mobile@e2e.konboro.local", home_chat=False, used=12, sample_data=False, audit=True),
    E2eTenant(16, "audit-shots@e2e.konboro.local", home_chat=False, used=12, sample_data=False, audit=True),
    # The price list (S19): saves change it, so one tenant per project; the screenshots read a third. Each has the
    # NURSERY draft, for the editor's "בשימוש בטיוטה הפתוחה".
    E2eTenant(17, "prices-desktop@e2e.konboro.local", False, 12, False, nursery=True, prices=True),
    E2eTenant(18, "prices-mobile@e2e.konboro.local", False, 12, False, nursery=True, prices=True),
    E2eTenant(19, "prices-shots@e2e.konboro.local", False, 12, False, nursery=True, prices=True),
    # S28. A new factory's first day (10 §2): no terms, no price list, nothing sent; its first quote is sent, so one
    # tenant per project (20 was `prices-off`, gone with the `price_list` flag).
    E2eTenant(20, "day-one-desktop@e2e.konboro.local", False, 0, False, terms=False),
    # The review screen's actions (S23): they change the NURSERY draft (and sending locks it), so one tenant per
    # project, with the demo price list for its prices, costs and suppliers.
    E2eTenant(21, "review-desktop@e2e.konboro.local", False, 12, False, nursery=True, prices=True),
    E2eTenant(22, "review-mobile@e2e.konboro.local", False, 12, False, nursery=True, prices=True),
    # The product picker (S23b): an attribute, a missing line, a mark and a brand discount change the draft, so one
    # tenant per project.
    E2eTenant(23, "picker-desktop@e2e.konboro.local", False, 12, False, nursery=True, prices=True, missing=True),
    E2eTenant(24, "picker-mobile@e2e.konboro.local", False, 12, False, nursery=True, prices=True, missing=True),
    # S24. Onboarding, settings and queue actions change the tenant, so one per project; the screenshots read a third
    # that nothing changes; and one tenant has the three flags off.
    E2eTenant(25, "welcome-desktop@e2e.konboro.local", False, 0, False, terms=False),
    E2eTenant(26, "welcome-mobile@e2e.konboro.local", False, 0, False, terms=False),
    E2eTenant(27, "prefs-desktop@e2e.konboro.local", False, 12, False, prices=True),
    E2eTenant(28, "prefs-mobile@e2e.konboro.local", False, 12, False, prices=True),
    E2eTenant(29, "queue-desktop@e2e.konboro.local", False, 12, False, queue=True),
    E2eTenant(30, "queue-mobile@e2e.konboro.local", False, 12, False, queue=True),
    E2eTenant(31, "s24-shots@e2e.konboro.local", False, 12, False, prices=True, queue=True),
    E2eTenant(
        32,
        "s24-off@e2e.konboro.local",
        False,
        12,
        False,
        terms=False,
        off=("onboarding", "settings_screen", "approval_queue"),
    ),
    # S25. Applying a proposal changes the NURSERY draft, so one tenant per project; one has the chat's flag off.
    E2eTenant(33, "chat-desktop@e2e.konboro.local", False, 12, False, nursery=True, prices=True, earlier=True),
    E2eTenant(34, "chat-mobile@e2e.konboro.local", False, 12, False, nursery=True, prices=True, earlier=True),
    E2eTenant(35, "chat-off@e2e.konboro.local", False, 12, False, nursery=True, prices=True, off=("chat_layer",)),
    E2eTenant(36, "chat-shots@e2e.konboro.local", False, 12, False, nursery=True, prices=True, earlier=True),
    # S26. The export sends the NURSERY draft and opens version 2, and its settings section saves the template, so one
    # tenant per project; one has `unresolved_overlay` and `export_doc` off. The overlay reads `review@`.
    E2eTenant(37, "export-desktop@e2e.konboro.local", False, 12, False, nursery=True, prices=True),
    E2eTenant(38, "export-mobile@e2e.konboro.local", False, 12, False, nursery=True, prices=True),
    E2eTenant(
        39,
        "s26-off@e2e.konboro.local",
        False,
        12,
        False,
        nursery=True,
        prices=True,
        off=("unresolved_overlay", "export_doc"),
    ),
    # S27. A build adds a quote and counts it, so one tenant per project, with the demo price list and the chat home;
    # one has the builder (and so voice) off; one makes the fidelity shots.
    E2eTenant(40, "build-desktop@e2e.konboro.local", True, 12, False, prices=True),
    E2eTenant(41, "build-mobile@e2e.konboro.local", True, 12, False, prices=True),
    E2eTenant(
        42, "build-off@e2e.konboro.local", True, 12, False, prices=True, off=("chat_quote_builder", "voice_input")
    ),
    E2eTenant(43, "build-shots@e2e.konboro.local", True, 12, False, prices=True),
    # S27b. Deciding a waiting line changes the quote, and the upload counts in the quota, so one tenant per project;
    # a third makes the fidelity shots.
    E2eTenant(44, "lines-desktop@e2e.konboro.local", False, 12, False, prices=True, lines=True),
    E2eTenant(45, "lines-mobile@e2e.konboro.local", False, 12, False, prices=True, lines=True),
    E2eTenant(46, "lines-shots@e2e.konboro.local", False, 12, False, prices=True, lines=True),
    E2eTenant(47, "day-one-mobile@e2e.konboro.local", False, 0, False, terms=False),
)
TERMS = {"version": "2026-10", "at": "2026-10-01T09:00:00+00:00"}

# A project with this name runs slowly, so a test can cancel it mid-run; every other upload runs at full speed.
SLOW_PROJECT = "E2E איטי"
SLOW_STAGE_S = 1.5


def slowed(stages: dict[int, Stage]) -> dict[int, Stage]:
    def wrap(stage: Stage) -> Stage:
        def run(ctx: StageContext) -> BaseModel:
            project = ctx.session.get(Project, ctx.drawing.project_id) if ctx.drawing.project_id else None
            if project is not None and project.name == SLOW_PROJECT:
                time.sleep(SLOW_STAGE_S)
            return stage(ctx)

        return run

    return {n: wrap(stage) for n, stage in stages.items()}


# Stage 2 at 100 DPI: E2E checks screens, not OCR, and the screenshot check runs the worker in an emulated amd64
# container, where full-size renders made the new-quote shots wait past their 90 s (S10).
E2E_EXTRACTION = ExtractionConfig(dpi=100, low_resolution_dpi=100, min_dpi=50)


def e2e_stages(stages: dict[int, Stage]) -> dict[int, Stage]:
    def extraction(ctx: StageContext) -> BaseModel:
        return s2_extraction.run(ctx, E2E_EXTRACTION)

    return slowed({**stages, 2: extraction})


def dev_users() -> str:
    return ",".join(f"{t.email}={t.tenant_id}" for t in TENANTS)


def _sample_data(s: Session, t: E2eTenant) -> None:
    """Made-up home-screen content: two drafts (one missing prices), one sent quote, queue items, an audit."""

    def add(obj: object) -> None:
        s.add(obj)
        s.flush()

    tid = t.tenant_id
    quotes = [
        ("גן ילדים, לוח ראשי", "draft", 13, 5),
        ("מבנה תעשייה, 3 לוחות", "draft", 20, 0),
        ("לוח חשמל קומה 3", "sent", 19, 0),
    ]
    for name, status, lines, unpriced in quotes:
        add(quote := Quote(id=new_id("quo"), tenant_id=tid, name=name))
        add(version := QuoteVersion(id=new_id("qv"), tenant_id=tid, quote_id=quote.id, version=1))
        for position in range(1, lines + 1):
            price = None if position <= unpriced else Decimal("185.00")
            s.add(
                QuoteLine(
                    id=new_id("ln"),
                    tenant_id=tid,
                    quote_version_id=version.id,
                    position=position,
                    description="שורה לדוגמה",
                    qty=Decimal(1),
                    unit_price=price,
                    status="green" if price is not None else "red",
                )
            )
        s.flush()
        if status == "sent":  # lines go in first: a sent version is frozen (07 §7.7)
            version.status, version.sent_at = "sent", datetime.now(UTC)
            s.flush()
    for text_ in ("מ.פ.", 'ממ"ג', "פ.צ."):
        s.add(
            KnowledgeCandidate(
                id=new_id("kc"), tenant_id=tid, kind="abbreviation", payload={"text": text_}, dedupe_key=text_
            )
        )
    add(drawing := Drawing(id=new_id("drw"), tenant_id=tid, purpose="audit", created_by=t.user_id))
    add(
        audit := Audit(
            id=new_id("aud"), tenant_id=tid, drawing_id=drawing.id, quote_ref={"number": "10271"}, status="ready"
        )
    )
    for amount in ("700.00", "400.00", "150.00"):
        s.add(
            AuditDifference(
                id=new_id("dif"),
                tenant_id=tid,
                audit_id=audit.id,
                type="missing_in_quote",
                severity="high",
                confidence=0.9,
                message="רכיב בשרטוט בלי שורה מתאימה",
                amount=Decimal(amount),
            )
        )
    s.flush()


def seed_e2e(owner: Engine, storage: Storage | None = None) -> None:
    """Plans and flags, then each E2E tenant. A tenant that already exists is left alone, like the demo seed.
    With `storage`, the review tenant's fixture pages get their images and viewer pyramids too (S11)."""
    with Session(owner) as s, s.begin():
        seed_global(s)
    month = datetime.now(ZoneInfo("Asia/Jerusalem")).date().replace(day=1)
    for t in TENANTS:
        with Session(owner) as s, s.begin():
            s.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": t.tenant_id})
            if s.execute(select(Tenant.id).where(Tenant.id == t.tenant_id)).first():
                continue
            s.add(Tenant(id=t.tenant_id, name=f"מפעל בדיקה {t.number}", plan_id="trial"))
            s.flush()
            s.add(User(id=t.user_id, tenant_id=t.tenant_id, email=t.email, display_name="בעלים"))
            entry = (
                {"data_terms_accepted": {**TERMS, "by": t.user_id}, "onboarding": {"quotes_sent": 2}} if t.terms else {}
            )
            if t.prices:  # the prototype's settings: floor 15%, a cabinet includes everything
                everything = {k: True for k in ("busbar", "n", "pe", "panels", "doors")}
                s.add(
                    TenantSettings(
                        tenant_id=t.tenant_id,
                        min_line_margin=Decimal("0.15"),
                        enclosure_includes_default=everything,
                        **entry,
                    )
                )
            else:
                s.add(TenantSettings(tenant_id=t.tenant_id, **entry))
            s.add(QuotaUsage(tenant_id=t.tenant_id, month=month, used=t.used))
            for flag in FLAGS:
                enabled = t.home_chat if flag["key"] == "home_chat" else flag["key"] not in t.off
                if flag["key"] == CATALOG_LINES:
                    enabled = t.lines
                s.add(TenantFeatureOverride(tenant_id=t.tenant_id, flag_key=flag["key"], enabled=enabled, reason="e2e"))
            s.flush()
            if t.sample_data:
                _sample_data(s, t)
            if t.queue:
                seed_queue(s, t.tenant_id)
            if t.prices:
                s.add(MarginRule(id=new_id("mr"), tenant_id=t.tenant_id, level="default", value=Decimal("0.25")))
                seed_price_list(s, t.tenant_id)
                link_demo_catalog(s, t.tenant_id)
                s.flush()
            if t.nursery:
                seed_nursery(s, t.tenant_id)
                if t.missing:
                    seed_missing_line(s, t.tenant_id)
                if t.earlier:
                    seed_earlier_quote(s, t.tenant_id)
                if storage is not None:
                    seed_nursery_pages(s, storage, t.tenant_id)
                    seed_nursery_detections(s, storage, t.tenant_id)
            if t.audit:
                seed_audit_993(s, t.tenant_id, t.user_id, t.audit_id)
                if storage is not None:
                    seed_audit_993_pages(s, storage, t.tenant_id)


def e2e_settings(web_port: int) -> Settings:
    origins = [f"http://localhost:{web_port}", f"http://127.0.0.1:{web_port}"]
    return Settings(  # type: ignore[call-arg]
        _env_file=None,  # hermetic: a developer's .env must not change the E2E run
        env="test",
        cors_origins=origins,
        dev_password=SecretStr(PASSWORD),
        dev_users=dev_users(),
        flag_cache_seconds=0,
        s3_endpoint=os.environ.get("KONBORO_S3_ENDPOINT", "http://localhost:9000"),
        sqs_endpoint=os.environ.get("KONBORO_SQS_ENDPOINT", "http://localhost:9324"),
        sqs_queue_prefix="e2e-",  # its own queues: a running `make dev` worker never takes E2E messages
        s3_bucket="konboro-e2e",  # and its own bucket, emptied at start (Storage.reset_local_bucket)
        stage_retry_seconds=1,
    )


def prepare(storage: Storage | None = None) -> Engine:
    """A fresh, seeded konboro_e2e. Returns the app-role engine (the API never connects as the owner)."""
    owner = create_engine(fresh_database(DATABASE))
    seed_e2e(owner, storage)
    owner.dispose()
    return app_engine(database_dsn(DATABASE, role="app"))


def main() -> None:
    import uvicorn

    from konboro.api.app import create_app
    from konboro.devtools.fake_llm import fake_providers
    from konboro.pipeline.stages import STAGES
    from konboro.pipeline.worker import start_in_thread
    from konboro.services.queue import DLQ, STAGE_QUEUES, Queue

    api_port = int(os.environ.get("KONBORO_E2E_API_PORT", "8001"))
    web_port = int(os.environ.get("KONBORO_E2E_WEB_PORT", "5181"))
    settings = e2e_settings(web_port)
    storage = Storage(settings)
    storage.reset_local_bucket()  # before the seed, which puts the fixture's page images in it
    engine = prepare(storage)
    queue = Queue(settings)
    queue.ensure()
    for base in [*STAGE_QUEUES.values(), DLQ]:  # nothing left over from an earlier run
        queue.purge(base)
    # The pipeline worker, beside the API, with the stand-in model: E2E never calls a real one (CLAUDE.md, testing)
    start_in_thread(settings, engine, stages=e2e_stages(STAGES), llm_providers=fake_providers())
    app = create_app(settings, engine=engine, llm_providers=fake_providers())  # the chat's stand-in too (S25)
    uvicorn.run(app, host="127.0.0.1", port=api_port, log_level="warning")


if __name__ == "__main__":
    main()
