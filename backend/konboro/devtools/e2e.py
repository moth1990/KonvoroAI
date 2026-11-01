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
from konboro.db.seed import FLAGS, seed_global
from konboro.db.session import app_engine
from konboro.devtools.fixtures.nursery import seed_nursery
from konboro.pipeline.context import StageContext
from konboro.pipeline.extraction.config import ExtractionConfig
from konboro.pipeline.stages import Stage, s2_extraction
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

    @property
    def tenant_id(self) -> str:
        return f"tnt_01JD0E2E{self.number:018d}"

    @property
    def user_id(self) -> str:
        return f"usr_01JD0E2E{self.number:018d}"


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
    E2eTenant(11, "review@e2e.konboro.local", home_chat=False, used=12, sample_data=False, nursery=True),
)

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
        s.add(KnowledgeCandidate(id=new_id("kc"), tenant_id=tid, kind="abbreviation", payload={"text": text_}))
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


def seed_e2e(owner: Engine) -> None:
    """Plans and flags, then each E2E tenant. A tenant that already exists is left alone, like the demo seed."""
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
            s.add(TenantSettings(tenant_id=t.tenant_id))
            s.add(QuotaUsage(tenant_id=t.tenant_id, month=month, used=t.used))
            for flag in FLAGS:
                enabled = t.home_chat if flag["key"] == "home_chat" else True
                s.add(TenantFeatureOverride(tenant_id=t.tenant_id, flag_key=flag["key"], enabled=enabled, reason="e2e"))
            s.flush()
            if t.sample_data:
                _sample_data(s, t)
            if t.nursery:
                seed_nursery(s, t.tenant_id)


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


def prepare() -> Engine:
    """A fresh, seeded konboro_e2e. Returns the app-role engine (the API never connects as the owner)."""
    owner = create_engine(fresh_database(DATABASE))
    seed_e2e(owner)
    owner.dispose()
    return app_engine(database_dsn(DATABASE, role="app"))


def main() -> None:
    import uvicorn

    from konboro.api.app import create_app
    from konboro.devtools.fake_llm import fake_providers
    from konboro.pipeline.stages import STAGES
    from konboro.pipeline.worker import start_in_thread
    from konboro.services.queue import DLQ, STAGE_QUEUES, Queue
    from konboro.services.storage import Storage

    api_port = int(os.environ.get("KONBORO_E2E_API_PORT", "8001"))
    web_port = int(os.environ.get("KONBORO_E2E_WEB_PORT", "5181"))
    settings = e2e_settings(web_port)
    engine = prepare()
    Storage(settings).reset_local_bucket()
    queue = Queue(settings)
    queue.ensure()
    for base in [*STAGE_QUEUES.values(), DLQ]:  # nothing left over from an earlier run
        queue.purge(base)
    # The pipeline worker, beside the API, with the stand-in model: E2E never calls a real one (CLAUDE.md, testing)
    start_in_thread(settings, engine, stages=e2e_stages(STAGES), llm_providers=fake_providers())
    uvicorn.run(create_app(settings, engine=engine), host="127.0.0.1", port=api_port, log_level="warning")


if __name__ == "__main__":
    main()
