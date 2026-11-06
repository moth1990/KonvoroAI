"""The chat quote builder (13 §4.2, S27): a quote with no drawing file, described in messages on `/build`.

A build is a drawing of `origin` = `chat` (S27 design 1): `bom_only`, no files, a panel, and stage outputs like any
BOM-only drawing's, so its quote opens in the review screen and every review action works on it. Its rows are a
`bom_table` artifact of source `chat` (`pipeline/bom/chat.py`), and the build's messages are `build_messages`: a
user message that changed the rows keeps them as they stood after it (`content.rows`), so the build's rows are its
last applied message's, and undo takes that message back.

One message (S27 design 2–3, decisions 1–4):
1. `chat_bom_extraction` is shown the message with amounts stripped (08 §5.4), the panels and the draft's lines by
   short name, and answers items and changes; `chat.check` keeps what the message says.
2. A typed message applies at once. A recording waits as `pending` until "הוסף" (decision 1).
3. Applying adds rows, changes a line's rows (its quantity, or removes it; decision 4), and runs stages 4, 5, 6 (data
   rules only) and 7 in the request (`pipeline/inline.py`). Every line already priced keeps its price (07 §7.2.3); a
   new line is priced from the list.
4. The first message that leaves a line makes the quote, and counts once in the month's quota (decision 2). A
   factory at its limit can't start a build.
The reply is written in code: what was added and changed, how many new lines have no price, what was left out and
why, and the model's question if it had one. The model never sees a price, a cost or a customer.
"""

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.chat.check import strip_amounts
from konboro.contracts.detection import DetectionResult
from konboro.contracts.extraction import ExtractionResult
from konboro.contracts.intake import ContextArtifact, IntakeResult, Panel
from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.pipeline import inline
from konboro.pipeline.bom import chat, terms
from konboro.pipeline.bom.table import BomRow, BomTable
from konboro.pipeline.intake.drawing import name_key
from konboro.pipeline.pricing.run import Outputs, contract, price_drawing
from konboro.services import quota
from konboro.services.storage import Storage
from konboro_llm import LLMClient, LLMError
from konboro_llm.stages import chat_bom_extraction as extraction

log = logging.getLogger("konboro.build")

DEFAULT_PANEL = "לוח 1"
NAME = "הצעה בצ'אט"
MAX_TEXT = 2000
PRODUCT_WORDS = ", ".join(dict.fromkeys(w for w, _, _ in terms.TERMS))
EXAMPLE = 'מפסק ראשי 4X63, 12 מא"ז 1X16, פחת 4X40'
NOTHING = f'לא זיהיתי רכיבים. נסו למשל: "{EXAMPLE}".'
REASONS = {
    "not_in_message": "לא מצאתי את זה בהודעה",
    "number_not_said": "יש בו ערך שלא נאמר",
    "unknown_line": "לא מצאתי את השורה בטיוטה",
    "bad_quantity": "הכמות לא ברורה",
}


class BuildError(Exception):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class Actor:
    tenant_id: str
    user_id: str


@dataclass
class Build:
    drawing: m.Drawing
    intake: IntakeResult
    quote: m.Quote | None
    version: m.QuoteVersion | None

    @property
    def tid(self) -> str:
        return self.drawing.tenant_id


def _now() -> datetime:
    return datetime.now(UTC)


def _remembered(storage: Storage) -> Storage:
    """One message's storage: what a stage writes, the next one reads from memory (`inline.Remembered`)."""
    return storage if isinstance(storage, inline.Remembered) else cast(Storage, inline.Remembered(storage))


# --- the build and its rows ---------------------------------------------------------------------------------------


def _can_start(session: Session, tenant_id: str) -> bool:
    found = next((c for c in quota.summary(session, tenant_id).counters if c.counter == "quote"), None)
    return found is None or found.usage.can_reserve()


