"""The answer check (08 §8.2), in code, on every answer before the screen sees it.

| Check | On failure |
| --- | --- |
| every `{{line:L3}}` is a line this conversation named and the quote still has | removed from the text, `invalid_ref` |
| every `{{$T1}}` was created in this conversation | replaced by "—", `invalid_ref` |
| every `{{quote:QT2}}` and `{{instance:I3}}` is one this conversation named (S25b) | removed, `invalid_ref` |
| no amount of money written in the text (₪, ש"ח, שקל, a decimal price) | sent back once; then the number is removed |
| a UI action points at existing lines | dropped |

Quantities, currents (16A), poles, line counts and percentages the estimator gave are not money, and neither is a
date (BUG-099): a full one ("06.11.2026"), a day and month with a time, as a chat build is named ("הצעה בצ'אט 06.11
09:37"), or the name of one of the factory's quotes that the estimator wrote (`keep`, "25.26.100.01").
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from .state import ChatState

LINE_REF = re.compile(r"\{\{\s*line:\s*([A-Za-z]+\d+)\s*\}\}")
MONEY_REF = re.compile(r"\{\{\s*(\$[A-Z]\d+)\s*\}\}")
QUOTE_REF = re.compile(r"\{\{\s*quote:\s*([A-Za-z]+\d+)\s*\}\}")
INSTANCE_REF = re.compile(r"\{\{\s*instance:\s*([A-Za-z]+\d+)\s*\}\}")
# a reference the screen sent back in the estimator's message (a clicked option): real ids, named again for the model
SCREEN_REF = re.compile(r"\{\{\s*(quote|line):\s*((?:quo|ln)_[0-9A-Z]+)\s*\}\}")
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
# An amount written as money: a currency sign or word beside a number, a number with agorot, or a thousands
# separator in a price context.
AMOUNT = re.compile(
    rf"(?:₪|NIS|ILS)\s*(?:{_NUM})"
    rf"|(?:{_NUM})\s*(?:₪|ש\"ח|ש״ח|שח\b|שקלים|שקל|ש'ח|NIS|ILS|אגורות)"
    rf"|(?:{_NUM})\s*(?:אלף|אלפים)\s*(?:שקל|ש\"ח|₪)"
    r"|\b\d{1,3}(?:,\d{3})+\.\d{2}\b"
    r"|\b\d+\.\d{2}\b(?!\s*(?:A|kA|mA|V|mm|%|מ\"מ|אמפר))",
    re.IGNORECASE,
)
WORD_AMOUNT = re.compile(r"(?:אלף|אלפיים|מאה|מאתיים|מיליון)[\w\s]{0,20}(?:שקל|ש\"ח|₪)")
# A date is no price: a price has one decimal point at most, and none is followed by a clock time (BUG-099).
_DAY_MONTH = r"(?:0?[1-9]|[12]\d|3[01])\.(?:0?[1-9]|1[0-2])"
DATE = re.compile(rf"(?<![\d.,]){_DAY_MONTH}(?:\.(?:\d{{4}}|\d{{2}})(?![\d.,])|\s+(?:[01]?\d|2[0-3]):[0-5]\d(?!\d))")
_WORD = re.compile(r"[^\W_]+")


@dataclass
class Checked:
    text: str
    line_ids: list[str] = field(default_factory=list)  # real ids, in order of first mention
    money_refs: set[str] = field(default_factory=set)
    quote_ids: list[str] = field(default_factory=list)
    instance_ids: list[str] = field(default_factory=list)
    invalid_refs: list[str] = field(default_factory=list)
    amounts: list[str] = field(default_factory=list)  # amounts written as numbers (the caller asks once again)


def _kept(text: str, keep: Sequence[str]) -> list[tuple[int, int]]:
    """The spans no amount is read in: dates, and each of `keep` written whole (its words in order, any punctuation
    between them, any case)."""
    spans = [m.span() for m in DATE.finditer(text)]
    for name in keep:
        words = _WORD.findall(name)
        if words:
            pattern = r"(?<![^\W_])" + r"[\W_]+".join(re.escape(w) for w in words) + r"(?![^\W_])"
            spans += [m.span() for m in re.finditer(pattern, text, re.IGNORECASE)]
    return spans


def _kept_out(spans: list[tuple[int, int]]) -> Callable[[re.Match[str]], bool]:
    return lambda m: any(m.start() < end and start < m.end() for start, end in spans)


def amounts_in(text: str, keep: Sequence[str] = ()) -> list[str]:
    """`keep`: names of the factory's quotes the estimator wrote, no amounts though they may look like one."""
    plain = MONEY_REF.sub("", text)
    kept = _kept_out(_kept(plain, keep))
    return [m.group(0) for p in (AMOUNT, WORD_AMOUNT) for m in p.finditer(plain) if not kept(m)]


