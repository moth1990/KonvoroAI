"""Builds one row in every tenant table for a tenant, through the app role (so RLS WITH CHECK is exercised).

test_rls.py checks that this covers every tenant table, so a new table without a row here fails the suite.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.ids import new_id

GLOBAL_PLAN = "test_plan"
GLOBAL_FLAG = "test_flag"
GLOBAL_SYMBOL = "test_symbol"


def build_tenant_graph(s: Session, tenant_id: str) -> dict[str, str]:
    """Insert a small but complete object graph for one tenant. Returns the ids by table."""
    ids: dict[str, str] = {"tenants": tenant_id}

    def add(obj: object) -> None:
        s.add(obj)
        s.flush()

    add(m.Tenant(id=tenant_id, name=f"מפעל {tenant_id[-4:]}", plan_id=GLOBAL_PLAN))
    add(user := m.User(id=new_id("usr"), tenant_id=tenant_id, email=f"owner@{tenant_id.lower()}.test"))
    add(m.TenantSettings(tenant_id=tenant_id))
    add(m.TenantPlanOverride(tenant_id=tenant_id, monthly_quote_limit=5))
    add(m.TenantFeatureOverride(tenant_id=tenant_id, flag_key=GLOBAL_FLAG, enabled=True))
    add(m.QuotaUsage(tenant_id=tenant_id, month=date(2026, 10, 1), used=1))
    add(cus := m.Customer(id=new_id("cus"), tenant_id=tenant_id, name="לקוח"))
    add(prj := m.Project(id=new_id("prj"), tenant_id=tenant_id, customer_id=cus.id, name="פרויקט"))
    add(drw := m.Drawing(id=new_id("drw"), tenant_id=tenant_id, project_id=prj.id, created_by=user.id))
    add(res := m.QuotaEvent(id=new_id("qev"), tenant_id=tenant_id, month=date(2026, 10, 1), kind="reserve"))
    add(
        m.QuotaEvent(
            id=new_id("qev"),
            tenant_id=tenant_id,
            month=date(2026, 10, 1),
            drawing_id=drw.id,
            kind="confirm",
            reservation_id=res.id,
        )
    )
    add(
        m.LlmCall(
            id=new_id("llm"),
            tenant_id=tenant_id,
            stage="page_classification",
            provider="fake",
            model="m",
            input_tokens=10,
            output_tokens=5,
            latency_ms=3,
            attempts=1,
            drawing_id=drw.id,
        )
    )
    add(
        fil := m.DrawingFile(
            id=new_id("fil"),
            tenant_id=tenant_id,
            drawing_id=drw.id,
            original_name="a.pdf",
            detected_format="pdf",
            sha256="ab" * 32,
            size_bytes=1024,
            storage_key="k",
        )
    )
    add(pg := m.Page(id=new_id("pg"), tenant_id=tenant_id, drawing_id=drw.id, file_id=fil.id, page_no=1))
    add(pnl := m.Panel(id=new_id("pnl"), tenant_id=tenant_id, drawing_id=drw.id, name="לוח ראשי", page_ids=[pg.id]))
    add(
        m.ContextArtifact(
            id=new_id("ctx"),
            tenant_id=tenant_id,
            drawing_id=drw.id,
            page_id=pg.id,
            kind="general_notes",
            format="markdown",
            content="הערות",
        )
    )
    add(
        m.PageTemplate(
            id=new_id("tpl"),
            tenant_id=tenant_id,
            producer="ס.ס לוחות חשמל ובקרה",
            page_kind="factory_template",
            fingerprint="00" * 32,
            mask=[0.0, 0.8, 1.0, 1.0],
            source_page_id=pg.id,
        )
    )
    add(m.StageRun(tenant_id=tenant_id, drawing_id=drw.id, stage=1, status="done"))
    add(
        cmp := m.Component(
            id=new_id("cmp"),
            tenant_id=tenant_id,
            drawing_id=drw.id,
            panel_id=pnl.id,
            family="mcb",
            quantity=Decimal(4),
            designators=["F1", "F2", "F3", "F4"],
        )
    )
    add(quo := m.Quote(id=new_id("quo"), tenant_id=tenant_id, drawing_id=drw.id, customer_id=cus.id, name="הצעה"))
    add(qv := m.QuoteVersion(id=new_id("qv"), tenant_id=tenant_id, quote_id=quo.id, version=1))
    add(
        prd := m.Product(
            id=new_id("prd"),
            tenant_id=tenant_id,
            display_name='מא"ז 3P 16A',
            manufacturer_sku=f"S203M-C16-{tenant_id[-4:]}",
            family="mcb",
            sale_mode="fixed",
            fixed_price=Decimal("185.00"),
            source="manual_entry",
            entered_in_quote=quo.id,
        )
    )
    add(
        ln := m.QuoteLine(
            id=new_id("ln"),
            tenant_id=tenant_id,
            quote_version_id=qv.id,
            panel_id=pnl.id,
            position=1,
            component_id=cmp.id,
            product_id=prd.id,
            description='מא"ז 3P 16A',
            qty=Decimal(4),
            unit_price=Decimal("1250.10"),
            status="green",
        )
    )
    add(
        m.Finding(
            id=new_id("iss"),
            tenant_id=tenant_id,
            quote_version_id=qv.id,
            drawing_id=drw.id,
            source="rule",
            severity="warning",
            code="TEST",
            message="ממצא",
            line_ids=[ln.id],
        )
    )
    add(
        m.CorrectionEvent(
            id=new_id("evt"),
            tenant_id=tenant_id,
            quote_id=quo.id,
            quote_version=1,
            user_id=user.id,
            source="review_screen",
            type="row_confirmed",
            line_id=ln.id,
        )
    )
    add(sup := m.Supplier(id=new_id("sup"), tenant_id=tenant_id, name="ספק א׳"))
    add(
        m.ProductSupplier(
            id=new_id("psp"),
            tenant_id=tenant_id,
            product_id=prd.id,
            supplier_id=sup.id,
            unit_cost=Decimal("138.00"),
            price_date=date(2026, 10, 1),
            preferred=True,
        )
    )
    add(
        m.PriceHistory(
            id=new_id("prh"),
            tenant_id=tenant_id,
            product_id=prd.id,
            field="fixed_price",
            new={"value": "185.00"},
            quote_id=quo.id,
            changed_by=user.id,
        )
    )
    add(m.BrandDiscount(tenant_id=tenant_id, brand="ABB", discount_pct=Decimal("0.32")))
    add(m.MarginRule(id=new_id("mr"), tenant_id=tenant_id, level="default", kind="markup", value=Decimal("0.25")))
    add(
        m.DerivedItemRule(
            id=new_id("dr"),
            tenant_id=tenant_id,
            scope="panel",
            trigger={"always": True},
            quantity_formula="1",
            item={"family": "enclosure"},
            explanation_he="ארון",
        )
    )
    add(m.MatchMemory(id=new_id("mm"), tenant_id=tenant_id, signature="mcb|3P|16A|C", sku="S203M-C16"))
    add(m.TenantAbbreviation(id=new_id("tab"), tenant_id=tenant_id, text="מ.פ.", family="rcd"))
    add(
        m.TenantReferenceCrop(
            id=new_id("trf"),
            tenant_id=tenant_id,
            symbol_class=GLOBAL_SYMBOL,
            scope="tenant",
            image_key="crop.png",
            source="user_correction",
        )
    )
    add(m.TenantRuleOverride(tenant_id=tenant_id, rule_id="PANEL_OUTGOING_GT_MAIN", enabled=False))
    add(m.KnowledgeCandidate(id=new_id("kc"), tenant_id=tenant_id, kind="abbreviation", payload={"text": "מ.פ."}))
    add(cnv := m.ChatConversation(id=new_id("cnv"), tenant_id=tenant_id, quote_id=quo.id))
    add(
        m.ChatMessage(
            id=new_id("msg"), tenant_id=tenant_id, conversation_id=cnv.id, role="user", content={"text": "החלף לשניידר"}
        )
    )
    add(
        m.ChatProposal(
            id=new_id("prp"),
            tenant_id=tenant_id,
            quote_id=quo.id,
            conversation_id=cnv.id,
            base_version=1,
            base_revision=0,
            summary_he="החלפה",
            changes=[],
            diff={},
        )
    )
    add(aud := m.Audit(id=new_id("aud"), tenant_id=tenant_id, drawing_id=drw.id, quote_file_id=fil.id))
    add(
        m.AuditDifference(
            id=new_id("dif"),
            tenant_id=tenant_id,
            audit_id=aud.id,
            type="missing_in_quote",
            severity="high",
            confidence=0.9,
            message="חסר",
            drawing_qty=Decimal(3),
            quote_qty=Decimal(0),
        )
    )

    ids.update(users=user.id, drawings=drw.id, quotes=quo.id, quote_versions=qv.id, quote_lines=ln.id)
    return ids


def created_at_now() -> datetime:
    return datetime.now(UTC)