def start(session: Session, storage: Storage, actor: Actor) -> m.Drawing:
    """A new build: its drawing, its panel and stage 1–3 outputs (no pages, one empty table). Nothing is counted."""
    if not _can_start(session, actor.tenant_id):
        raise BuildError(409, "quota_reached")
    drawing = m.Drawing(
        id=new_id("drw"),
        tenant_id=actor.tenant_id,
        purpose="quote",
        origin="chat",
        status="ready",
        input_kind="bom_only",
        current_stage=3,
        progress=1.0,
        trace_id=new_id("trc"),
        created_by=actor.user_id,
    )
    session.add(drawing)
    session.flush()
    panel = m.Panel(id=new_id("pnl"), tenant_id=actor.tenant_id, drawing_id=drawing.id, name=DEFAULT_PANEL, page_ids=[])
    session.add(panel)
    session.flush()
    intake = IntakeResult(
        drawing_id=drawing.id,
        tenant_id=actor.tenant_id,
        project_id=None,
        status="ready",
        created_at=_now(),
        input_kind="bom_only",
        title_block=None,
        source_files=[],
        pages=[],
        panels=[Panel(panel_id=panel.id, name=DEFAULT_PANEL, page_ids=[])],
        context_artifacts=[
            ContextArtifact(
                artifact_id=new_id("ctx"),
                page_id=new_id("pg"),  # the conversation stands for the page its rows are on (no `pages` row)
                kind="bom_table",
                format="json",
                content=chat.empty_table(DEFAULT_PANEL).model_dump_json(),
            )
        ],
        trace_id=str(drawing.trace_id),
    )
    inline.write_output(session, storage, drawing, 1, intake)
    inline.write_output(
        session, storage, drawing, 2, ExtractionResult(drawing_id=drawing.id, pages=[], trace_id=intake.trace_id)
    )
    inline.write_output(
        session, storage, drawing, 3, DetectionResult(drawing_id=drawing.id, pages=[], trace_id=intake.trace_id)
    )
    return drawing


def load(session: Session, storage: Storage, tenant_id: str, drawing_id: str, lock: bool = False) -> Build:
    """`lock`: a write holds the drawing's row until it commits, so two messages to one build never both read the
    same rows (one of them would be lost)."""
    q = select(m.Drawing).where(
        m.Drawing.tenant_id == tenant_id, m.Drawing.id == drawing_id, m.Drawing.origin == "chat"
    )
    drawing = session.scalar(q.with_for_update() if lock else q)
    if drawing is None:
        raise BuildError(404, "not_found")
    run = session.get_one(m.StageRun, (tenant_id, drawing.id, 1))
    intake = IntakeResult.model_validate_json(storage.get(tenant_id, str(run.output_key)))
    quote = session.scalar(select(m.Quote).where(m.Quote.tenant_id == tenant_id, m.Quote.drawing_id == drawing.id))
    version = (
        session.scalar(
            select(m.QuoteVersion).where(
                m.QuoteVersion.tenant_id == tenant_id,
                m.QuoteVersion.quote_id == quote.id,
                m.QuoteVersion.version == quote.current_version,
            )
        )
        if quote
        else None
    )
    return Build(drawing, intake, quote, version)


def messages(session: Session, b: Build) -> list[m.BuildMessage]:
    return list(
        session.scalars(
            select(m.BuildMessage)
            .where(m.BuildMessage.tenant_id == b.tid, m.BuildMessage.drawing_id == b.drawing.id)
            .order_by(m.BuildMessage.created_at, m.BuildMessage.id)
        )
    )


def rows(session: Session, b: Build) -> BomTable:
    """The build's rows: as its last applied message left them."""
    last = next(
        (
            x
            for x in reversed(messages(session, b))
            if x.role == "user" and x.status == "applied" and "rows" in x.content
        ),
        None,
    )
    table = chat.empty_table(DEFAULT_PANEL)
    if last is None:
        return table
    return table.model_copy(update={"rows": [BomRow.model_validate(r) for r in last.content["rows"]]})