def strip_amounts(text: str, keep: Sequence[str] = ()) -> str:
    out = text
    for p in (AMOUNT, WORD_AMOUNT):
        kept = _kept_out(_kept(out, keep))
        out = p.sub(lambda m: m.group(0) if kept(m) else "—", out)  # noqa: B023  # used within this pass
    return out


def check(
    text: str,
    state: ChatState,
    live_lines: set[str],
    allowed_refs: set[str] | None = None,
    live_instances: set[str] | None = None,
    keep: Sequence[str] = (),
) -> Checked:
    """`live_lines`: the ids the quote has now. Line, quote and instance names become real ids (`{{line:ln_…}}`) for
    the screen; money references stay, and the screen gets their amounts. `live_instances`: the instances the turn
    may point at (those a tool located); None accepts any this conversation named. `keep`: as in `amounts_in`."""
    out = Checked(text="")
    refs_ok = set(state.money) if allowed_refs is None else allowed_refs

    def line(match: re.Match[str]) -> str:
        real = state.real(match.group(1), "line")
        if real is None or real not in live_lines:
            out.invalid_refs.append(match.group(0))
            return ""
        if real not in out.line_ids:
            out.line_ids.append(real)
        return "{{line:" + real + "}}"

    def money(match: re.Match[str]) -> str:
        ref = match.group(1)
        if ref not in refs_ok:
            out.invalid_refs.append(match.group(0))
            return "—"
        out.money_refs.add(ref)
        return "{{" + ref + "}}"

    def named(kind: str, found: list[str]) -> Callable[[re.Match[str]], str]:
        def sub(match: re.Match[str]) -> str:
            real = state.real(match.group(1), kind)
            if real is None or (kind == "instance" and live_instances is not None and real not in live_instances):
                out.invalid_refs.append(match.group(0))
                return ""
            if real not in found:
                found.append(real)
            return "{{" + kind + ":" + real + "}}"

        return sub

    text = LINE_REF.sub(line, text)
    text = MONEY_REF.sub(money, text)
    text = QUOTE_REF.sub(named("quote", out.quote_ids), text)
    text = INSTANCE_REF.sub(named("instance", out.instance_ids), text)
    out.amounts = amounts_in(text, keep)
    out.text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return out


def valid_lines(names: list[str], state: ChatState, live_lines: set[str]) -> list[str]:
    """A UI action's lines: the ones that exist, as real ids; the rest are dropped."""
    out: list[str] = []
    for n in names:
        real = state.real(n, "line")
        if real is not None and real in live_lines and real not in out:
            out.append(real)
    return out


def for_model(text: str, state: ChatState) -> str:
    """The estimator's message as the model gets it: a reference the screen put in it (a clicked option with
    `{{quote:quo_…}}`) is named again (`{{quote:QT2}}`), so no id or quote name reaches the model. An id this
    conversation never named is dropped."""

    def sub(match: re.Match[str]) -> str:
        alias = state.alias_of(match.group(2))
        return "{{" + match.group(1) + ":" + alias + "}}" if alias else ""

    return SCREEN_REF.sub(sub, text)
