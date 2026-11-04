"""The answer check (08 §8.2), in code, on every answer before the screen sees it.

| Check | On failure |
| --- | --- |
| every `{{line:L3}}` is a line this conversation named and the quote still has | removed from the text, `invalid_ref` |
| every `{{$T1}}` was created in this conversation | replaced by "—", `invalid_ref` |
| no amount of money written in the text (₪, ש"ח, שקל, a decimal price) | sent back once; then the number is removed |
| a UI action points at existing lines | dropped |

Quantities, currents (16A), poles, line counts and percentages the estimator gave are not money.
"""

import re
from dataclasses import dataclass, field

from .state import ChatState

LINE_REF = re.compile(r"\{\{\s*line:\s*([A-Za-z]+\d+)\s*\}\}")
MONEY_REF = re.compile(r"\{\{\s*(\$[A-Z]\d+)\s*\}\}")
INSTANCE_REF = re.compile(r"\{\{\s*instance:[^}]*\}\}")
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


@dataclass
class Checked:
    text: str
    line_ids: list[str] = field(default_factory=list)  # real ids, in order of first mention
    money_refs: set[str] = field(default_factory=set)
    invalid_refs: list[str] = field(default_factory=list)
    amounts: list[str] = field(default_factory=list)  # amounts written as numbers (the caller asks once again)


def amounts_in(text: str) -> list[str]:
    plain = MONEY_REF.sub("", text)
    return [m.group(0) for m in AMOUNT.finditer(plain)] + [m.group(0) for m in WORD_AMOUNT.finditer(plain)]


def strip_amounts(text: str) -> str:
    out = AMOUNT.sub("—", text)
    return WORD_AMOUNT.sub("—", out)


def check(text: str, state: ChatState, live_lines: set[str], allowed_refs: set[str] | None = None) -> Checked:
    """`live_lines`: the ids the quote has now. Line names become real ids (`{{line:ln_…}}`) for the screen; money
    references stay, and the screen gets their amounts."""
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

    text = LINE_REF.sub(line, text)
    text = MONEY_REF.sub(money, text)
    text = INSTANCE_REF.sub("", text)  # instances come with S25b's explain_line
    out.amounts = amounts_in(text)
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