def lines(session: Session, b: Build) -> list[m.QuoteLine]:
    """The draft's live lines the estimator described (a component's head line), in the table's order."""
    if b.version is None:
        return []
    return list(
        session.scalars(
            select(m.QuoteLine)
            .where(
                m.QuoteLine.tenant_id == b.tid,
                m.QuoteLine.quote_version_id == b.version.id,
                m.QuoteLine.deleted_at.is_(None),
                m.QuoteLine.component_id.is_not(None),
                m.QuoteLine.parent_line_id.is_(None),
            )
            .order_by(m.QuoteLine.position)
        )
    )


def _aliases(rows_: Sequence[m.QuoteLine]) -> dict[str, m.QuoteLine]:
    return {f"L{n}": r for n, r in enumerate(rows_, start=1)}


def _panel_names(session: Session, b: Build) -> dict[str, str]:
    return {
        p.id: p.name
        for p in session.scalars(select(m.Panel).where(m.Panel.tenant_id == b.tid, m.Panel.drawing_id == b.drawing.id))
    }


def _qty(value: Decimal) -> int:
    return int(value)


def lines_for_model(session: Session, b: Build, table: BomTable) -> tuple[str, dict[str, m.QuoteLine]]:
    """The draft's lines as the model sees them: a short name, the description, the words the estimator used for it
    ("מפסק ראשי", so "תוריד את המפסק הראשי" finds its line), the panel when there are several, and the quantity. No
    price."""
    named = _aliases(lines(session, b))
    panels = _panel_names(session, b)
    several = len({r.panel_id for r in named.values()}) > 1
    said = {r.row: r.cells[chat.SAID] or r.cells[chat.ITEM] for r in table.rows if len(r.cells) > chat.SAID}
    out = []
    for alias, r in named.items():
        rows_ = _rows_of(session, b.tid, r.component_id)
        words = said.get(rows_[0]) if rows_ else None
        panel = f" [{panels.get(r.panel_id or '', '')}]" if several else ""
        written = f' (נאמר: "{words}")' if words else ""
        out.append(f"{alias}: {r.description}{written}{panel} × {_qty(r.qty)}")
    return "\n".join(out), named


_ALIAS = re.compile(r"\bL(\d+)\b")


def _without_aliases(question: str, named: dict[str, m.QuoteLine]) -> str:
    """The model's question names lines by the short names only it saw: the estimator sees the descriptions."""
    return _ALIAS.sub(lambda x: f'"{named[x[0]].description}"' if x[0] in named else x[0], question)


# --- one message ----------------------------------------------------------------------------------------------------


def _rows_of(session: Session, tenant_id: str, component_id: str | None) -> list[int]:
    if not component_id:
        return []
    c = session.scalar(select(m.Component).where(m.Component.tenant_id == tenant_id, m.Component.id == component_id))
    return sorted({n for i in (c.instances if c else []) for n in i.get("rows", [])})


def _understood(checked: chat.Checked, named: dict[str, m.QuoteLine]) -> dict[str, Any]:
    return {
        "items": [{"text": i.text, "quantity": i.quantity, "panel": i.panel, "quote": i.quote} for i in checked.items],
        "changes": [
            {
                "line_id": named[c.line].id,
                "description": named[c.line].description,
                "action": c.action,
                "quantity": c.quantity,
                "quote": c.quote,
            }
            for c in checked.changes
        ],
        "dropped": [{"quote": d.quote, "reason": d.reason} for d in checked.dropped],
    }


