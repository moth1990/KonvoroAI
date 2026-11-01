"""Pipeline step 1, context (01 §5.5): structured content from pages and regions that are not diagrams.

One call per item, each on an image of just that page or region:
- the drawing's title block, read once per drawing from a crop of the region the classifier found (S08 decision);
- `technical_data` pages and a panel's `notes_block` (§5.5.1): the same requirements schema;
- `panel_front_view` pages: the panels, their sizes, and the device tags shown on the front;
- a `feed_diagram` region (§5.5.2): which panel is fed from which, by what cable;
- `general_notes` pages: the notes as Markdown.

Every value comes from the image or is null: the prompt says so and code checks the shapes afterwards.
Never sent: prices, customer details, other drawings' results (01 §11).
"""

from __future__ import annotations

from typing import Literal, TypeVar

from pydantic import BaseModel, Field

from ..client import LLMClient
from ..types import ImageInput, LLMRequest, LLMResult
from .page_classification import TitleBlockAnswer

STAGE = "context_extraction"

RULES = """\
Rules: copy only what is written in the image. Anything not written is null; never guess or fill in a typical \
value. Text is usually Hebrew, sometimes English. Numbers keep the unit asked for in the field name."""

T = TypeVar("T", bound=BaseModel)


class Enclosure(BaseModel):
    height_mm: float | None = None
    width_mm: float | None = None
    depth_mm: float | None = None
    ip: str | None = Field(default=None, description="e.g. IP55")
    ik: str | None = Field(default=None, description="e.g. IK10")
    color: str | None = Field(default=None, description="e.g. RAL-7035")
    material: str | None = None
    installation: str | None = Field(default=None, description="e.g. wall-mounted, floor-standing, outdoor")


class PanelRequirements(BaseModel):
    """01 §5.5 technical data and §5.5.1 a panel's notes block: the same schema."""

    enclosure: Enclosure = Enclosure()
    rated_current_a: float | None = None
    icc_ka: float | None = Field(default=None, description="Rated/conditional short-circuit current, kA")
    control_voltage: str | None = Field(default=None, description="As written, e.g. 230V-AC")
    standard: str | None = Field(default=None, description="e.g. 61439-2")
    form: str | None = Field(default=None, description="Form of separation, e.g. 2B")
    ambient_c: float | None = None
    min_breaking_capacity_ka: float | None = None
    spare_space_pct: float | None = None
    required_services: list[str] = Field(default=[], description="Services the panel builder must provide, as written")
    cable_entry: str | None = None


class FrontViewPanel(BaseModel):
    name: str | None = None
    height_mm: float | None = None
    width_mm: float | None = None
    depth_mm: float | None = None


class FrontView(BaseModel):
    panels: list[FrontViewPanel] = []
    designators: list[str] = Field(
        default=[], description="Every device tag on the front, as written, ranges kept (R1-R7)"
    )


class Feed(BaseModel):
    panel: str
    fed_from: str | None = None
    cable: str | None = None
    length_m: float | None = None


class FeedDiagram(BaseModel):
    feeds: list[Feed] = []


class GeneralNotes(BaseModel):
    markdown: str = Field(description="The notes as Markdown, one bullet per note, in the original language")


Kind = Literal["title_block", "technical_data", "notes_block", "panel_front_view", "feed_diagram", "general_notes"]

PROMPTS: dict[Kind, tuple[str, type[BaseModel]]] = {
    "title_block": (
        "This is the title block of an electrical-panel drawing. Read its fields. designer is the company or "
        "office that made the drawing, never a person's name. panel_name is the panel's name if a field gives it. "
        "Dates are written day/month/year; return YYYY-MM-DD. status: for_info (לעיון), for_bidding (למכרז), "
        "for_execution (לביצוע), else null.",
        TitleBlockAnswer,
    ),
    "technical_data": (
        "This is a panel's technical data sheet. Read the enclosure and the electrical requirements.",
        PanelRequirements,
    ),
    "notes_block": (
        "This is a framed notes block next to one panel on a drawing. Read the panel requirements it states.",
        PanelRequirements,
    ),
    "panel_front_view": (
        "This is a panel's front view. List the panels with their sizes if written, and every device tag shown.",
        FrontView,
    ),
    "feed_diagram": (
        "This is a feed diagram. List each panel with the panel it is fed from, the cable and its length.",
        FeedDiagram,
    ),
    "general_notes": ("This page holds general notes. Transcribe them as Markdown.", GeneralNotes),
}


def extract(client: LLMClient, kind: Kind, image: ImageInput, tenant_id: str | None = None) -> LLMResult[BaseModel]:
    prompt, schema = PROMPTS[kind]
    return client.run(
        LLMRequest(
            stage=STAGE,
            system=f"You read electrical-panel drawings for a panel-building factory.\n{RULES}",
            user_text=prompt,
            output_schema=schema,
            images=[image],
            tenant_id=tenant_id,
            max_tokens=4096,
        )
    )
