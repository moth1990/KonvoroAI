"""From the matching to the differences (11 §5.4), their money (11 §5.5) and the summary (11 §6).

For every component with units no line took:
1. a line's included item covers it ("כולל פסי צבירה", "+נתיכים"): "כלול", no difference (11 §5.3);
2. its family is on the tenant's auxiliary list: `not_a_difference`, no money (S15 decision 4);
3. a line of the same family with units left disagrees on one value: `attribute_mismatch`, the pair consumed (it
   explains both leftovers, so it comes before a short quantity);
4. a line matched it but had no units left: `qty_short` on that line;
5. else `missing_in_quote`.
For every line with units left:
- its components are drawn more times than they are, and the line counts the drawings: `possible_double_count`;
- it took nothing, and repeats word for word, at the same quantity, an earlier line that took exactly its own
  quantity: `possible_double_count` on the twin's components, at the twin's confidence (BUG-074: quote 10298's
  "משנה זרם 100/5 × 3" twice for T1-T3);
- else, when it took something: `qty_over`; when it took nothing: `extra_in_quote`. An enclosure line with no
  enclosure among the components stands for the panel's cabinet, which comes from the data page (07 §7.4): matched.
`arithmetic` comes from the quote's own numbers; `drawing_conflict` when a matched component has values that
disagree inside the drawing (04 §5.5 `attribute_conflict`): the line shows which one the quote took.

Confidence (11 §5.4): the lowest of the component's, the line's reading, and the match's. A missing item while some
line could not be signed is at most 0.55: that line may be it. A line not found in the drawing is at most 0.55: the
drawing's reading misses things too. Below 0.6, a difference is shown apart ("לבדוק").

Money (11 §5.5), `Decimal` only: a price from a line with the same signature, else from a line of the same family
and poles (the nearest current, then the quote's order), else none. The tenant's price list needs catalog matching
(stage 5, S20) and is not searched yet. `qty_short` is priced at its own line. An attribute mismatch risks the price
difference to the drawn product, never less than 0. `qty_over` and `possible_double_count` are over-charged, apart.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from konboro.contracts.audit import (
    AuditedLine,
    AuditSummary,
    Difference,
    DifferenceSeverity,
    DifferenceType,
    Evidence,
    LineStatus,
    PriceSource,
    SuggestedLine,
)
from konboro.db.ids import new_id

from .match import Assignment, DrawnComponent, assign, compare
from .quote import ArithmeticBreak, QuoteLine, QuoteRead, check
from .signature import ENCLOSURE, UNTYPED, Signature, sign

SHOWN_FROM = 0.6  # 11 §5.4, §10
UNSURE_CAP = 0.55
MATCH_CONFIDENCE = {0: 0.95, 1: 0.85}
NEAR_CONFIDENCE = 0.8
ZERO = Decimal(0)

SEVERITY: dict[DifferenceType, DifferenceSeverity] = {
    "missing_in_quote": "high",
    "qty_short": "high",
    "qty_over": "medium",
    "possible_double_count": "medium",
    "attribute_mismatch": "high",
    "extra_in_quote": "low",
    "arithmetic": "high",
    "drawing_conflict": "info",
    "not_a_difference": "info",
}
NOT_COUNTED: frozenset[DifferenceType] = frozenset({"drawing_conflict", "not_a_difference"})
PRICED: frozenset[DifferenceType] = frozenset({"missing_in_quote", "qty_short", "attribute_mismatch"})
OVER: frozenset[DifferenceType] = frozenset({"qty_over", "possible_double_count"})

FAMILY_HE = {
    "circuit_breaker": 'מא"ז',
    "rcd": "מפסק פחת",
    "rcbo": 'מא"ז משולב פחת',
    "contactor": "מגען",
    "relay": "ממסר",
    "voltage_relay": "ממסר חוסר מתח",
    "overload_relay": "ממסר תרמי",
    "timer": "ממסר זמן",
    "impulse_relay": "ממסר צעד",
    "relay_coil": "סליל ממסר",
    "shunt_trip": "סליל הפסקה",
    "current_transformer": "משנה זרם",
    "energy_meter": "מונה",
    "measuring_instrument": "מכשיר מדידה",
    "surge_protector": "מגן מתח יתר",
    "indicator_lamp": "נורת סימון",
    "push_button": "לחצן",
    "selector_switch": "בורר",
    "fuse": "נתיך",
    "switch_disconnector": "מנתק",
    "changeover_switch": "מחליף",
    "ats": "מחליף אוטומטי",
    "terminal": "מהדק",
    "aux_contact": "מגע עזר",
    "temperature_controller": "בקר טמפרטורה",
    "time_switch": "שעון שבת",
    "socket_outlet": "שקע",
    "busbar": "פסי צבירה",
    "busbar_block": "פסי צבירה",
    ENCLOSURE: "ארון",
}
CLASS_HE = {
    "mccb": "מפסק בתיבה יצוקה",
    "motor_protection": "מגן מנוע",
    "fuse_base": "בסיס נתיך",
    "emergency_button": "לחצן חירום",
}


def _num(v: Any) -> str:
    f = float(v)
    return str(int(f)) if f.is_integer() else f"{f:g}"


def describe(family: str, cls: str, values: dict[str, Any]) -> str:
    """A product as a factory writes it: 'מא"ז 2X16A', 'מגען 3P', 'משנה זרם 125/5A'."""
    name = CLASS_HE.get(cls) or FAMILY_HE.get(family) or family
    if family == "circuit_breaker" and cls == UNTYPED:
        name = "מפסק"
    poles, current = values.get("poles"), values.get("current_a")
    neutral = values.get("neutral")
    parts: list[str] = []
    if poles is not None and current is not None:
        parts.append(f"1P+N {_num(current)}A" if neutral and int(poles) == 1 else f"{_num(poles)}X{_num(current)}A")
    elif poles is not None:
        parts.append(f"{_num(poles)}P" + ("+N" if neutral else ""))
    elif current is not None:
        parts.append(f"{_num(current)}A")
    if "range_min_a" in values and "range_max_a" in values:
        parts.append(f"{_num(values['range_min_a'])}–{_num(values['range_max_a'])}A")
    if "ratio_primary_a" in values:
        parts.append(f"{_num(values['ratio_primary_a'])}/{_num(values.get('ratio_secondary_a', 5))}A")
    return " ".join([name, *parts])


def _designators(cs: list[DrawnComponent]) -> list[str]:
    out: list[str] = []
    for c in cs:
        out += [d for d in c.designators if d not in out]
    return out


def _evidence(cs: list[DrawnComponent]) -> list[Evidence]:
    by_page: dict[int, list[str]] = defaultdict(list)
    for c in cs:
        for instance_id, page in c.instances:
            by_page[page].append(instance_id)
    return [Evidence(page_no=p, instance_ids=ids) for p, ids in sorted(by_page.items())]


def _des_text(des: list[str]) -> str:
    return f" ({', '.join(des)})" if des else ""


def _money(x: Decimal) -> str:
    return f"{x:,.2f}"


def unit_price(line: QuoteLine) -> Decimal | None:
    if line.unit_price is not None:
        return line.unit_price
    if line.total is not None and line.qty:
        return line.total / line.qty
    return None


@dataclass
class Price:
    unit: Decimal
    source: PriceSource


def find_price(c: DrawnComponent, lines: list[QuoteLine], sigs: dict[int, Signature]) -> Price | None:
    """11 §5.5 priorities 1 and 2, from the quote itself."""
    best: tuple[tuple[int, float, int], Price] | None = None
    for ln in lines:
        price = unit_price(ln)
        sig = sigs[ln.index]
        if price is None or sig.family is None:
            continue
        p = compare(sig, c)
        if p is not None and not p.near and sig.current_max_a is None:
            key, kind = (0, 0.0, ln.index), "same_signature"
        elif sig.family == c.family and sig.values.get("poles") is not None and same_poles(sig, c):
            distance = abs(float(sig.values.get("current_a") or 0) - float(c.values.get("current_a") or 0))
            key, kind = (1, distance, ln.index), "same_family_poles"
        else:
            continue
        if best is None or key < best[0]:
            best = (key, Price(price, PriceSource(kind=kind, line_index=ln.index)))  # type: ignore[arg-type]
    return best[1] if best else None


def same_poles(sig: Signature, c: DrawnComponent) -> bool:
    if c.values.get("poles") is None:
        return False
    return int(sig.values["poles"]) == int(c.values["poles"]) and bool(sig.values.get("neutral")) == bool(
        c.values.get("neutral")
    )


@dataclass
class Outcome:
    lines: list[AuditedLine]
    differences: list[Difference]
    summary: AuditSummary
    included: dict[str, int] = field(default_factory=dict)  # component → the line whose included item covers it


def _line_status(statuses: dict[int, LineStatus], index: int, status: LineStatus) -> None:
    rank = ["matched", "arithmetic", "not_in_drawing", "quantity_differs", "attribute_differs"]
    if rank.index(status) > rank.index(statuses.get(index, "matched")):
        statuses[index] = status


def audit(
    read: QuoteRead,
    components: list[DrawnComponent],
    auxiliary: frozenset[str] = frozenset(),
    new_diff_id: Callable[[], str] = lambda: new_id("dif"),
) -> Outcome:
    lines = read.lines
    by_index = {ln.index: ln for ln in lines}
    sigs = {ln.index: sign(ln.text, ln.model) for ln in lines}
    comps = {c.component_id: c for c in components}
    a: Assignment = assign([(ln.index, sigs[ln.index], ln.qty) for ln in lines], components)
    diffs: list[Difference] = []
    statuses: dict[int, LineStatus] = {}
    unsigned = any(not s.signed for s in sigs.values())

    def add(
        kind: DifferenceType,
        confidence: float,
        message: str,
        cs: list[DrawnComponent] = [],  # noqa: B006
        line: QuoteLine | None = None,
        drawing_qty: Decimal | int | None = None,
        quote_qty: Decimal | int | None = None,
        amount: Decimal | None = None,
        suggested: SuggestedLine | None = None,
        family: str | None = None,
    ) -> None:
        diffs.append(
            Difference(
                diff_id=new_diff_id(),
                type=kind,
                severity=SEVERITY[kind],
                confidence=round(max(0.0, min(1.0, confidence)), 4),
                family=family or (cs[0].family if cs else (sigs[line.index].family if line else None)),
                designators=_designators(cs),
                drawing_qty=Decimal(drawing_qty) if drawing_qty is not None else None,
                quote_qty=Decimal(quote_qty) if quote_qty is not None else None,
                quote_line_index=line.index if line else None,
                evidence=_evidence(cs),
                suggested_line=suggested,
                message=message,
                amount=amount,
                component_ids=[c.component_id for c in cs],
            )
        )

    # included items (11 §5.3): a component no line took, of a family a line says it includes
    included: dict[str, int] = {}
    for c in components:
        if a.component_left[c.component_id] <= 0:
            continue
        for ln in lines:
            if any(_accepts_family(inc.family, inc.cls, c) for inc in sigs[ln.index].included):
                included[c.component_id] = ln.index
                a.component_left[c.component_id] = 0
                break

    # lines whose leftover units are the drawing's repeated views (11 §5.4): not open to a near pairing
    doubled = {ln.index for ln in lines if _doubled(ln, a, comps)}

    # components with units left
    short_by_line: dict[int, list[tuple[DrawnComponent, int]]] = defaultdict(list)
    for c in components:
        left = a.component_left[c.component_id]
        if left <= 0:
            continue
        if c.family in auxiliary:
            add(
                "not_a_difference",
                c.confidence,
                f"{describe(c.family, c.cls, c.values)} × {left}{_des_text(c.designators)}: "
                "חומר עזר בהגדרות המפעל, ולכן לא הבדל",
                [c],
                drawing_qty=left,
                quote_qty=0,
            )
            continue
        near = [
            p
            for (_, cid), p in a.pairs.items()
            if cid == c.component_id
            and p.near
            and p.close
            and p.line not in doubled
            and (a.line_left[p.line] is None or (a.line_left[p.line] or 0) > 0)
        ]
        if near:
            p = min(near, key=lambda p: (len(p.conflicts), p.line))
            ln = by_index[p.line]
            line_left = a.line_left[p.line]
            n = left if line_left is None else min(left, int(line_left))
            if line_left is not None:
                a.line_left[p.line] = line_left - n
            a.component_left[c.component_id] -= n
            a.taken[(p.line, c.component_id)] = n
            price = find_price(c, lines, sigs)
            own = unit_price(ln)
            risk = max(ZERO, price.unit - own) * n if price is not None and own is not None else None
            add(
                "attribute_mismatch",
                min(c.confidence, ln.confidence, NEAR_CONFIDENCE),
                f'בהצעה "{ln.text}" (שורה {ln.index}). בשרטוט {describe(c.family, c.cls, c.values)}'
                f"{_des_text(c.designators)}",
                [c],
                ln,
                drawing_qty=n,
                quote_qty=n,
                amount=risk,
                suggested=SuggestedLine(
                    description=describe(c.family, c.cls, c.values),
                    qty=Decimal(n),
                    unit_price=price.unit if price else None,
                    price_source=price.source if price else None,
                ),
            )
            _line_status(statuses, ln.index, "attribute_differs")
            left -= n
            if left <= 0:
                continue
        good = [p for (_, cid), p in a.pairs.items() if cid == c.component_id and not p.near]
        if good:
            best = min(good, key=lambda p: (p.tier, -p.agreed, p.line))
            short_by_line[best.line].append((c, left))
            continue
        price = find_price(c, lines, sigs)
        conf = c.confidence if not unsigned else min(c.confidence, UNSURE_CAP)
        desc = describe(c.family, c.cls, c.values)
        add(
            "missing_in_quote",
            conf,
            f"בשרטוט {left} × {desc}{_des_text(c.designators)}, ואין להם שורה בהצעה"
            if left > 1
            else f"בשרטוט {desc}{_des_text(c.designators)}, ואין לו שורה בהצעה",
            [c],
            drawing_qty=left,
            quote_qty=0,
            amount=price.unit * left if price else None,
            suggested=SuggestedLine(
                description=desc,
                qty=Decimal(left),
                unit_price=price.unit if price else None,
                price_source=price.source if price else None,
            ),
        )

    for index, shorts in short_by_line.items():
        ln = by_index[index]
        took = [comps[cid] for cid, _ in a.absorbed(index)]
        cs = took + [c for c, _ in shorts if c not in took]
        short = sum(n for _, n in shorts)
        drawn = sum(n for _, n in a.absorbed(index)) + short
        own = unit_price(ln)
        pair_tier = min(a.pairs[(index, c.component_id)].tier for c, _ in shorts)
        add(
            "qty_short",
            min([c.confidence for c in cs] + [ln.confidence, MATCH_CONFIDENCE[pair_tier]]),
            f'בהצעה {_num(ln.qty or 0)} × "{ln.text}" (שורה {ln.index}). בשרטוט {drawn}{_des_text(_designators(cs))}',
            cs,
            ln,
            drawing_qty=drawn,
            quote_qty=ln.qty,
            amount=own * short if own is not None else None,
            suggested=SuggestedLine(
                description=ln.text,
                qty=Decimal(short),
                unit_price=own,
                price_source=PriceSource(kind="this_line", line_index=ln.index) if own is not None else None,
            ),
        )
        _line_status(statuses, index, "quantity_differs")

    # lines with units left
    has_enclosure = any(c.family == ENCLOSURE for c in components)
    for ln in lines:
        rest = a.line_left[ln.index]
        sig = sigs[ln.index]
        took = [comps[cid] for cid, _ in a.absorbed(ln.index)]
        if rest is None or rest <= 0:
            continue
        if not took:
            if sig.family == ENCLOSURE and not has_enclosure:
                continue  # the panel's cabinet, from the data page (07 §7.4)
            if (twin := _twin(ln, lines, sigs, a)) is not None:
                twin_took = [comps[cid] for cid, _ in a.absorbed(twin.index)]
                tier = min(a.pairs[(twin.index, c.component_id)].tier for c in twin_took)
                drawn = sum(n for _, n in a.absorbed(twin.index))
                own = unit_price(ln)
                add(
                    "possible_double_count",
                    min([c.confidence for c in twin_took] + [ln.confidence, twin.confidence, MATCH_CONFIDENCE[tier]]),
                    f'שורה {ln.index} בהצעה, {_num(rest)} × "{ln.text}", חוזרת על שורה {twin.index}. '
                    f"בשרטוט {drawn}{_des_text(_designators(twin_took))}: ייתכן שנספרה פעמיים",
                    twin_took,
                    ln,
                    drawing_qty=drawn,
                    quote_qty=ln.qty,
                    amount=-own * rest if own is not None else None,
                )
                _line_status(statuses, ln.index, "quantity_differs")
                continue
            add(
                "extra_in_quote",
                min(ln.confidence, UNSURE_CAP),
                f'שורה {ln.index} בהצעה, "{ln.text}", ולא מצאנו אותה בשרטוט',
                line=ln,
                drawing_qty=0,
                quote_qty=ln.qty,
            )
            _line_status(statuses, ln.index, "not_in_drawing")
            continue
        drawn = sum(n for _, n in a.absorbed(ln.index))
        drawings = sum(c.drawings for c in took)
        own = unit_price(ln)
        tier = min(a.pairs[(ln.index, c.component_id)].tier for c in took)
        conf = min([c.confidence for c in took] + [ln.confidence, MATCH_CONFIDENCE[tier]])
        amount = -own * rest if own is not None else None
        des = _designators(took)
        if drawings > drawn and ln.qty == drawings:
            pages = sorted({p for c in took for p in c.pages})
            where = f"בעמודים {', '.join(str(p) for p in pages)}" if len(pages) > 1 else f"ב-{drawings} מקומות"
            add(
                "possible_double_count",
                conf,
                f'בהצעה {_num(ln.qty)} × "{ln.text}" (שורה {ln.index}). בשרטוט {drawn}{_des_text(des)}, '
                f"שמצויר {where}: ייתכן שנספר פעמיים",
                took,
                ln,
                drawing_qty=drawn,
                quote_qty=ln.qty,
                amount=amount,
            )
        else:
            add(
                "qty_over",
                conf,
                f'בהצעה {_num(ln.qty or 0)} × "{ln.text}" (שורה {ln.index}). בשרטוט {drawn}{_des_text(des)}',
                took,
                ln,
                drawing_qty=drawn,
                quote_qty=ln.qty,
                amount=amount,
            )
        _line_status(statuses, ln.index, "quantity_differs")

    # conflicts inside the drawing that a line settles (11 §5.4 drawing_conflict)
    for c in components:
        if not c.conflicts:
            continue
        for index, _ in a.lines_of(c.component_id):
            ln = by_index[index]
            add(
                "drawing_conflict",
                c.confidence,
                f"בשרטוט ערכים סותרים ל-{', '.join(c.designators) or describe(c.family, c.cls, c.values)} "
                f'({", ".join(c.conflicts)}). בהצעה: "{ln.text}"',
                [c],
                ln,
            )
            break

    for br in check(read):
        _arithmetic(add, br, by_index, statuses)

    audited = _audited(lines, sigs, a, statuses, included)
    return Outcome(audited, diffs, summarize(audited, diffs, components), included)


def _twin(ln: QuoteLine, lines: list[QuoteLine], sigs: dict[int, Signature], a: Assignment) -> QuoteLine | None:
    """BUG-074: the earlier line `ln` repeats word for word (the same signature and text) at the same quantity, when
    that line took exactly its quantity from the drawing. Another quantity, or a line the drawing did not fill, may be
    a second item the reading missed: that stays "not in the drawing"."""
    for other in lines:
        if other.index >= ln.index or ln.qty is None or other.qty != ln.qty or sigs[other.index] != sigs[ln.index]:
            continue
        if not sigs[ln.index].signed or a.line_left[other.index] != 0:
            continue
        if sum(n for _, n in a.absorbed(other.index)) == other.qty:
            return other
    return None


def _doubled(ln: QuoteLine, a: Assignment, comps: dict[str, DrawnComponent]) -> bool:
    """The line's leftover units are the drawing's repeated views: it counts the drawings, not the devices."""
    left = a.line_left[ln.index]
    taken = a.absorbed(ln.index)
    if left is None or left <= 0 or not taken:
        return False
    drawings = sum(comps[cid].drawings for cid, _ in taken)
    return ln.qty == drawings and drawings > sum(n for _, n in taken)


def _accepts_family(family: str, cls: str, c: DrawnComponent) -> bool:
    probe = Signature(family=family, cls=cls)
    p = compare(probe, c)
    return p is not None


def _arithmetic(
    add: Callable[..., None], br: ArithmeticBreak, by_index: dict[int, QuoteLine], statuses: dict[int, LineStatus]
) -> None:
    if br.line_index is None:
        add(
            "arithmetic",
            0.95,
            f"סכום השורות בהצעה {_money(br.expected)}, ובהצעה כתוב {_money(br.written)}",
            amount=br.delta,
            family=None,
        )
        return
    ln = by_index[br.line_index]
    add(
        "arithmetic",
        min(ln.confidence, 0.95),
        f"שורה {ln.index}: {_num(ln.qty or 0)} × {_money(ln.unit_price or ZERO)} = {_money(br.expected)}, "
        f"ובהצעה כתוב {_money(br.written)}",
        line=ln,
        quote_qty=ln.qty,
        amount=br.delta,
    )
    _line_status(statuses, ln.index, "arithmetic")


def _audited(
    lines: list[QuoteLine],
    sigs: dict[int, Signature],
    a: Assignment,
    statuses: dict[int, LineStatus],
    included: dict[str, int],
) -> list[AuditedLine]:
    out: list[AuditedLine] = []
    for ln in lines:
        took = a.absorbed(ln.index)
        covered = [cid for cid, i in included.items() if i == ln.index]
        out.append(
            AuditedLine(
                index=ln.index,
                text=ln.text,
                qty=ln.qty,
                unit_price=ln.unit_price,
                total=ln.total,
                confidence=ln.confidence,
                page_no=ln.page_no,
                rows=ln.rows,
                bbox=ln.bbox,
                signature=sigs[ln.index].describe(),
                status=statuses.get(ln.index, "matched"),
                component_ids=[cid for cid, _ in took] + covered,
                matched_qty=Decimal(sum(n for _, n in took)),
            )
        )
    return out


def summarize(lines: list[AuditedLine], diffs: list[Difference], components: list[DrawnComponent]) -> AuditSummary:
    counted = [d for d in diffs if d.type not in NOT_COUNTED]
    shown = [d for d in counted if d.confidence >= SHOWN_FROM]
    missing = [d for d in counted if d.type in ("missing_in_quote", "qty_short")]

    def short_units(d: Difference) -> int:
        if d.type == "missing_in_quote":
            return int(d.drawing_qty or 0)
        return int((d.drawing_qty or 0) - (d.quote_qty or 0))

    at_risk = sum((d.amount for d in shown if d.type in PRICED and d.amount is not None and d.amount > 0), ZERO)
    over = sum((-d.amount for d in shown if d.type in OVER and d.amount is not None), ZERO)
    return AuditSummary(
        quote_lines=len(lines),
        lines_matched=sum(1 for ln in lines if ln.status == "matched"),
        drawing_components=len(components),
        differences=len(counted),
        info_notes=sum(1 for d in diffs if d.type == "drawing_conflict"),
        missing_items=sum(short_units(d) for d in missing),
        value_at_risk=at_risk.quantize(Decimal("0.01")),
        missing_items_without_price=sum(short_units(d) for d in missing if d.amount is None),
        over_charged=over.quantize(Decimal("0.01")),
        not_differences=sum(1 for d in diffs if d.type == "not_a_difference"),
        to_check=len(counted) - len(shown),
    )
