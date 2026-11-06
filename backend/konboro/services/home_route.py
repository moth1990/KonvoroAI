"""Where a request typed on the chat home goes (13 §4.3, S27): code first, the `home_intent` model for the rest.

- A check of an existing quote ("בדוק את הצעה 10271"): `/audit`.
- The price list ("אילו מחירים חסרים במחירון?"): `/prices`.
- A question about a quote it names (its name, project, customer or drawing number): `/review/{id}`, with the chat
  open and the question sent (08).
- A panel description, a product word and a number ("12 מא"ז 1X16"): `/build`, the text as its first message (4.2).
- A drawing or a file to quote from: `/new`.
- Anything else: the intent the `home_intent` model picks from a closed list.

The routing is a suggestion, not an action: an unclear request, a question that names several quotes or none, gets a
short question with choices, and nothing happens until the estimator picks one. The model is shown the text with
amounts stripped, never a quote's name or a customer (S25b decision 1): code matches quotes by the estimator's words.
"""

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.chat.check import strip_amounts
from konboro.db import models as m
from konboro.pipeline.bom import numbers, terms
from konboro_llm import LLMClient, LLMError
from konboro_llm.stages import home_intent

log = logging.getLogger("konboro.home")

NO_BUILDER = "כדי ליצור הצעה, צרפו שרטוט או כתב כמויות"  # S04's text, when the builder is off
WHICH_QUOTE = "על איזו הצעה?"
UNCLEAR = "לא בטוח שהבנתי. מה תרצו לעשות?"
SURE_FROM = 0.6  # the model's confidence below which its intent is a question, not a route
MAX_CHOICES = 4

# A check of a quote: a check word and a quote in one request, in either order ("תבדוק לי את ההצעה", "הצעה ישנה,
# אפשר לבדוק אם חסר בה")
CHECK = re.compile(r"(?:^|\s)(?:ו?(?:בדוק|תבדוק|לבדוק|נבדוק|בדיקת|בדיקה|תשווה|להשוות))(?=\s|$|[?.,!])")
OFFER = re.compile(r"(?:^|\s)(?:ה|את\s+ה)?הצע(?:ה|ת|תי|ות)(?=\s|$|[?.,!])")
PRICES = re.compile(r"מחירון|מחירים\s+חסרים|כמה\s+עולה|מה\s+המחיר\s+של")
DRAWING = re.compile(r"(?<!בלי )(?<!ללא )(?<!אין )(?:שרטוט|קובץ)|להעלות|העלא(?:ה|ת)|לצרף|PDF", re.I)
QUESTION = re.compile(r"\?|(?:^|\s)(?:מה|למה|כמה|איך|האם|איפה|מתי|תראה|הראה|תשנה|תחליף|תוסיף|תמחק|חסר|חסרים)(?=\s|$)")
LATEST = re.compile(r"(?:ה)?(?:אחרונה|אחרון)(?=\s|$|[?.,!])")  # "ההצעה האחרונה": the one changed last
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_PREFIX = "בהלשומ"
# Words in many quotes' names that don't name one (a file's extension, a panel's kind)
STOP = frozenset(
    {
        *("הצעה", "הצעות", "הצעת", "שרטוט", "שרטוטים", "לוח", "לוחות", "ראשי", "משנה", "גרסה"),
        *("pdf", "xlsx", "xls", "dwg", "merged", "rev", "final"),
        *("בעמ", "חשמל", "פרויקט", "מבנה", "בניין", "קומה", "חדש", "חדשה", "ישן", "של", "את", "עם", "מה", "זה"),
        *("חסר", "חסרים", "חסרה", "יש", "כמה", "למה", "איך", "האם", "תראה", "תשנה", "תחליף", "תוסיף", "תמחק"),
    }
)

Kind = Literal["go", "ask", "toast"]


@dataclass(frozen=True)
class Choice:
    label: str
    to: str
    text: str | None = None
    chat: bool = False
    note: str | None = None  # a quote's last change, so two quotes of one name can be told apart


