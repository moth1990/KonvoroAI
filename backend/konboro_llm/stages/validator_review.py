"""Pipeline step 6 (06 §6.4): one independent look at a panel, for what the rules don't cover ("a residential panel
with 40 breakers and no RCD", "a 95A contactor in a panel where everything else is up to 16A").

The model gets the panel's component table (family, values, quantity, tags and the catalog description, never a
price, a cost or a customer detail: 06 §12, CLAUDE.md non-negotiable 6), a picture of the panel's area on its page
when there is one, the feed tree as indented text, the designer's BOM in short, and the rules' findings so it does
not repeat them. Each issue it reports names the table's rows (`c01`) or a box in the picture; code drops one that
names neither, caps its severity at a warning and keeps at most five (`konboro.pipeline.validation.agent`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..client import LLMClient
from ..types import ImageInput, LLMRequest, LLMResult

STAGE = "validator_review"

SYSTEM = """\
You review one electrical panel of a price quote that a panel-building factory is preparing from a drawing. The \
components were read from the drawing by other steps, and rules already checked them. You look for what a careful \
estimator would notice and the rules did not: a quantity that does not fit the panel, a component that seems to be \
in the picture but not in the table, a value that does not fit the rest of the panel, a component that seems to be \
of another kind. You do not check the electrical design or the regulations: only whether the reading and the quote \
look right. Report only what you can point at; when nothing stands out, report nothing."""

PROMPT = """\
Panel: {panel}

Components (one row each; ref | kind | values | quantity | tags | catalog item):
{components}

{tree}{bom}Already found by the rules (do not repeat these):
{findings}

{image}Report at most 5 issues. For each:
- type: suspicious_quantity, missing_component, inconsistent_attributes, wrong_family or other.
- component_ids: the refs from the table (c01, c02 …) the issue is about; empty only for a component missing from \
the table, which then needs a bbox.
- bbox: [x0, y0, x1, y1] in the picture's pixels, for a component you see in the picture; else null.
- message: one or two short sentences in Hebrew, for the estimator, saying what to check.
- confidence: from 0 to 1."""


class ReviewIssue(BaseModel):
    type: Literal["suspicious_quantity", "missing_component", "inconsistent_attributes", "wrong_family", "other"]
    component_ids: list[str] = []
    bbox: list[float] | None = None
    message: str
    confidence: float = Field(ge=0, le=1)


class ReviewAnswer(BaseModel):
    issues: list[ReviewIssue] = []


def review(
    client: LLMClient,
    panel: str,
    components: str,
    tree: str,
    bom: str,
    findings: str,
    image: ImageInput | None,
    image_size: tuple[int, int] | None,
    tenant_id: str | None = None,
) -> LLMResult[ReviewAnswer]:
    seen = (
        f"The picture is the panel's area on its page, {image_size[0]}×{image_size[1]} pixels.\n\n"
        if image is not None and image_size
        else "There is no picture of this panel.\n\n"
    )
    return client.run(
        LLMRequest(
            stage=STAGE,
            system=SYSTEM,
            user_text=PROMPT.format(
                panel=panel,
                components=components,
                tree=f"Feed tree:\n{tree}\n\n" if tree else "",
                bom=f"The designer's BOM, in short:\n{bom}\n\n" if bom else "",
                findings=findings or "(none)",
                image=seen,
            ),
            images=[image] if image is not None else [],
            output_schema=ReviewAnswer,
            tenant_id=tenant_id,
            max_tokens=2_000,
            effort="low",
        )
    )
