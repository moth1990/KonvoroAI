"""`propose_change` and what happens to a proposal (08 §6.7, §7).

**Resolve.** The model's target is a filter (or line names); code turns it into lines once, and the proposal keeps
those lines, so what the estimator approves is what they saw.

**What if** (08 §7.2). Inside a SAVEPOINT, on in-memory storage: the same review actions the screen uses run on the
quote (`chat.actions`, `services.review`), stages 5–7 once at the end, the quote is read again, and everything is
rolled back. The diff is the quote before against the quote after: every effect, asked for or not (a bigger
enclosure, a new finding, a line that could not change). A sent version is copied to version N+1 first, as approving
would (07 §7.7).

**Apply** (08 §7.5) is the estimator's click, never a tool: the same actions for real, with `source` = `chat` and the
proposal's id on every event, so the review screen's undo takes the whole proposal back. A proposal made on a revision
the quote has since moved past is expired (`proposal_expired`).

**Remember** (08 §7.4, S25b). A proposal that swaps a brand or a SKU offers "לזכור ללקוח הזה" (when the quote has a
customer) and "לזכור למפעל" beside `quote_only`, the default, which the model cannot change (S25b decision 3).
Approved with one of them, each line that changed SKU and has a signature writes the match memory under its signature
and the brand context it was matched in (S25b decisions 5–6), and the proposal's undo takes it back. Prices, margins
and the discount are always `quote_only`.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.domain.permissions import Permission, allowed
from konboro.pipeline.pricing.edits import Replaced
from konboro.services import quote_versions, review
from konboro.services import review_picker as picker
from konboro.services.review import Ctx, Deferred, Done, ReviewError
from konboro.services.storage import Storage
from konboro_llm.stages.chat_command import ProposeChange

from . import actions
from .lines import ChatLine, QuoteLines, load, select_lines
from .overlay import OverlayStorage
from .state import ChatState

MEMORY_TYPES = ("replace_brand", "replace_sku")  # 08 §7.4: what a match memory can hold, a SKU for a signature
SCOPES = ("quote_only", "customer", "tenant")
MANY_LINES = 30  # 08 §9: a prominent warning with the count
MANY_DELETES = 5  # 08 §9: the button says "מחק X שורות"
LINE_FIELDS = ("sku", "manufacturer", "description", "qty", "status", "unit_price", "line_total")
REASON_HE = {
    "not_found": "השורה כבר לא בהצעה",
    "fixed_quantity": "הכמות של השורה הזו נקבעת לפי רכיב אחר",
    "not_editable": "אי אפשר לשנות את הערך הזה בשורה הזו",
    "no_component": "לשורה אין רכיב מהשרטוט",
    "invalid": "הערך לא תקין",
    "no_cost": "אין עלות לשורה, ולכן אין ממה לחשב רווח",
    "missing_line": "קודם צריך לבחור מוצר לשורה החסרה",
    "invalid_amount": "המחיר לא תקין",
    "unknown_product": 'המק"ט לא נמצא בקטלוג',
}


class ProposalError(Exception):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


@dataclass
class Outcome:
    notes: dict[str, str] = field(default_factory=dict)  # line id -> why it did not change as asked
    warnings: list[str] = field(default_factory=list)
    deleted: int = 0

    def warn(self, code: str) -> None:
        if code not in self.warnings:
            self.warnings.append(code)


# --- resolve --------------------------------------------------------------------------------------------------------


def _decimal(text: str | None, loc: str) -> Decimal:
    try:
        value = Decimal(str(text).replace(",", "").replace("%", "").replace("₪", "").strip())
    except (InvalidOperation, ValueError) as e:
        raise ProposalError(422, f"invalid_{loc}") from e
    if not value.is_finite():
        raise ProposalError(422, f"invalid_{loc}")
    return value


def resolve(
    session: Session, tenant_id: str, ql: QuoteLines, state: ChatState, args: ProposeChange
) -> list[dict[str, Any]]:
    """Each change with the lines it applies to, as ids, and its parameters checked."""
    out: list[dict[str, Any]] = []
    for ch in args.changes:
        params: dict[str, Any] = {}
        lines: list[ChatLine] = []
        if ch.type != "add_line" and ch.type != "set_customer_discount":
            lines = select_lines(ql, ch.target, state, include_removed=ch.type == "restore_derived")
            if ch.type == "restore_derived":
                lines = [ln for ln in lines if ln.removed]
        if ch.type == "replace_brand":
            if not ch.manufacturer:
                raise ProposalError(422, "missing_manufacturer")
            params["brand"] = ch.manufacturer.strip()
        elif ch.type in ("replace_sku", "add_line"):
            if not ch.sku:
                raise ProposalError(422, "missing_sku")
            choice = _sku_choice(session, tenant_id, ch.sku)
            if choice is None:
                raise ProposalError(422, "no_catalog_match")
            params["ref"] = choice.ref
            if ch.type == "add_line":
                params["qty"] = ch.qty or 1
                panel = state.real(ch.panel, "panel") if ch.panel else None
                params["panel_id"] = panel or (ql.panels()[0][0] if ql.panels() else None)
        elif ch.type == "set_attribute":
            if ch.attribute not in picker.EDITABLE or ch.value is None:
                raise ProposalError(422, "attribute_not_editable")
            params["attribute"] = ch.attribute
            params["value"] = str(_decimal(ch.value, "value"))
        elif ch.type == "set_quantity":
            if ch.qty is None:
                raise ProposalError(422, "missing_qty")
            params["qty"] = ch.qty
        elif ch.type == "set_line_price":
            params["unit_price"] = str(_decimal(ch.unit_price, "unit_price"))
        elif ch.type == "set_line_margin":
            params["pct"] = str(_decimal(ch.pct, "pct"))
            params["kind"] = ch.margin_kind or "markup"
        elif ch.type == "set_customer_discount":
            params["pct"] = str(_decimal(ch.pct, "pct"))
        if ch.type not in ("add_line", "set_customer_discount") and not lines:
            raise ProposalError(422, "no_lines")
        out.append(
            {
                "type": ch.type,
                "line_ids": [ln.line_id for ln in lines],
                "keys": [ln.key for ln in lines],
                "params": params,
            }
        )
    return out


def _sku_choice(session: Session, tenant_id: str, sku: str) -> picker.Choice | None:
    want = sku.strip().casefold()
    found = [c for c in picker.search(session, tenant_id, sku) if (c.sku or "").casefold() == want]
    return found[0] if found else None


# --- run the changes -------------------------------------------------------------------------------------------------


def _rows(ctx: Ctx, ch: dict[str, Any], removed: bool = False) -> list[m.QuoteLine]:
    """The change's lines in the version being changed: by id, else by key (version N+1 copies lines under new ids)."""
    rows = {r.id: r for r in ctx.lines(live=False)}
    by_key = {(r.line_key or f"pos:{r.position}"): r for r in rows.values()}
    out = []
    for line_id, key in zip(ch["line_ids"], ch.get("keys") or ch["line_ids"], strict=False):
        row = rows.get(line_id) or by_key.get(key)
        if row is not None and (row.deleted_at is not None) == removed:
            out.append(row)
    return out


