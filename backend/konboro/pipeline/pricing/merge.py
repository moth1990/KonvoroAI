"""07 §7.1 (S27b, `catalog_lines`): one line per product in a panel. Pure, like the engine.

Stage 7 builds a line per component first (`lines.panel_lines`), and the estimator's choices for a component (a product
picked, an alternative, an attribute set, a missing line resolved) apply to that line, so a change of product moves
the component. Then the lines of the components that came to the same product, in the same panel and the same group,
become one:

| What | The merged line |
| --- | --- |
| key | `p:<panel>:<group>:<product>`: the catalog item, `prd:<factory product>` or `sku:<maker>:<sku>` |
| quantity | the members' added |
| designators, boxes, circuit notes | joined, through `component_ids` |
| the colour's reasons | every member's, once each; of the confidences, the lowest |
| approved | when every member is (a draft from before the flag, S27b decision 5) |
| a kit part, an accessory | a child line under the merged device, merged with its likes there (S27b decision 4) |

A line with no product waits for a decision (`pending`): it stays a line per component, red, unpriced, until the user
decides, and then joins its product's line. Labor, services, consumables and derived items are not touched.
"""

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from typing import Any

from .lines import Draft

PRODUCT_TYPES = frozenset({"component"})


def product_ref(line: Draft) -> str | None:
    """What a line is, as a product: the catalog item, else the factory's product, else the maker's SKU."""
    if line.catalog_item_id:
        return line.catalog_item_id
    if line.product_id:
        return "prd:" + line.product_id
    if line.sku:
        return f"sku:{line.manufacturer or ''}:{line.sku}"
    return None


def waiting(line: Draft) -> bool:
    """07 §7.1: a component or a missing row with no product."""
    return line.line_type in ("component", "missing") and product_ref(line) is None and line.parent is None


def _reasons(lines: Sequence[Draft]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    confidence: dict[str, Any] | None = None
    for ln in lines:
        for r in ln.reasons:
            if r.get("source") == "confidence":
                if confidence is None or float(r.get("value") or 0) < float(confidence.get("value") or 0):
                    confidence = r
            elif r not in out:
                out.append(r)
    return ([confidence] if confidence else []) + out


def _one(key: str, members: Sequence[Draft], parent: str | None) -> Draft:
    first = members[0]
    if len(members) == 1 and first.key == key:
        return first
    component_ids: list[str] = []
    for ln in members:
        for c in ln.component_ids or ([ln.component_id] if ln.component_id else []):
            if c not in component_ids:
                component_ids.append(c)
    approved = [ln.approved_at for ln in members]
    # a draft from before the flag: a member's quantity or supplier set on its own line stays the merged line's
    edits: dict[str, Any] = {}
    if any("qty" in ln.edits for ln in members):
        edits["qty"] = format(sum((ln.qty for ln in members), Decimal(0)).normalize(), "f")
    supplier = next((ln.edits["supplier_id"] for ln in members if ln.edits.get("supplier_id")), None)
    if supplier:
        edits["supplier_id"] = supplier
    return replace(
        first,
        key=key,
        parent=parent,
        qty=sum((ln.qty for ln in members), Decimal(0)),
        component_id=component_ids[0] if component_ids else first.component_id,
        component_ids=component_ids,
        boxes=[b for ln in members for b in ln.boxes],
        reasons=_reasons(members),
        issue_ids=sorted({i for ln in members for i in ln.issue_ids}),
        approved_at=min(a for a in approved if a) if all(approved) else None,
        edits=edits,
        members=[ln.key for ln in members],
    )


def merge(lines: Sequence[Draft]) -> list[Draft]:
    """A panel's lines, in their order, each product once among the top lines and once under each device."""
    heads: dict[tuple[Any, ...], list[Draft]] = {}
    order: list[tuple[str, Any]] = []
    renamed: dict[str, str] = {}
    for ln in lines:
        if ln.parent is not None:
            continue
        ref = product_ref(ln)
        if ln.line_type not in PRODUCT_TYPES or ref is None:
            order.append(("as_is", ln))
            continue
        group = (ln.panel_id, ln.line_group, ref)
        if group not in heads:
            heads[group] = []
            order.append(("head", group))
        heads[group].append(ln)
    for group, members in heads.items():
        key = f"p:{group[0]}:{group[1] or ''}:{group[2]}"
        for ln in members:
            renamed[ln.key] = key
    children: dict[tuple[str, str], list[Draft]] = {}
    child_order: dict[str, list[tuple[str, str]]] = {}
    loose: dict[str, list[Draft]] = {}
    for ln in lines:
        if ln.parent is None:
            continue
        parent = renamed.get(ln.parent, ln.parent)
        ref = product_ref(ln)
        if ref is None:
            loose.setdefault(parent, []).append(replace(ln, parent=parent))
            continue
        k = (parent, ref)
        if k not in children:
            children[k] = []
            child_order.setdefault(parent, []).append(k)
        children[k].append(ln)
    out: list[Draft] = []

    def emit_children(parent_key: str) -> None:
        for k in child_order.get(parent_key, []):
            out.append(_one(f"{parent_key}>{k[1]}", children[k], parent_key))
        out.extend(loose.get(parent_key, []))

    for kind, value in order:
        if kind == "as_is":
            out.append(value)
            emit_children(value.key)
        else:
            members = heads[value]
            head = _one(renamed[members[0].key], members, None)
            out.append(head)
            emit_children(head.key)
    return out


def member_keys(lines: Sequence[Draft]) -> dict[str, str]:
    """A component line's key → the key of the line it is in now."""
    return {m: ln.key for ln in lines for m in (ln.members or [ln.key])}
