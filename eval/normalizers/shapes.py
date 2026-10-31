"""One normalizer per label shape (dev-strategy §6). Each takes the parsed `labels.json` and, when the drawing has
one, `actual_quote.json`, and returns the canonical drawing."""

from typing import Any

from ..canonical import CanonComponent, CanonPanel, Checksums, GoldenDrawing
from . import common

Labels = dict[str, Any]
Quote = dict[str, Any] | None


def _drawing(
    folder: str, labels: Labels, quote: Quote, panels: list[CanonPanel], checksums: Checksums | None
) -> GoldenDrawing:
    return GoldenDrawing(
        id=folder,
        file=labels["file"],
        input_kind=labels["input_kind"],
        pages=common.pages(labels.get("pages", [])),
        panels=tuple(panels),
        audit=common.audit(quote),
        quote_total=common.quote_total(quote),
        checksums=checksums,
    )


def _summary(labels: Labels, products: str = "products") -> Checksums | None:
    summary = labels.get("summary")
    return Checksums(products=summary[products], units=summary["units"]) if summary else None


def bom_list(folder: str, labels: Labels, quote: Quote) -> GoldenDrawing:
    """26-993: `bom[]` for the one panel. `outside_scope[]` is outside the panel (prepare-only), not a component."""
    components = [
        CanonComponent(
            family=row["family"],
            designators=common.designators(row.get("designators")),
            attributes=common.attributes(row.get("attributes")),
            qty=row["qty"],
            label=row["product"],
        )
        for row in labels["bom"]
    ]
    panel = CanonPanel(name=labels["title_block"]["panel"], components=tuple(components))
    return _drawing(folder, labels, quote, [panel], _summary(labels))


def component_list(folder: str, labels: Labels, quote: Quote) -> GoldenDrawing:
    """NEVIS-1: `components[]` with `attrs`, where a `resolved` block overrides what the drawing says (FNV: 3 poles,
    confirmed by the real quote). `derived_expected[]` (the cabinet, busbars) is stage 7's job, not a component."""
    components = []
    for row in labels["components"]:
        attrs = common.attributes(row.get("attrs"))
        attrs.update({k: v for k, v in (row.get("resolved") or {}).items() if k != "by"})
        components.append(
            CanonComponent(
                family=row["family"],
                designators=common.designators(row.get("designators")),
                attributes=attrs,
                qty=row["qty"],
                label=" ".join(row.get("model_tokens") or []) or row["family"],
            )
        )
    panel = CanonPanel(name=labels["title_block"]["panel"], components=tuple(components))
    return _drawing(folder, labels, quote, [panel], None)


def panel_list(folder: str, labels: Labels, quote: Quote) -> GoldenDrawing:
    """6199-2-50: `panels[].components[]`, scored by family and attributes since a designer plan has no designators
    (S06 decision). `outside_panel[]` is drawn in another location. Each panel's merged `bom[]` only gives the
    product checksum."""
    panels, products, units = [], 0, 0
    for p in labels["panels"]:
        components = [
            CanonComponent(
                family=row["family"],
                attributes=common.attributes(row.get("attributes")),
                qty=row["qty"],
                supply_scope=row.get("supply_scope", "in_panel"),
                label=row["item"],
            )
            for row in p["components"]
        ]
        panels.append(CanonPanel(name=p["name"], components=tuple(components)))
        products += len(p["bom"])
        units += sum(row["qty"] for row in p["bom"])
    return _drawing(folder, labels, quote, panels, Checksums(products=products, units=units))


def handwritten_rows(folder: str, labels: Labels, quote: Quote) -> GoldenDrawing:
    """BOM-HW-1: a photographed, handwritten BOM. `rows[]` already merges the form's mistakes (`merged_rows`). No
    page list: the photo is the one page, and stage 1 has nothing labelled to score but `input_kind`."""
    components = [
        CanonComponent(
            family=row["family"],
            attributes=common.attributes(row.get("attributes")),
            qty=row["qty"],
            label=row["product"],
        )
        for row in labels["rows"]
    ]
    panel = CanonPanel(name=labels["header"]["panel"], components=tuple(components))
    return _drawing(folder, labels, quote, [panel], _summary(labels, "rows"))


def priced_rows(folder: str, labels: Labels, quote: Quote) -> GoldenDrawing:
    """NURSERY-1: `rows[]` with prices and no attribute block; current and poles are read from the product name.
    `front_view_only` designators are leftovers on the front view, not components (confirmed)."""
    components = [
        CanonComponent(
            family=row["family"],
            designators=common.designators(row.get("designators")),
            attributes=common.attributes_from_text(row["product"]),
            qty=row["qty"],
            label=row["product"],
        )
        for row in labels["rows"]
    ]
    panel = CanonPanel(name=labels["title_block"]["panel"], components=tuple(components))
    return _drawing(folder, labels, quote, [panel], _summary(labels))