def _each(ctx: Ctx, rows: list[m.QuoteLine], outcome: Outcome, act: Callable[[m.QuoteLine], Done]) -> None:
    for row in rows:
        try:
            with ctx.session.begin_nested():
                act(row)
        except ReviewError as e:
            kind = str(e.details[0]["type"]) if e.details else e.code
            outcome.notes[row.id] = REASON_HE.get(kind) or REASON_HE.get(e.code) or "השורה לא השתנתה"
            outcome.warn("not_applied")


def _attrs_differ(ctx: Ctx, row: m.QuoteLine, item_id: str | None) -> bool:
    if not item_id:
        return False
    item = ctx.session.get(m.CatalogItem, item_id)
    component = picker.component_of(ctx, row)
    if item is None or component is None:
        return False
    for name in ("current_a", "poles"):
        have = component.attributes.get(name)
        want = (item.attributes or {}).get(name)
        if have is not None and have.value is not None and want is not None and str(have.value) != str(want):
            return True
    return False


def run_change(ctx: Ctx, ch: dict[str, Any], outcome: Outcome) -> None:
    t, p = ch["type"], ch["params"]
    if t == "restore_derived":
        rows = _rows(ctx, ch, removed=True)
        if rows:
            review.restore_lines(ctx, [r.id for r in rows])
        return
    rows = _rows(ctx, ch)
    missing = set(ch["line_ids"]) - {r.id for r in rows}
    if t != "add_line" and t != "set_customer_discount" and len(rows) < len(ch["line_ids"]) and missing:
        outcome.warn("not_applied")
    if t == "replace_brand":
        brand = actions.catalog_brand(ctx, p["brand"]) or p["brand"]
        pairs: list[tuple[m.QuoteLine, Replaced]] = []
        for row in rows:
            if row.line_type not in ("component", "manual") or row.parent_line_id:
                outcome.notes[row.id] = "השורה לא מוצר שאפשר להחליף"
                continue
            if (row.manufacturer or "").casefold() == brand.casefold():
                continue  # already the brand
            try:
                rem = picker.rematch(ctx, row, dict((row.edits or {}).get("attrs") or {}), brand=brand)
            except ReviewError:
                outcome.notes[row.id] = 'לשורה אין רכיב מהשרטוט, אז אי אפשר להתאים מחדש. אפשר להחליף מק"ט'
                outcome.warn("partial_brand_coverage")
                continue
            if rem.sku and (rem.manufacturer or "").casefold() == brand.casefold():
                pairs.append((row, Replaced(rem.sku, rem.manufacturer, rem.description, rem.catalog_item_id)))
            else:
                outcome.notes[row.id] = f'אין בקטלוג מוצר מתאים של {brand}. המק"ט הקודם נשאר'
                outcome.warn("partial_brand_coverage")
        actions.replace_products(ctx, pairs, "replace_brand")
    elif t == "replace_sku":
        choice = picker.choice(ctx.session, ctx.tid, p["ref"])
        rep = choice.replaced()
        for row in rows:
            if _attrs_differ(ctx, row, choice.catalog_item_id):
                outcome.notes[row.id] = 'התכונות של המק"ט החדש שונות מאלה שבשרטוט'
                outcome.warn("sku_attribute_mismatch")
        actions.replace_products(ctx, [(r, rep) for r in rows if r.sku != rep.sku], "replace_sku")
    elif t == "set_attribute":
        value = Decimal(p["value"])
        _each(ctx, rows, outcome, lambda r: picker.set_attribute(ctx, r.id, p["attribute"], value))
    elif t == "set_quantity":
        _each(ctx, rows, outcome, lambda r: review.set_quantity(ctx, r.id, Decimal(p["qty"])))
    elif t == "delete_lines":
        gone: set[str] = set()

        def delete(r: m.QuoteLine) -> Done:
            if r.parent_line_id in gone:
                return Done("")
            gone.add(r.id)
            return review.delete(ctx, r.id)

        _each(ctx, rows, outcome, delete)
        outcome.deleted += len(gone)
    elif t == "add_line":
        actions.add_line(ctx, picker.choice(ctx.session, ctx.tid, p["ref"]), int(p["qty"]), p["panel_id"])
    elif t == "set_line_price":
        price = Decimal(p["unit_price"])
        _each(ctx, rows, outcome, lambda r: review.change_price(ctx, r.id, price, "quote"))
    elif t == "set_line_margin":
        pct = Decimal(p["pct"])
        _each(ctx, rows, outcome, lambda r: actions.set_line_margin(ctx, r.id, pct, p["kind"]))
    elif t == "set_customer_discount":
        actions.set_discount(ctx, Decimal(p["pct"]))