@dataclass
class Route:
    kind: Kind
    to: str | None = None
    text: str | None = None  # sent on arrival: the build's first message, or the question to the review's chat
    chat: bool = False  # the review opens with its chat
    message: str | None = None  # the question, or the toast
    choices: list[Choice] = field(default_factory=list)
    by: Literal["code", "model"] = "code"


def _words(text: str) -> set[str]:
    """A text's words, each also without a one-letter prefix ("בהצעה" → "הצעה", "לנורסרי" → "נורסרי"); a word whose
    bare form is a stop word is dropped with it."""
    out: set[str] = set()
    for w in _WORD.findall(text.casefold()):
        forms = {w, w[1:]} if len(w) > 3 and w[0] in _PREFIX else {w}
        if forms & STOP:
            continue
        out |= forms
    return out


def _distinct(words: set[str]) -> set[str]:
    return {w for w in words if w not in STOP and len(w) >= 3}


_FILE = re.compile(r"(?:[_-]merged)?\.(?:pdf|xlsx?|csv|dwg|png|jpe?g)$", re.I)


def _spoken(name: str) -> str:
    """A quote's name as said: without its file's extension ("NURSERY-1_merged.pdf" → "NURSERY-1")."""
    return _FILE.sub("", name).strip()


def _phrase(text: str) -> str:
    return " ".join(_WORD.findall(text.casefold()))


@dataclass(frozen=True)
class Named:
    quote_id: str
    name: str
    words: frozenset[str]
    phrases: tuple[str, ...] = ()  # its names whole, for a name of common words ("לוח חשמל קומה 3")
    when: str | None = None  # its last change, "05.11 21:40" in the factory's time zone


def _quotes(session: Session, tenant_id: str) -> list[Named]:
    """The factory's quotes with the words that name them: the quote's, its project's and customer's names, and the
    drawing number, most recently changed first."""
    rows = session.execute(
        select(m.Quote, m.Project.name, m.Customer.name, m.Drawing.title_block)
        .outerjoin(m.Project, (m.Project.tenant_id == m.Quote.tenant_id) & (m.Project.id == m.Quote.project_id))
        .outerjoin(m.Customer, (m.Customer.tenant_id == m.Quote.tenant_id) & (m.Customer.id == m.Quote.customer_id))
        .outerjoin(m.Drawing, (m.Drawing.tenant_id == m.Quote.tenant_id) & (m.Drawing.id == m.Quote.drawing_id))
        .where(m.Quote.tenant_id == tenant_id)
        .order_by(m.Quote.updated_at.desc(), m.Quote.id.desc())
    ).all()
    zone = ZoneInfo(session.scalar(select(m.Tenant.timezone).where(m.Tenant.id == tenant_id)) or "Asia/Jerusalem")
    out = []
    for q, project, customer, title in rows:
        number = (title or {}).get("drawing_number") if isinstance(title, Mapping) else None
        text = " ".join(x for x in (q.name, project, customer, number) if x)
        names = tuple(p for x in (_spoken(q.name), project, customer, number) if x and len(p := _phrase(x)) >= 5)
        when = f"{q.updated_at.astimezone(zone):%d.%m %H:%M}" if q.updated_at else None
        out.append(Named(q.id, q.name, frozenset(_distinct(_words(text))), names, when))
    return out


def named_quotes(session: Session, tenant_id: str, text: str) -> list[Named]:
    """The quotes the text names: one whose name is written whole in it (its first word may take a prefix: "מה חסר
    בהצעה בצ'אט 06.11 09:37?"), else those sharing the most of its distinctive words with their names."""
    quotes = _quotes(session, tenant_id)
    whole = f" {_phrase(text)} "
    exact = [q for q in quotes if any(f" {x}{p} " in whole for p in q.phrases for x in ("", *_PREFIX))]
    if exact:
        return exact
    said = _distinct(_words(text))
    if not said:
        return []
    scored = [(len(said & q.words), q) for q in quotes]
    best = max((s for s, _ in scored), default=0)
    return [q for s, q in scored if s and s == best]


