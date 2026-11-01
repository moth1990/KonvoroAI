"""Drawing-level decisions of stage 1, from the pages' results: the panels (01 §5.4, §12 item 2), the input kind
(01 §4.4) and whether an upload marked as a new version is one (01 §4.5)."""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from konboro.contracts.intake import InputKind

REVISION_SHARED_PAGES = 0.5  # 01 §4.5: at least half the pages identical by sha256


@dataclass
class PagePanels:
    page_id: str
    route: str
    panels: list[tuple[str | None, tuple[float, float, float, float], float]]  # name, bbox, confidence


@dataclass
class MergedPanel:
    name: str
    page_ids: list[str] = field(default_factory=list)
    bboxes: dict[str, list[list[float]]] = field(default_factory=dict)
    confidence: float = 1.0


def name_key(name: str) -> str:
    return " ".join(name.replace('"', "").split()).casefold()


def merge_panels(pages: Sequence[PagePanels], title_panel: str | None) -> list[MergedPanel]:
    """One list of panels for the drawing, from the process pages only (01 §5.5: count only from `process`).

    The same name on several pages is one panel (01 §12 item 2). A panel drawn without a name belongs to the panel
    the title block names; failing that, to the drawing's only named panel; failing that, to one unnamed panel.
    A process page on which no panel was found still belongs to that panel, so no page is left out.
    """
    process = [p for p in pages if p.route == "process"]
    if not process:
        return []
    named = {name_key(n) for p in process for n, _, _ in p.panels if n}
    default = title_panel or (next(n for p in process for n, _, _ in p.panels if n) if len(named) == 1 else None)
    merged: dict[str, MergedPanel] = {}

    def add(name: str, page_id: str, bbox: tuple[float, float, float, float] | None, confidence: float) -> None:
        panel = merged.setdefault(name_key(name), MergedPanel(name=name))
        if page_id not in panel.page_ids:
            panel.page_ids.append(page_id)
        if bbox is not None:
            panel.bboxes.setdefault(page_id, []).append(list(bbox))
        panel.confidence = min(panel.confidence, confidence)

    for page in process:
        if not page.panels:
            add(default or "לוח 1", page.page_id, None, 1.0)
        for name, bbox, confidence in page.panels:
            add(name or default or "לוח 1", page.page_id, bbox, confidence)
    return list(merged.values())


def input_kind(formats: Sequence[str], kinds: Sequence[str], labels: Sequence[str]) -> InputKind:
    """01 §4.4. `labels` are the classifier's `component_labels` on the diagram pages. Telling a factory's drawing
    from a designer's plan by its symbols waits for stage 3 (S12); until then the classifier's reading of the device
    tags stands in: most diagram pages with tags and models → a factory drawing."""
    if all(f in ("xlsx", "csv") for f in formats) or (kinds and all(k == "bom_table" for k in kinds)):
        return "bom_only"
    if "bom_table" in kinds:
        return "mixed"
    tagged = sum(1 for label in labels if label == "tags_and_models")
    return "factory_drawing" if labels and tagged * 2 > len(labels) else "designer_plan"


def drawing_number_key(number: str | None) -> str | None:
    if not number:
        return None
    return re.sub(r"[\s\-_/.]+", "", number).casefold() or None


def is_revision(
    previous_number: str | None, number: str | None, previous_pages: set[str], pages: Sequence[str]
) -> bool:
    """01 §4.5 (S08 decision: either is enough): the same drawing number in the title block, or at least half of
    the new drawing's pages identical to the previous drawing's by sha256."""
    a, b = drawing_number_key(previous_number), drawing_number_key(number)
    if a is not None and a == b:
        return True
    if not pages:
        return False
    shared = sum(1 for h in pages if h in previous_pages)
    return shared / len(pages) >= REVISION_SHARED_PAGES