def run_all(ctx: Ctx, changes: list[dict[str, Any]]) -> Outcome:
    outcome = Outcome()
    ctx.deferred = Deferred()
    for ch in changes:
        run_change(ctx, ch, outcome)
    review.run_deferred(ctx)
    return outcome


def _draft(session: Session, storage: Any, actor: review.Actor, quote_id: str) -> tuple[Ctx, bool]:
    """A draft to change: the current one, or version N+1 of a sent one (07 §7.7)."""
    _, version = quote_versions.current(session, actor.tenant_id, quote_id)
    opened = False
    if version.status == "sent":
        quote_versions.open_next(session, quote_versions.Actor(actor.tenant_id, actor.user_id), quote_id)
        opened = True
    return review.open_draft(session, storage, actor, quote_id), opened


# --- the diff --------------------------------------------------------------------------------------------------------


def _side(ln: ChatLine, state: ChatState) -> dict[str, Any]:
    return {
        "sku": ln.sku,
        "manufacturer": ln.manufacturer,
        "description": ln.description,
        "qty": str(ln.qty.normalize()),
        "status": ln.status,
        "unit_price": state.ref(ln.unit_price),
        "line_total": state.ref(ln.line_total),
    }


def _totals(ql: QuoteLines, state: ChatState) -> dict[str, str | None]:
    t = ql.view.totals
    return {
        "net_total": state.ref(t.net_total),
        "margin_pct": state.ref(t.margin_pct, "pct"),
        "discount": state.ref(t.discount),
    }


def _issues(ql: QuoteLines) -> dict[tuple[str, frozenset[str]], str]:
    return {(f.code, frozenset(f.line_ids)): f.title or f.message for f in ql.view.findings}