def _describes_a_panel(text: str) -> bool:
    return bool(terms.families_in(terms.norm(text))) and bool(numbers.numbers(text))


def _review(q: Named, question: str, chat_on: bool) -> Route:
    return Route("go", f"/review/{q.quote_id}", text=question if chat_on else None, chat=chat_on)


def _which(qs: list[Named], question: str, chat_on: bool) -> Route:
    return Route(
        "ask",
        message=WHICH_QUOTE,
        choices=[
            Choice(q.name, f"/review/{q.quote_id}", question if chat_on else None, chat_on, q.when)
            for q in qs[:MAX_CHOICES]
        ],
    )


def _build(text: str, flags: Mapping[str, bool], by: Literal["code", "model"] = "code") -> Route:
    if not flags.get("chat_quote_builder"):
        return Route("toast", message=NO_BUILDER, by=by)
    return Route("go", "/build", text=text, by=by)


def _about_a_quote(session: Session, tenant_id: str, text: str, chat_on: bool, named: list[Named]) -> Route:
    if len(named) == 1:
        return _review(named[0], text, chat_on)
    if named:
        return _which(named, text, chat_on)
    recent = _quotes(session, tenant_id)
    if recent and LATEST.search(text):
        return _review(recent[0], text, chat_on)
    return _which(recent, text, chat_on)


def _unclear(session: Session, tenant_id: str, text: str, flags: Mapping[str, bool]) -> Route:
    choices = []
    if flags.get("chat_quote_builder"):
        choices.append(Choice("לבנות הצעה מהתיאור", "/build", text))
    choices.append(Choice("הצעה משרטוט", "/new"))
    if flags.get("quote_audit"):
        choices.append(Choice("בדיקת הצעה קיימת", "/audit"))
    recent = _quotes(session, tenant_id)[:1]
    chat_on = bool(flags.get("chat_layer"))
    for q in recent:
        choices.append(Choice(f"שאלה על {q.name}", f"/review/{q.quote_id}", text if chat_on else None, chat_on, q.when))
    return Route("ask", message=UNCLEAR, choices=choices[:MAX_CHOICES], by="model")


def route(session: Session, llm: LLMClient, tenant_id: str, text: str, flags: Mapping[str, bool]) -> Route:
    t = " ".join(text.split())
    said = strip_amounts(t)  # for the model only: code reads the text as typed ("הצעה בצ'אט 06.11" is no price)
    chat_on = bool(flags.get("chat_layer"))
    if CHECK.search(t) and OFFER.search(t):
        return Route("go", "/audit")
    if PRICES.search(t):
        return Route("go", "/prices")
    question = bool(QUESTION.search(t))
    named = named_quotes(session, tenant_id, t)
    if question and named:
        return _about_a_quote(session, tenant_id, t, chat_on, named)
    if _describes_a_panel(t):
        return _build(t, flags)
    if DRAWING.search(t):
        return Route("go", "/new")
    try:
        answer = home_intent.route(llm, said, tenant_id).data
    except LLMError:
        log.warning("home_intent failed; asking instead", extra={"tenant_id": tenant_id})
        return _unclear(session, tenant_id, t, flags)
    log.info("home route by the model", extra={"tenant_id": tenant_id, "intent": answer.intent})
    if answer.confidence < SURE_FROM or answer.intent == "unclear":
        return _unclear(session, tenant_id, t, flags)
    if answer.intent == "build":
        return _build(t, flags, "model")
    if answer.intent == "new_drawing":
        return Route("go", "/new", by="model")
    if answer.intent == "audit":
        return Route("go", "/audit", by="model")
    if answer.intent == "price_list":
        return Route("go", "/prices", by="model")
    out = _about_a_quote(session, tenant_id, t, chat_on, named)
    out.by = "model"
    return out
