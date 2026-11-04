"""The quote brief every turn starts from (08 §5.2): panels, lines per panel and per colour, the main families and
brands. No line list and no amounts: the model asks the tools for what it needs. The truth is the quote, not the
conversation, so the brief is built again from the quote's current state each turn (08 §5.2.1)."""

from collections import Counter

from .lines import QuoteLines
from .state import ChatState

STATUS_HE = {"green": "ירוק", "yellow": "צהוב", "red": "אדום"}
TOP = 6


def brief(ql: QuoteLines, state: ChatState) -> str:
    v = ql.view
    status = "נשלחה ללקוח ונעולה (שינוי יפתח גרסה חדשה)" if v.status == "sent" else "טיוטה"
    out = [f'Quote "{v.name}", version {v.version} ({status}). {len(ql.lines)} lines.']
    for panel_id, name in ql.panels():
        mine = [ln for ln in ql.lines if ln.panel_id == panel_id]
        colours = Counter(ln.status for ln in mine)
        counts = ", ".join(f"{STATUS_HE[s]} {colours[s]}" for s in ("red", "yellow", "green") if colours[s])
        alias = state.name("panel", panel_id) if panel_id else "-"
        out.append(f'- Panel {alias} "{name}": {len(mine)} lines ({counts})')
    families = Counter(ln.family for ln in ql.lines if ln.family)
    if families:
        out.append("Families: " + ", ".join(f"{f} {n}" for f, n in families.most_common(TOP)))
    brands = Counter(ln.manufacturer for ln in ql.lines if ln.manufacturer)
    if brands:
        out.append("Brands: " + ", ".join(f"{b} {n}" for b, n in brands.most_common(TOP)))
    kinds = Counter(ln.line_type for ln in ql.lines)
    out.append("Line types: " + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items())))
    if v.findings:
        out.append(f"Open findings from the validator: {len(v.findings)}")
    if ql.removed:
        out.append(f"Derived lines the estimator removed: {len(ql.removed)} (query_lines with include_removed)")
    return "\n".join(out)