def diff(before: QuoteLines, after: QuoteLines, outcome: Outcome, state: ChatState) -> dict[str, Any]:
    b = {ln.key: ln for ln in before.lines}
    a = {ln.key: ln for ln in after.lines}
    changed: list[dict[str, Any]] = []
    derived: list[dict[str, Any]] = []
    for key, old in b.items():
        new = a.get(key)
        if new is None:
            continue
        moved = any(getattr(old, f) != getattr(new, f) for f in LINE_FIELDS)
        note = outcome.notes.get(old.line_id) or outcome.notes.get(new.line_id)
        if not moved and not note:
            continue
        entry = {"line_id": old.line_id, "before": _side(old, state), "after": _side(new, state), "note": note}
        (derived if old.line_type in ("derived", "labor") else changed).append(entry)
    restored = {ln.key for ln in before.removed}
    added = [
        {"line_id": ln.line_id, "after": _side(ln, state), "restored": k in restored}
        for k, ln in a.items()
        if k not in b
    ]
    removed = [{"line_id": ln.line_id, "before": _side(ln, state)} for k, ln in b.items() if k not in a]
    ib, ia = _issues(before), _issues(after)
    return {
        "lines_changed": changed,
        "lines_added": added,
        "lines_removed": removed,
        "derived_changes": derived,
        "totals_before": _totals(before, state),
        "totals_after": _totals(after, state),
        "new_issues": [msg for k, msg in ia.items() if k not in ib],
        "resolved_issues": [msg for k, msg in ib.items() if k not in ia],
    }


def affected(d: dict[str, Any]) -> int:
    real = [x for x in d["lines_changed"] if x["before"] != x["after"]]
    return len(real) + len(d["lines_added"]) + len(d["lines_removed"])


# --- propose, apply, dismiss -----------------------------------------------------------------------------------------


@dataclass
class Proposed:
    proposal: m.ChatProposal
    outcome: Outcome


def propose(
    session: Session,
    storage: Storage,
    actor: review.Actor,
    quote_id: str,
    conversation: m.ChatConversation,
    state: ChatState,
    args: ProposeChange,
) -> Proposed:
    before = load(session, actor.tenant_id, quote_id)
    if before is None:
        raise ProposalError(404, "not_found")
    changes = resolve(session, actor.tenant_id, before, state, args)
    savepoint = session.begin_nested()
    try:
        ctx, opened = _draft(session, OverlayStorage(storage), actor, quote_id)
        outcome = run_all(ctx, changes)
        session.flush()
        after = load(session, actor.tenant_id, quote_id)
        assert after is not None  # noqa: S101
    finally:
        savepoint.rollback()
        session.expire_all()
    d = diff(before, after, outcome, state)
    if opened:
        outcome.warn("opens_new_version")
    count = affected(d)
    if count > MANY_LINES:
        outcome.warn("many_lines")
    if outcome.deleted > MANY_DELETES:
        outcome.warn("many_deletes")
    if d["new_issues"]:
        outcome.warn("new_issues")
    d["deleted_count"] = outcome.deleted
    pid = new_id("prp")
    row = m.ChatProposal(
        id=pid,
        tenant_id=actor.tenant_id,
        quote_id=quote_id,
        conversation_id=conversation.id,
        base_version=before.view.version,
        base_revision=before.view.revision,
        summary_he=args.summary_he.strip()[:200],
        changes=changes,
        diff=d,
        remember_default="quote_only",
        remember_options=remember_options(session, actor.tenant_id, quote_id, changes, d),
        warnings=outcome.warnings,
        affected_line_count=count,
        alias=state.name("proposal", pid),
    )
    session.add(row)
    session.flush()
    return Proposed(row, outcome)


def get(session: Session, tenant_id: str, proposal_id: str) -> m.ChatProposal:
    row = session.scalar(
        select(m.ChatProposal).where(m.ChatProposal.tenant_id == tenant_id, m.ChatProposal.id == proposal_id)
    )
    if row is None:
        raise ProposalError(404, "not_found")
    return row


def is_stale(session: Session, tenant_id: str, p: m.ChatProposal) -> bool:
    _, version = quote_versions.current(session, tenant_id, p.quote_id)
    return version.version != p.base_version or version.revision != p.base_revision


def expire_stale(session: Session, tenant_id: str, rows: list[m.ChatProposal]) -> None:
    """08 §7.5: a pending proposal on a revision the quote has moved past is expired."""
    for p in rows:
        if p.status == "pending" and is_stale(session, tenant_id, p):
            p.status = "expired"
            p.resolved_at = review.now()
    session.flush()


