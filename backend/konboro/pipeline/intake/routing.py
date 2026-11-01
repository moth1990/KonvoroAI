"""Routing (01 §7) and when to ask the user to confirm (01 §5.6).

The rule behind every row: when in doubt between skipping and processing, process. A skipped process page is a
panel missing from the quote; an extra processed page costs pennies (01 §1).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from konboro.contracts.intake import PageKind, Route

CONFIRM_THRESHOLD = 0.85  # confirm_threshold (01 §5.6), also the bar for skipping a page (01 §7)

PROCESS_KINDS: frozenset[PageKind] = frozenset({"single_line_diagram", "control_diagram", "other"})
CONTEXT_KINDS: frozenset[PageKind] = frozenset(
    {"panel_front_view", "legend", "bom_table", "general_notes", "technical_data", "terminal_diagram"}
)
SKIP_KINDS: frozenset[PageKind] = frozenset({"title_cover", "factory_template"})  # only when sure
DIAGRAM_KINDS: frozenset[PageKind] = frozenset({"single_line_diagram", "control_diagram"})


def route(kind: PageKind, confidence: float, has_panels: bool = False) -> Route:
    """01 §7. `title_cover` and `factory_template` are skipped only at ≥ 0.85; below that they are processed. A
    page on which the classifier also found a panel is never skipped: the answer contradicts itself, so the page
    is processed."""
    if kind in CONTEXT_KINDS:
        return "context"
    if kind in SKIP_KINDS:
        return "skip" if confidence >= CONFIRM_THRESHOLD and not has_panels else "process"
    return "process"


@dataclass(frozen=True)
class RoutedPage:
    page_kind: PageKind
    page_kind_confidence: float
    classified_by: str


def confirmation_reasons(pages: Sequence[RoutedPage], panel_count: int, hinted_panels: int | None = None) -> list[str]:
    """01 §5.6: why the user has to look before decoding goes on. Empty means it goes on by itself. Pages the
    user classified are settled. A spreadsheet-only upload has no diagram by nature, so it never asks for one."""
    reasons: list[str] = []
    unsure = [p for p in pages if p.classified_by != "user" and p.page_kind_confidence < CONFIRM_THRESHOLD]
    if unsure:
        reasons.append("low_confidence")
    if (
        pages
        and not any(p.page_kind in DIAGRAM_KINDS for p in pages)
        and any(p.page_kind != "bom_table" for p in pages)
    ):
        reasons.append("no_diagram_pages")
    if hinted_panels is not None and hinted_panels != panel_count:
        reasons.append("panel_count_mismatch")
    return reasons
