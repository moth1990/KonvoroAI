"""The API that Playwright runs against: `python -m konboro.devtools.e2e` (started by playwright.config.ts).

It recreates the `konboro_e2e` database, migrates it, loads plans, flags and fixed E2E tenants, and serves
the API on port 8001 (KONBORO_E2E_API_PORT) for the web app on port 5181 (KONBORO_E2E_WEB_PORT).

Flags are read-only through the API (S03 decision), so each state a test needs is its own tenant with its own
dev login. frontend/e2e/fixtures.ts lists the same emails.
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.orm import Session

from konboro.db.admin import database_dsn, fresh_database
from konboro.db.ids import new_id
from konboro.db.models import (
    Audit,
    AuditDifference,
    Drawing,
    KnowledgeCandidate,
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
)


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


def e2e_settings(web_port: int) -> Settings:
    origins = [f"http://localhost:{web_port}", f"http://127.0.0.1:{web_port}"]
    return Settings(  # type: ignore[call-arg]
        _env_file=None,  # hermetic: a developer's .env must not change the E2E run
        env="test",
        cors_origins=origins,
        dev_password=SecretStr(PASSWORD),
        dev_users=dev_users(),
        flag_cache_seconds=0,
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

    api_port = int(os.environ.get("KONBORO_E2E_API_PORT", "8001"))
    web_port = int(os.environ.get("KONBORO_E2E_WEB_PORT", "5181"))
    app = create_app(e2e_settings(web_port), engine=prepare())
    uvicorn.run(app, host="127.0.0.1", port=api_port, log_level="warning")


if __name__ == "__main__":
    main()