def remember_options(
    session: Session, tenant_id: str, quote_id: str, changes: list[dict[str, Any]], d: dict[str, Any]
) -> list[str]:
    """08 §7.1 `remember_options`: more than `quote_only` only for a brand or SKU swap that moves a signed line."""
    if not any(ch.get("type") in MEMORY_TYPES for ch in changes):
        return ["quote_only"]
    moved = [x["line_id"] for x in d["lines_changed"] if x["after"]["sku"] and x["before"]["sku"] != x["after"]["sku"]]
    signed = session.scalar(
        select(m.QuoteLine.id)
        .where(m.QuoteLine.tenant_id == tenant_id, m.QuoteLine.id.in_(moved), m.QuoteLine.signature.is_not(None))
        .limit(1)
    )
    if signed is None:
        return ["quote_only"]
    quote = session.scalar(select(m.Quote).where(m.Quote.tenant_id == tenant_id, m.Quote.id == quote_id))
    return ["quote_only", *(["customer"] if quote is not None and quote.customer_id else []), "tenant"]


def apply(
    session: Session,
    storage: Storage,
    actor: review.Actor,
    proposal_id: str,
    remember: str = "quote_only",
    role: str = "owner",
) -> tuple[m.ChatProposal, Done]:
    p = get(session, actor.tenant_id, proposal_id)
    if remember not in SCOPES or remember not in (p.remember_options or ["quote_only"]):
        raise ProposalError(422, "remember_not_offered")
    if remember == "tenant" and not allowed(role, Permission.SETTINGS_WRITE):
        raise ProposalError(403, "forbidden")  # 08 §7.4: "לזכור למפעל" is managing the preferences
    if p.status == "expired" or (p.status == "pending" and is_stale(session, actor.tenant_id, p)):
        p.status, p.resolved_at = "expired", review.now()
        session.flush()
        raise ProposalError(409, "proposal_expired")
    if p.status != "pending":
        raise ProposalError(409, "proposal_not_pending")
    ctx, _ = _draft(session, storage, actor, p.quote_id)
    ctx.source = "chat"
    ctx.tags = {"proposal": p.id}
    before = {r.line_key or r.id: (r.sku, r.signature, r.brand_context) for r in ctx.lines()}
    saved: Done | None = None
    run_all(ctx, list(p.changes))
    if remember != "quote_only":
        entries = []
        for r in ctx.lines():
            sku, sig, context = before.get(r.line_key or r.id, (None, None, None))
            if sig and r.sku and r.sku != sku:  # the line's signature and context before the swap (S25b decision 6)
                entries.append((sig, context, r.sku))
        saved = review.save_memory(ctx, entries, ctx.quote.customer_id if remember == "customer" else None)
    p.remembered = remember
    p.status, p.resolved_at = "applied", review.now()
    session.flush()
    event = session.scalar(
        select(m.CorrectionEvent)
        .where(
            m.CorrectionEvent.tenant_id == actor.tenant_id,
            m.CorrectionEvent.quote_id == p.quote_id,
            m.CorrectionEvent.after["proposal"].astext == p.id,
        )
        .order_by(m.CorrectionEvent.created_at.desc())
        .limit(1)
    )
    n = p.affected_line_count
    message = "השינוי הוחל" if n != 1 else "השינוי הוחל על שורה אחת"
    if n > 1:
        message = f"השינוי הוחל על {n} שורות"
    if remember != "quote_only" and saved is not None:
        message += ". נזכור את זה ללקוח הזה" if remember == "customer" else ". נזכור את זה במפעל"
    return p, Done(message, event.id if event else None, n)


def dismiss(session: Session, tenant_id: str, proposal_id: str) -> m.ChatProposal:
    p = get(session, tenant_id, proposal_id)
    if p.status != "pending":
        raise ProposalError(409, "proposal_not_pending")
    p.status, p.resolved_at = "dismissed", review.now()
    session.flush()
    return p


def for_model(p: m.ChatProposal, outcome: Outcome, state: ChatState) -> dict[str, Any]:
    """What the model is told about the proposal it made: counts, notes, warnings and references, no amounts."""
    d = p.diff
    return {
        "proposal": p.alias,
        "affected_line_count": p.affected_line_count,
        "changed": sum(1 for x in d["lines_changed"] if x["before"] != x["after"]),
        "added": len(d["lines_added"]),
        "removed": len(d["lines_removed"]),
        "not_changed": [{"line": state.name("line", lid), "note": note} for lid, note in outcome.notes.items()],
        "warnings": p.warnings,
        "new_issues": d["new_issues"],
        "resolved_issues": len(d["resolved_issues"]),
        "totals_before": d["totals_before"],
        "totals_after": d["totals_after"],
        "note": "The card is on the screen. Nothing changes until the estimator approves it.",
    }
