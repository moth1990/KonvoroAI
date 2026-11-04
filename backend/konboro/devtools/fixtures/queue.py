"""The prototype's approval queue (`QUEUE`, prototype lines 512–519) as candidates, for the demo and E2E tenants.

The evidence is the prototype's, which is made up. A rerun adds nothing: each candidate's `dedupe_key` is unique per
tenant. The two catalog items' SKUs are made up as well.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.services.knowledge import clean_payload, dedupe_key

# (kind, payload, evidence, date "dd.mm" of 2026)
QUEUE: list[tuple[str, dict[str, Any], dict[str, Any], str]] = [
    (
        "abbreviation",
        {"text": "מ.פ.", "family": "rcd", "symbol_class": "rcd", "display_he": "מפסק פחת"},
        {"text": '6199-2-50 · 7 מופעים, כולם במלבן ליד "4x63A/0,03A"', "origin": "תיקון בהצעה"},
        "28.10",
    ),
    (
        "spelling",
        {"pattern": "SAVE", "meaning_he": "שמור (מעגל רזרבי)"},
        {"text": "NURSERY · F30, F31", "origin": "אישור שורה"},
        "03.11",
    ),
    (
        "catalog_item",
        {"sku": "XT1C160-4P-RCD", "brand": "ABB", "family": "circuit_breaker"},
        {"what": "ABB XT1C 4P ‏160A + מודול פחת (ערכה)", "text": 'NURSERY · Q0 "משולב פחת"', "origin": "הזנה ידנית"},
        "03.11",
    ),
    (
        "symbol",
        {"id": "step_relay", "family": "relay", "display_name_he": "ממסר צעד (טלרופטור)", "billable": True},
        {"text": '6199-2-50 · 6 מופעים עם "לחצן בלוח"', "origin": "סיווג ידני"},
        "28.10",
    ),
    (
        "spelling",
        {"pattern": "INC=", "meaning_he": 'זרם העומס של המעגל, לא זרם המא"ז', "attribute": "load_current_a"},
        {"text": "3 שרטוטים · INC בערך 0.8 מהזרם הנקוב", "origin": "אישור מהנדס"},
        "26.10",
    ),
    (
        "catalog_item",
        {"sku": "SIRCO-4P-125", "brand": "SOCOMEC", "family": "switch_disconnector"},
        {"what": "מנתק SOCOMEC 4P ‏125A", "text": "26/993 · SG", "origin": "ייבוא מהצעה 10271"},
        "03.11",
    ),
]


def seed_queue(session: Session, tenant_id: str) -> None:
    for kind, raw, evidence, day in QUEUE:
        payload = clean_payload(kind, raw)
        d, mo = (int(x) for x in day.split("."))
        session.execute(
            insert(m.KnowledgeCandidate)
            .values(
                id=new_id("kc"),
                tenant_id=tenant_id,
                kind=kind,
                payload=payload,
                evidence=evidence,
                dedupe_key=dedupe_key(kind, payload),
                created_at=datetime(2026, mo, d, 9, 0, tzinfo=UTC),
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "kind", "dedupe_key"])
        )
    session.flush()
