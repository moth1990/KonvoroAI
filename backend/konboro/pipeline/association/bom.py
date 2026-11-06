"""Stage 4 on a BOM-only drawing (01 §5.8, S14 decision 3): each row of the BOM tables stage 1 read becomes an
instance, and the instances merge into components, in the contract of 04 §6.3.

For each item (`bom.table.items`: the rows after the row rules):
1. Its text is normalized as stage 2 normalizes a span (units, × between numbers), and its family and class come
   from the BOM words (`bom.terms`): "מא"ז" a breaker, "פחת" a residual-current device. An untyped "מפסק" leaves the
   class to stage 5 (05 §5.5.1). A row no word names stays, red, as `unknown`: a row left out is a product missing
   from the quote.
2. The spelling grammar (04 §5.1) reads its values. Every attribute's `source` is `bom` and has no span: the row is
   the evidence, and the instance keeps its row numbers and, from a picture, its box on the page (01 §5.8 item 2).
3. The confidence is the row's (the lowest of its cells, from a picture) times the lowest required value's parse
   confidence (04 §6.4, the row standing for the detection). A column mapping nobody confirmed keeps the row yellow.
Then the merge: rows with the same panel, family, class, values, model text and brand are one component, their
quantities added. A row with no readable quantity never merges and keeps quantity 0, uncertain: a quantity is never
made up.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from konboro.contracts.common import StageIssue
from konboro.contracts.merge import AttributeValue, Component, Instance
from konboro.pipeline.bom import table as bom_table
from konboro.pipeline.bom import terms
from konboro.pipeline.extraction import normalize
from konboro.pipeline.intake.drawing import name_key

from .config import DEFAULT, AssociationConfig
from .grammar import CONTEXT_KEYS, parse
from .merge import status
from .schemas import Schemas

UNKNOWN_FAMILY = "unknown"

ISSUES = {
    "bom_unknown_item": "שורה {rows} בכתב הכמויות: לא זיהינו איזה מוצר זה. בדקו את השורה.",
    "bom_quantity_unreadable": "שורה {rows} בכתב הכמויות: לא הצלחנו לקרוא כמות. בדקו את השורה.",
    "bom_mapping_unsure": "שורה {rows} בכתב הכמויות: מיפוי העמודות לא אושר. בדקו שהפריט והכמות נקראו מהעמודות הנכונות.",
    "missing_required": "חסר בכתב הכמויות: {names}. השלב הבא ינסה להשלים, או שהשורה תסומן לבדיקה.",
}


def _issue(code: str, page_id: str, **values: Any) -> StageIssue:
    severity = "warning" if code.startswith("bom_") else "info"
    return StageIssue(code=code, severity=severity, page_id=page_id, message=ISSUES[code].format(**values))  # type: ignore[arg-type]


@dataclass
class Row:
    """One item on its way to a component."""

    instance: Instance
    quantity: int | None
    signature: tuple[Any, ...]
    order: tuple[int, int]
    issues: list[StageIssue] = field(default_factory=list)


def read_item(
    item: bom_table.Item,
    page_id: str,
    panel_id: str,
    seq: int,
    sch: Schemas,
    cfg: AssociationConfig = DEFAULT,
    mapping_sure: bool = True,
) -> Row:
    raw = " ".join(x for x in (item.text, item.model) if x)
    text = normalize.normalize(
        normalize.Text(raw_text=raw, bbox=(0, 0, 0, 0), rotation=0, confidence=1.0, source="bom")
    ).text
    found = terms.family_of(item.text) or (terms.family_of(item.model) if item.model else None)
    family, cls = found if found else (UNKNOWN_FAMILY, terms.UNTYPED)
    names = sch.names(family)
    values: dict[str, AttributeValue] = {}
    parse_conf: dict[str, float] = {}
    context: dict[str, list[Any]] = defaultdict(list)
    for r in parse(text):
        if not r.fits(family):
            continue
        if r.key in names and r.key not in values:
            values[r.key] = AttributeValue(
                value=r.value, source="bom", confidence=round(r.confidence * item.confidence, 4), span_ids=[]
            )
            parse_conf[r.key] = r.confidence
        elif r.key in CONTEXT_KEYS and r.value not in context[r.key]:
            context[r.key].append(r.value)
    required = sch.required(family)
    found_required = [parse_conf[n] for n in required if n in parse_conf]
    confidence = round(item.confidence * (min(found_required) if found_required else 1.0), 4)
    issues: list[StageIssue] = []
    rows = f"{item.rows[0]}–{item.rows[-1]}" if len(item.rows) > 1 else str(item.rows[0])
    if family == UNKNOWN_FAMILY:
        confidence = min(confidence, cfg.missing_max)
        issues.append(_issue("bom_unknown_item", page_id, rows=rows))
    if item.quantity is None:
        confidence = min(confidence, cfg.missing_max)
        issues.append(_issue("bom_quantity_unreadable", page_id, rows=rows))
    if not mapping_sure:  # the mapping went on without the user (flag off, S14 decision 1): yellow at most
        confidence = min(confidence, round(cfg.accepted_from - 0.01, 4))
        issues.append(_issue("bom_mapping_unsure", page_id, rows=rows))
    missing = [n for n in required if n not in values]
    if missing and family != UNKNOWN_FAMILY:
        issues.append(_issue("missing_required", page_id, names=", ".join(missing)))
    tokens = [str(v) for v in context.get("model_token", [])]
    explicit = [item.text] + ([item.model] if item.model else []) + [t for t in tokens if t not in (item.text,)]
    brand = item.brand or next((str(v) for v in context.get("brand", [])), None)
    instance = Instance(
        instance_id=f"ins_b{seq:03d}_{item.rows[0]:04d}",
        det_id=None,
        page_id=page_id,
        panel_id=panel_id,
        bbox=item.bbox,
        family=family,
        symbol_class=cls,
        attributes={n: values.get(n) or AttributeValue(value=None, source=None, confidence=None) for n in names},
        multiplicity=item.quantity or 1,
        explicit_texts=_unique(explicit),
        brand_hint=brand,
        method="bom",
        status=status(confidence, cfg),  # type: ignore[arg-type]
        confidence=confidence,
        rows=item.rows,
        issues=issues,
    )
    model_text = tuple(sorted(t.casefold() for t in tokens))
    values_key = tuple((k, repr(v.value)) for k, v in sorted(values.items()))
    signature: tuple[Any, ...] = (panel_id, family, cls, values_key, model_text, (brand or "").casefold())
    if family == UNKNOWN_FAMILY or item.quantity is None:
        signature = (*signature, instance.instance_id)  # never merges
    return Row(instance, item.quantity, signature, (seq, item.rows[0]), issues)


def _unique(xs: list[str]) -> list[str]:
    out: list[str] = []
    for x in xs:
        if x and x not in out:
            out.append(x)
    return out


def rows(
    tables: list[tuple[str, bom_table.BomTable]],
    panel_ids: dict[str, str],
    fallback_panel: str | None,
    sch: Schemas,
    cfg: AssociationConfig = DEFAULT,
) -> list[Row]:
    """Every item of every table, in page and row order. `panel_ids`: panel name key → id (stage 1's panels)."""
    out: list[Row] = []
    first = next(iter(panel_ids.values()), None)
    for seq, (page_id, t) in enumerate(tables, start=1):
        for item in bom_table.items(t):
            name = bom_table.item_panel(item, t.panel_name or fallback_panel)
            panel_id = panel_ids.get(name_key(name)) or first
            if panel_id is None:
                continue  # stage 1 always gives a BOM-only drawing a panel; nothing to point at otherwise
            out.append(read_item(item, page_id, panel_id, seq, sch, cfg, t.mapping_sure))
    return out


def components(
    drawing_id: str, found: list[Row], cfg: AssociationConfig = DEFAULT, by_row: bool = False
) -> list[Component]:
    """`by_row`: a chat build's components are named by their first row, not their place, so a line keeps its key
    while the rows before it come and go (S27; `pipeline/bom/chat.py`)."""
    groups: dict[tuple[Any, ...], list[Row]] = defaultdict(list)
    for r in sorted(found, key=lambda r: r.order):
        groups[r.signature].append(r)
    prefix = drawing_id.removeprefix("drw_")
    out: list[Component] = []
    for n, group in enumerate(groups.values(), start=1):
        first = group[0].instance
        attrs: dict[str, AttributeValue] = {}
        for name, a in first.attributes.items():
            if a.value is None:
                attrs[name] = a
                continue
            confs = [r.instance.attributes[name].confidence or 1.0 for r in group]
            attrs[name] = a.model_copy(update={"confidence": min(confs)})
        confidence = round(min(r.instance.confidence for r in group), 4)
        texts: list[str] = []
        for r in group:
            texts += [t for t in r.instance.explicit_texts if t not in texts]
        known = [r.quantity for r in group if r.quantity is not None]
        out.append(
            Component(
                component_id=f"cmp_{prefix}_{group[0].order[1] if by_row else n:04d}",
                drawing_id=drawing_id,
                panel_id=first.panel_id,  # type: ignore[arg-type]
                family=first.family,
                symbol_class=first.symbol_class,
                attributes=attrs,
                explicit_texts=texts,
                brand_hint=first.brand_hint,
                quantity=sum(known),
                instance_ids=[r.instance.instance_id for r in group],
                confidence=confidence,
                status=status(confidence, cfg),  # type: ignore[arg-type]
            )
        )
    return out
