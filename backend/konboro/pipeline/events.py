"""What a stage reports while it runs, for the live run step (01 §4.6 "איך זה עובד טכנית", S28c).

Three kinds go to `pipeline_events`:
- `message`: a sentence for the live header and the log, built here from a template and the stage's own numbers
  ("עמוד 5: 18 מא"זים"). Never by a model, so the run step costs nothing.
- `counters`: the numbers under the page view (pages, tiles, components, products, findings).
- `boxes`: one page's detections in PDF points, origin top left (00 §6.3), drawn over the page.

At most one write a second per stage run: what comes in between waits, only the latest of each kind, and goes out
with the next write or when the stage ends (`flush`). Each write has its own transaction, like `llm_calls`, so the
events stay when the stage fails or is cancelled and its own transaction rolls back.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Engine

from konboro.db.ids import new_id
from konboro.db.models import PipelineEvent
from konboro.db.session import tenant_session

log = logging.getLogger(__name__)

KINDS = ("message", "counters", "boxes")
MIN_GAP_S = 1.0
MAX_BOXES = 400  # a page's boxes drawn at once; a denser page shows its first ones

# The live sentences, by key. Plain Hebrew (01 §4.6: no abbreviations), filled in code.
TEMPLATES: dict[str, str] = {
    "reading_file": "קורא את מבנה הקובץ",
    "page_kind": "עמוד {page}: {kind}",
    "page_template": "עמוד {page}: תבנית של המפעל, בלי מודל",
    "bom_rows": "כתב כמויות: {rows} שורות",
    "text_from_file": "עמוד {page}: הטקסט נקרא מהקובץ",
    "text_from_image": "עמוד {page}: קורא את הטקסט מהתמונה",
    "tiles": "עמוד {page}: {tiles} אריחים",
    "detecting": "עמוד {page}: מזהה רכיבים",
    "components_on_page": "עמוד {page}: {count} רכיבים",
    "model_decides": "{count} סימנים עמומים: שולח למודל",
    "joining": "מחבר תוויות לרכיבים",
    "merged": "{devices} מכשירים ← {products} מוצרים",
    "matching": "מחפש בקטלוג",
    "matched": "{matched} מתוך {products} מוצרים הותאמו",
    "checking": "בודק את הלוח",
    "findings": "{count} ממצאים",
    "pricing": "מתמחר מהמחירון שלכם",
    "priced": "{lines} שורות בהצעה",
    "reading_quote": "קורא את ההצעה",
    "comparing": "משווה את ההצעה לשרטוט",
}

# Page kinds as the live sentence says them (01 §5.2); a kind missing here is said as "עמוד".
PAGE_KINDS: dict[str, str] = {
    "single_line_diagram": "חד-קווי",
    "control_diagram": "פיקוד",
    "panel_front_view": "חזית לוח",
    "legend": "מקרא",
    "bom_table": "כתב כמויות",
    "general_notes": "הערות",
    "technical_data": "נתונים טכניים",
    "terminal_diagram": "מהדקים",
    "title_cover": "שער",
    "factory_template": "תבנית של המפעל",
    "other": "עמוד אחר",
}


def message_text(key: str, **values: Any) -> str:
    return TEMPLATES[key].format(**values)


def kind_text(kind: str | None) -> str:
    return PAGE_KINDS.get(kind or "", "עמוד")


Write = Callable[[str, dict[str, Any]], None]


class Events:
    """One stage run's reporter. `now` is injectable for the throttle's tests."""

    def __init__(self, write: Write, now: Callable[[], float] = time.monotonic, min_gap: float = MIN_GAP_S) -> None:
        self._write = write
        self._now = now
        self._min_gap = min_gap
        self._last: float | None = None
        self._pending: dict[str, dict[str, Any]] = {}

    def message(self, key: str, *, page_id: str | None = None, **values: Any) -> None:
        """`page_id`: the page the sentence is about, which the page view shows."""
        self._emit("message", {"key": key, "text": message_text(key, **values), "page_id": page_id})

    def counters(self, **values: int) -> None:
        self._emit("counters", dict(values))

    def boxes(self, page_id: str, page_no: int, size_pt: tuple[float, float], boxes: list[list[float]]) -> None:
        self._emit(
            "boxes",
            {
                "page_id": page_id,
                "page_no": page_no,
                "size": [round(size_pt[0], 1), round(size_pt[1], 1)],
                "boxes": [[round(v, 1) for v in b] for b in boxes[:MAX_BOXES]],
            },
        )

    def _emit(self, kind: str, payload: dict[str, Any]) -> None:
        self._pending[kind] = payload
        now = self._now()
        if self._last is None or now - self._last >= self._min_gap:
            self._send(now)

    def flush(self) -> None:
        """At the stage's end: what still waits goes out, whatever the time."""
        if self._pending:
            self._send(self._now())

    def _send(self, now: float) -> None:
        pending, self._pending = self._pending, {}
        self._last = now
        for kind in KINDS:
            if kind in pending:
                try:
                    self._write(kind, pending[kind])
                except Exception:  # the run step is a view: a lost event never fails a stage
                    log.exception("pipeline event %s not written", kind)


# Stages 4–8 report at their two ends, here, from their contracts; stages 1–3 report page by page inside.
STARTS = {4: "joining", 5: "matching", 6: "checking", 7: "pricing", 8: "comparing"}


def started(events: Events, stage: int) -> None:
    if stage in STARTS:
        events.message(STARTS[stage])


def finished(events: Events, stage: int, output: BaseModel) -> None:
    """The stage's last sentence and counters, from what it wrote."""
    data = output.model_dump()
    if stage == 4:
        stats = data.get("stats") or {}
        devices, products = int(stats.get("instance_count", 0)), int(stats.get("component_count", 0))
        events.message("merged", devices=devices, products=products)
        events.counters(products=products)
    elif stage == 5:
        by_status = (data.get("stats") or {}).get("by_status") or {}
        products = sum(int(n) for n in by_status.values())
        events.message("matched", matched=int(by_status.get("matched", 0)), products=products)
        events.counters(products=products)
    elif stage == 6:
        findings = len(data.get("issues") or [])
        events.message("findings", count=findings)
        events.counters(findings=findings)
    elif stage == 7:
        lines = sum(len(p.get("lines") or []) for p in data.get("panels") or [])
        events.message("priced", lines=lines)


class _Silent(Events):
    """For a stage run outside the worker (the chat builder's inline stages, unit tests): reports go nowhere."""

    def __init__(self) -> None:
        super().__init__(lambda kind, payload: None)


SILENT: Events = _Silent()


def recorder(engine: Engine, tenant_id: str, drawing_id: str, stage: int) -> Events:
    def write(kind: str, payload: dict[str, Any]) -> None:
        with tenant_session(tenant_id, engine) as s:
            s.add(
                PipelineEvent(
                    id=new_id("pev"),
                    tenant_id=tenant_id,
                    drawing_id=drawing_id,
                    stage=stage,
                    kind=kind,
                    payload=payload,
                )
            )

    return Events(write)
