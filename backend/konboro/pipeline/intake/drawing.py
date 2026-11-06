"""Drawing-level decisions of stage 1, from the pages' results: the panels (01 §5.4, §12 item 2), the input kind
(01 §4.4) and whether an upload marked as a new version is one (01 §4.5)."""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from konboro.contracts.intake import InputKind

REVISION_SHARED_PAGES = 0.5  # 01 §4.5: at least half the pages identical by sha256
# 01 §4.4 (S28b decision 2): only a panel factory's drawing set has its technical-data form and its fixed template
# pages (5.7). Every factory drawing of the golden set has one; neither designer's plan has.
FACTORY_PAGE_KINDS = ("technical_data", "factory_template")
DEFAULT_PANEL = "לוח 1"


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
    # Other names the classifier gave parts of this panel ("לוח מטבח-חלק א"), on any page: a factory drawing's
    # panel is one (S28b), and a notes block or a front view that names a part belongs to it.
    aliases: list[str] = field(default_factory=list)


def name_key(name: str) -> str:
    return " ".join(name.replace('"', "").split()).casefold()


def merge_panels(pages: Sequence[PagePanels], title_panel: str | None, *, one_panel: bool = False) -> list[MergedPanel]:
    """One list of panels for the drawing, from the process pages only (01 §5.5: count only from `process`).

    The same name on several pages is one panel (01 §12 item 2). A panel drawn without a name belongs to the panel
    the title block names; failing that, to the drawing's only named panel; failing that, to one unnamed panel.
    A process page on which no panel was found still belongs to that panel, so no page is left out.

    `one_panel` (a factory drawing, 01 §4.4, S28b decision 1): a factory draws one panel per drawing set, and what
    the classifier reads as several panels are its cells or parts ("לוח מטבח-חלק א", "שדה 2"). They are one panel.
    """
    process = [p for p in pages if p.route == "process"]
    if not process:
        return []
    if one_panel:
        return [_one_panel(pages, process, title_panel)]
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
            add(default or DEFAULT_PANEL, page.page_id, None, 1.0)
        for name, bbox, confidence in page.panels:
            add(name or default or DEFAULT_PANEL, page.page_id, bbox, confidence)
    return list(merged.values())


def _one_panel(pages: Sequence[PagePanels], process: Sequence[PagePanels], title_panel: str | None) -> MergedPanel:
    """A factory drawing's one panel, with every process page and every box the classifier drew. Its name: the
    title block's "שם הלוח" (01 §12 item 2); failing that, the name every other name extends ("לוח מטבח" of
    "לוח מטבח-חלק א"); failing that, the name on the most process pages, the first one on a tie (S28b decision 3)."""
    names: list[str] = []
    for page in [*process, *(p for p in pages if p.route != "process")]:
        for n, _, _ in page.panels:
            if n and n.strip() and name_key(n) not in {name_key(x) for x in names}:
                names.append(n.strip())
    name = (title_panel or "").strip() or _base(names) or _most_pages(names, process) or DEFAULT_PANEL
    panel = MergedPanel(name=name, aliases=[n for n in names if name_key(n) != name_key(name)])
    for page in process:
        panel.page_ids.append(page.page_id)
        for _, bbox, confidence in page.panels:
            panel.bboxes.setdefault(page.page_id, []).append(list(bbox))
            panel.confidence = min(panel.confidence, confidence)
    return panel


def _most_pages(names: Sequence[str], process: Sequence[PagePanels]) -> str | None:
    def pages(name: str) -> int:
        return sum(1 for p in process if any(n and name_key(n) == name_key(name) for n, _, _ in p.panels))

    counted = [(pages(n), -i, n) for i, n in enumerate(names)]
    best = max(counted, default=None)
    return best[2] if best and best[0] > 0 else None


def _base(names: Sequence[str]) -> str | None:
    """The name every other name is, or extends by a separate word or a mark ("לוח מטבח" → "לוח מטבח-חלק א",
    "לוח מטבח שדה 2"; not "לוח 1" → "לוח 10")."""
    for base in sorted(names, key=lambda n: len(name_key(n))):
        b = name_key(base)
        if all(name_key(n) == b or (name_key(n).startswith(b) and not name_key(n)[len(b)].isalnum()) for n in names):
            return base
    return None


def is_factory_set(kinds: Sequence[str]) -> bool:
    """01 §4.4 (S28b decision 2): a drawing with the factory's technical-data page or its template pages."""
    return any(k in FACTORY_PAGE_KINDS for k in kinds)


def panel_resolver(
    merged: list[MergedPanel], panel_ids: dict[str, str], *, one: bool
) -> Callable[[str | None], str | None]:
    """The panel a name the classifier wrote belongs to: by its name or one of its parts' (`aliases`). In a factory
    drawing's one panel (S28b decision 1) every name is that panel's, even one no panel box carried."""
    by_name = dict(panel_ids)
    for p in merged:
        for alias in p.aliases:
            by_name.setdefault(name_key(alias), panel_ids[name_key(p.name)])
    only = next(iter(panel_ids.values())) if one and len(panel_ids) == 1 else None

    def resolve(name: str | None) -> str | None:
        if not name:
            return None
        return by_name.get(name_key(name)) or only

    return resolve


def input_kind(formats: Sequence[str], kinds: Sequence[str]) -> InputKind:
    """01 §4.4. A drawing with a panel factory's own pages (its technical-data form, its fixed template pages) is a
    factory drawing; any other drawing is a designer's plan (S28b decision 2). Until S28b the classifier's reading
    of the device tags decided, and a one-sheet designer's plan whose devices carry tags and models (25.26.100)
    came out a factory drawing."""
    if all(f in ("xlsx", "csv") for f in formats) or (kinds and all(k == "bom_table" for k in kinds)):
        return "bom_only"
    if "bom_table" in kinds:
        return "mixed"
    return "factory_drawing" if is_factory_set(kinds) else "designer_plan"


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