def message(
    session: Session,
    storage: Storage,
    llm: LLMClient,
    actor: Actor,
    drawing_id: str | None,
    text: str,
    heard: str | None = None,
) -> Build:
    """A typed message (applied at once), or a recording's transcript (`heard`: waits for "הוסף", decision 1)."""
    text = text.strip()
    if not text or len(text) > MAX_TEXT:
        raise BuildError(422, "validation_error")
    storage = _remembered(storage)
    drawing = start(session, storage, actor) if drawing_id is None else None
    b = load(session, storage, actor.tenant_id, drawing.id if drawing else str(drawing_id), lock=True)
    if b.version is not None and b.version.status == "sent":
        raise BuildError(409, "quote_sent")
    if any(x.status == "pending" for x in messages(session, b)):
        _dismiss_pending(session, b)  # a new message replaces a recording that was never added
    said = strip_amounts(text)
    table = rows(session, b)
    shown, named = lines_for_model(session, b, table)
    panels = chat.panel_names(table, DEFAULT_PANEL)
    last = next((x for x in reversed(messages(session, b)) if x.role == "user" and x.status != "dismissed"), None)
    previous = (
        (strip_amounts(last.content["text"]), last.content["question"])
        if last is not None and last.content.get("question")
        else None
    )
    try:
        answer = extraction.extract(llm, said, shown, ", ".join(panels), PRODUCT_WORDS, actor.tenant_id, previous).data
    except LLMError as e:
        raise BuildError(502, "model_unavailable") from e
    checked = chat.check(
        said,
        [chat.Item(i.text, i.quantity, i.panel, i.quote) for i in answer.items],
        [chat.Change(c.line, c.action, c.quantity, c.quote) for c in answer.changes],
        named,
        panels,
    )
    question = _without_aliases(answer.question, named) if answer.question else None
    content: dict[str, Any] = {"text": text, **_understood(checked, named), "question": question}
    if heard is not None:
        content["heard"] = heard
    row = m.BuildMessage(
        id=new_id("bmg"),
        tenant_id=b.tid,
        drawing_id=b.drawing.id,
        role="user",
        content=content,
        status="pending" if heard is not None else "applied",
    )
    session.add(row)
    session.flush()
    log.info(
        "build message",
        extra={
            "tenant_id": b.tid,
            "user_id": actor.user_id,
            "drawing_id": b.drawing.id,
            "voice": heard is not None,
            "items": len(checked.items),
            "changes": len(checked.changes),
            "dropped": len(checked.dropped),
        },
    )
    if heard is None:
        _apply(session, storage, llm, actor, b, row)
    return load(session, storage, actor.tenant_id, b.drawing.id)


def _dismiss_pending(session: Session, b: Build) -> None:
    for x in messages(session, b):
        if x.status == "pending":
            x.status = "dismissed"
    session.flush()


def apply_pending(
    session: Session, storage: Storage, llm: LLMClient, actor: Actor, drawing_id: str, message_id: str
) -> Build:
    """ "הוסף" on a recording's card (decision 1)."""
    b = load(session, storage, actor.tenant_id, drawing_id, lock=True)
    row = _own_message(session, b, message_id)
    if row.status != "pending":
        raise BuildError(409, "not_pending")
    if b.version is not None and b.version.status == "sent":
        raise BuildError(409, "quote_sent")
    row.status = "applied"
    session.flush()
    _apply(session, storage, llm, actor, b, row)
    return load(session, storage, actor.tenant_id, drawing_id)


def dismiss_pending(session: Session, storage: Storage, actor: Actor, drawing_id: str, message_id: str) -> Build:
    """ "תקן": the recording is not added; the screen puts its text in the input."""
    b = load(session, storage, actor.tenant_id, drawing_id)
    row = _own_message(session, b, message_id)
    if row.status != "pending":
        raise BuildError(409, "not_pending")
    row.status = "dismissed"
    session.flush()
    return b


def _own_message(session: Session, b: Build, message_id: str) -> m.BuildMessage:
    row = session.scalar(
        select(m.BuildMessage).where(
            m.BuildMessage.tenant_id == b.tid,
            m.BuildMessage.drawing_id == b.drawing.id,
            m.BuildMessage.id == message_id,
        )
    )
    if row is None or row.role != "user":
        raise BuildError(404, "not_found")
    return row


