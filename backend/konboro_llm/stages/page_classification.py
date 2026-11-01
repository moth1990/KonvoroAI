"""Pipeline step 1: what kind of page this is, and which panels and regions are on it (01 §5.4).

Input: the page upright, its longer side 1024 px, plus up to 2,000 characters of its text layer when it has one.
Output: one page kind from a closed list, with confidence; the panels and regions on it, as boxes on a 0–1000 grid
over the image; the title block as written. Code checks the answer afterwards (00 §7.2).
Never sent: prices, customer details, other drawings' results (01 §11).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from ..client import LLMClient
from ..types import ImageInput, LLMRequest, LLMResult

STAGE = "page_classification"

PageKindAnswer = Literal[
    "single_line_diagram",
    "control_diagram",
    "panel_front_view",
    "legend",
    "bom_table",
    "general_notes",
    "technical_data",
    "terminal_diagram",
    "title_cover",
    "factory_template",
    "other",
]

Grid = Annotated[int, Field(ge=0, le=1000)]
Box = tuple[Grid, Grid, Grid, Grid]

SYSTEM = """\
You classify one page of an electrical-panel drawing set for a panel-building factory in Israel. Text is usually \
Hebrew, sometimes English. The page image is upright as rendered; tell us if it is not.

Page kinds (pick exactly one):
- single_line_diagram: a single-line diagram of a panel (breakers, RCDs, busbars, outgoing circuits).
- control_diagram: a control or wiring diagram (contactors, relays, timers, push-buttons, pilot lamps, coils).
- panel_front_view: the panel's front or layout view (devices drawn as they sit in the enclosure).
- legend: a symbol legend.
- bom_table: a bill of materials table.
- general_notes: general notes or a written specification.
- technical_data: the panel's technical data sheet (enclosure size, IP, rated current, Icc, control voltage).
- terminal_diagram: a terminal-strip diagram.
- title_cover: a cover page or table of contents.
- factory_template: a fixed page the factory attaches to every project, with no devices of this project \
(conductor colour tables, tightening torques, label/sign tables).
- other: none of the above, or unsure.

Rules:
- Report only what is printed on the page. Anything not written there is null. Never guess.
- page_kind_confidence is your probability that page_kind is right. When unsure between a skipped kind \
(title_cover, factory_template) and a diagram, choose the diagram: a skipped diagram loses a panel.
- panels: every electrical panel drawn on the page, with its name as written (null if no name is written) and a \
box around its diagram. A page can hold several panels.
- regions: other areas of the page: notes_block (a framed block of notes or requirements; panel_ref = the name \
of the panel it sits next to, as written), feed_diagram (which panels feed which), title_block, legend.
- Boxes are [x0, y0, x1, y1] on a 0-1000 grid over the image, origin top-left.
- title_block: the fields as written. designer is the company or office that made the drawing, never a person. \
panel_name is the panel's name if the title block has a field for it. Dates are written day/month/year; return \
them as YYYY-MM-DD. status: for_info (לעיון), for_bidding (למכרז), for_execution (לביצוע), else null.
- orientation: how many degrees clockwise the image must turn to read upright (0 if it already reads upright).
- component_labels: whether devices carry tags like F1, Q2, C3 with explicit model numbers (tags_and_models), \
tags without models (tags_only), or neither (none). Use not_applicable for pages without devices.
- reasoning: one short sentence on what decided the kind.
"""


class PanelAnswer(BaseModel):
    name: str | None = Field(default=None, description="As written on the page; null if no name is written")
    bbox: Box
    confidence: float = Field(ge=0, le=1)


class RegionAnswer(BaseModel):
    region_kind: Literal["notes_block", "feed_diagram", "title_block", "legend"]
    bbox: Box
    panel_ref: str | None = Field(default=None, description="notes_block only: the nearby panel's name as written")
    confidence: float = Field(ge=0, le=1)


class TitleBlockAnswer(BaseModel):
    project_name: str | None = None
    designer: str | None = Field(default=None, description="The company or office, never a person")
    panel_name: str | None = None
    drawing_number: str | None = None
    revision: str | None = None
    date: str | None = Field(default=None, description="YYYY-MM-DD")
    status: Literal["for_info", "for_bidding", "for_execution"] | None = None


class ClassificationAnswer(BaseModel):
    page_kind: PageKindAnswer
    page_kind_confidence: float = Field(ge=0, le=1)
    orientation: Literal[0, 90, 180, 270] = 0
    component_labels: Literal["tags_and_models", "tags_only", "none", "not_applicable"]
    panels: list[PanelAnswer] = []
    regions: list[RegionAnswer] = []
    title_block: TitleBlockAnswer | None = None
    language: Literal["he", "en", "ru", "other"] | None = None
    reasoning: str


def user_text(page_no: int, page_count: int, file_name: str, text_excerpt: str) -> str:
    excerpt = text_excerpt.strip()
    lines = [f'Page {page_no} of {page_count}, file "{file_name}".']
    lines.append(f"Text layer of the page:\n{excerpt}" if excerpt else "The page has no usable text layer.")
    return "\n".join(lines)


def classify_page(
    client: LLMClient,
    image: ImageInput,
    page_no: int,
    page_count: int,
    file_name: str,
    text_excerpt: str = "",
    tenant_id: str | None = None,
) -> LLMResult[ClassificationAnswer]:
    return client.run(
        LLMRequest(
            stage=STAGE,
            system=SYSTEM,
            user_text=user_text(page_no, page_count, file_name, text_excerpt[:2000]),
            output_schema=ClassificationAnswer,
            images=[image],
            tenant_id=tenant_id,
            max_tokens=2048,
        )
    )