def _apply(session: Session, storage: Storage, llm: LLMClient, actor: Actor, b: Build, row: m.BuildMessage) -> None:
    """The message's changes and items on the rows; then stages 4–7 when the rows changed, and the reply."""
    before = rows(session, b)
    table = before
    done: list[str] = []
    skipped: list[str] = []
    for c in row.content.get("changes", []):
        line = session.scalar(
            select(m.QuoteLine).where(
                m.QuoteLine.tenant_id == b.tid, m.QuoteLine.id == c["line_id"], m.QuoteLine.deleted_at.is_(None)
            )
        )
        found = _rows_of(session, b.tid, line.component_id if line else None)
        if not found:
            skipped.append(c["description"])
            continue
        if c["action"] == "remove":
            table = chat.remove(table, found)
            done.append(f"הסרתי: {c['description']}")
        elif c["action"] == "set_qty":
            table = chat.set_quantity(table, found, int(c["quantity"]))
            done.append(f"עדכנתי: {c['description']}, כמות {c['quantity']}")
        else:
            table = chat.add_quantity(table, found, int(c["quantity"]))
            done.append(f"הוספתי {c['quantity']} ל{c['description']}")
    items = [chat.Item(i["text"], int(i["quantity"]), i.get("panel"), i["quote"]) for i in row.content.get("items", [])]
    table = chat.add_items(table, items, DEFAULT_PANEL)
    added: list[str] = []
    if table.rows != before.rows:  # only a message that changed the rows keeps them: the one undo takes back
        row.content = {**row.content, "rows": [r.model_dump(mode="json") for r in table.rows]}
        session.flush()
        keys_before = {r.line_key for r in _all_lines(session, b)}
        rerun(session, storage, llm, actor, b, table)
        b2 = load(session, storage, b.tid, b.drawing.id)
        added = [r.line_key or "" for r in _all_lines(session, b2) if r.line_key not in keys_before]
        unpriced = sum(
            1
            for r in _all_lines(session, b2)
            if r.line_key in set(added) and r.line_type == "component" and r.unit_price is None
        )
    else:
        unpriced = 0
    reply = _reply(len(items), unpriced, done, skipped, row.content.get("dropped", []), row.content.get("question"))
    session.add(
        m.BuildMessage(
            id=new_id("bmg"), tenant_id=b.tid, drawing_id=b.drawing.id, role="assistant", content={"text": reply}
        )
    )
    session.flush()


def _all_lines(session: Session, b: Build) -> list[m.QuoteLine]:
    if b.version is None:
        return []
    return list(
        session.scalars(
            select(m.QuoteLine).where(
                m.QuoteLine.tenant_id == b.tid,
                m.QuoteLine.quote_version_id == b.version.id,
                m.QuoteLine.deleted_at.is_(None),
            )
        )
    )


def _count(n: int, one: str, many: str) -> str:
    return one if n == 1 else many.format(n=n)


def _reply(
    added: int,
    unpriced: int,
    done: Sequence[str],
    skipped: Sequence[str],
    dropped: Sequence[dict[str, Any]],
    question: str | None,
) -> str:
    """The prototype's reply (`buildSay`, line 1318), with what changed and what was left out."""
    parts: list[str] = []
    if added:
        parts.append(_count(added, "הוספתי שורה אחת.", "הוספתי {n} שורות."))
        if unpriced and added > 1:  # the prototype's words (`buildSay`, line 1318)
            parts.append(f"ל-{unpriced} מהן אין מחיר במחירון, אפשר להזין בטבלה.")
        elif unpriced:
            parts.append("אין לה מחיר במחירון, אפשר להזין בטבלה.")
        else:
            parts.append("לכולן יש מחיר מהמחירון." if added > 1 else "יש לה מחיר מהמחירון.")
    parts += [f"{x}." for x in done]
    parts += [f"לא מצאתי בטיוטה: {x}." for x in skipped]
    parts += [f'לא הוספתי "{d["quote"]}": {REASONS.get(d["reason"], "")}.' for d in dropped]
    if question:
        parts.append(strip_amounts(question.strip()))
    if not (added or done):
        if not dropped and not question and not skipped:
            return NOTHING
        return " ".join(parts)
    parts.append("מה עוד יש בלוח?")
    return " ".join(parts)


# --- stages 4–7 -----------------------------------------------------------------------------------------------------


def _panels(session: Session, b: Build, table: BomTable) -> list[Panel]:
    """The build's panels for stage 1: the first one, and every one the live rows name (made the first time)."""
    have = {
        name_key(p.name): p
        for p in session.scalars(
            select(m.Panel)
            .where(m.Panel.tenant_id == b.tid, m.Panel.drawing_id == b.drawing.id)
            .order_by(m.Panel.created_at)
        )
    }
    named = chat.panel_names(table.model_copy(update={"rows": [r for r in table.rows if not r.removed]}), DEFAULT_PANEL)
    out: list[Panel] = []
    for name in named:
        row = have.get(name_key(name))
        if row is None:
            row = m.Panel(id=new_id("pnl"), tenant_id=b.tid, drawing_id=b.drawing.id, name=name, page_ids=[])
            session.add(row)
            session.flush()
        out.append(Panel(panel_id=row.id, name=row.name, page_ids=[]))
    return out


def _count_first_line(session: Session, actor: Actor, b: Build) -> m.Quote:
    """Decision 2: the quote is made at the first line and counted then, once."""
    try:
        reservation = quota.reserve(session, b.tid, "quote", created_by=actor.user_id, drawing_id=b.drawing.id)
    except quota.QuotaReachedError as e:
        raise BuildError(409, "quota_reached") from e
    quota.confirm(
        session, b.tid, reservation, drawing_id=b.drawing.id, created_by=actor.user_id, reason="chat_first_line"
    )
    b.drawing.quota = {"counted": True, "reason": "chat_first_line", "quota_event_id": reservation}
    zone = session.scalar(select(m.Tenant.timezone).where(m.Tenant.id == b.tid)) or "Asia/Jerusalem"
    when = _now().astimezone(ZoneInfo(zone))
    q = m.Quote(id=new_id("quo"), tenant_id=b.tid, drawing_id=b.drawing.id, name=f"{NAME} {when:%d.%m %H:%M}")
    session.add(q)
    session.flush()
    return q


def rerun(session: Session, storage: Storage, llm: LLMClient, actor: Actor, b: Build, table: BomTable) -> None:
    artifact = b.intake.context_artifacts[0]
    intake = b.intake.model_copy(
        update={
            "panels": _panels(session, b, table),
            "context_artifacts": [artifact.model_copy(update={"content": table.model_dump_json()})],
        }
    )
    inline.write_output(session, storage, b.drawing, 1, intake)
    live = any(not r.removed for r in table.rows)
    if b.quote is None:
        if not live:
            return
        b.quote = _count_first_line(session, actor, b)
    out = inline.run_stages(session, storage, b.drawing, llm, (4, 5, 6))
    keep: frozenset[str] | None = frozenset() if b.version is not None and b.version.status == "draft" else None
    priced = price_drawing(
        session,
        b.tid,
        b.drawing,
        Outputs(
            intake,
            out[4],  # type: ignore[arg-type]
            out[5],  # type: ignore[arg-type]
            out[6],  # type: ignore[arg-type]
        ),
        b.quote.name,
        keep=keep,
    )
    inline.write_output(session, storage, b.drawing, 7, contract(priced, b.drawing.id, intake.trace_id))
    b.drawing.current_stage = 7


def undo(session: Session, storage: Storage, llm: LLMClient, actor: Actor, drawing_id: str) -> Build:
    """The last applied message taken back: the rows as the message before it left them, and stages 4–7 again."""
    storage = _remembered(storage)
    b = load(session, storage, actor.tenant_id, drawing_id, lock=True)
    if b.version is not None and b.version.status == "sent":
        raise BuildError(409, "quote_sent")
    last = next(
        (
            x
            for x in reversed(messages(session, b))
            if x.role == "user" and x.status == "applied" and "rows" in x.content
        ),
        None,
    )
    if last is None:
        raise BuildError(409, "nothing_to_undo")
    before = rows(session, b)
    last.status = "undone"
    session.flush()
    table = rows(session, b)
    if table.rows != before.rows:
        rerun(session, storage, llm, actor, b, table)
    return load(session, storage, actor.tenant_id, drawing_id)
