"""Pipeline step 5 (05 §5.8): choose one catalog item from the few candidates code left, when no rule decides.

The model gets the component as read (its family, values with their sources, the text written beside it), 3 to 5
candidates that all fit its electrical values, the notes that concern its family and the factory's preferences in
short. Never a price, a cost, a margin or a customer detail (05 §12, CLAUDE.md non-negotiable 6): the candidates carry
sku, brand, series, description and attributes only. It chooses one of them or none; code checks the sku is on the
list (`konboro.pipeline.matching.agent`).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..client import LLMClient
from ..types import LLMRequest, LLMResult

STAGE = "catalog_disambiguation"

SYSTEM = """\
You choose the catalog item for one component of an electrical-panel drawing, for a panel-building factory. Every \
candidate already fits the component's electrical values; you decide between them from what is written in the \
drawing and from the factory's preferences. You choose only from the candidates, or choose none."""

PROMPT = """\
Component:
{component}

Candidates:
{candidates}

{context}
Choose:
- chosen_sku: the sku of the candidate that fits, exactly as listed; null when what is written does not decide.
- confidence: from 0 to 1, how sure you are.
- reason: one or two short sentences, in Hebrew, for the estimator.
- missing_attributes: the attribute names, from the candidates' attributes, whose value would decide when you \
choose null; otherwise empty."""


class CatalogAnswer(BaseModel):
    chosen_sku: str | None
    confidence: float = Field(ge=0, le=1)
    reason: str
    missing_attributes: list[str] = []


def choose(
    client: LLMClient,
    component: str,
    candidates: str,
    context: str,
    tenant_id: str | None = None,
    error: str | None = None,
) -> LLMResult[CatalogAnswer]:
    retry = f"\nYour previous answer was refused: {error}\n" if error else ""
    return client.run(
        LLMRequest(
            stage=STAGE,
            system=SYSTEM,
            user_text=PROMPT.format(component=component, candidates=candidates, context=context) + retry,
            output_schema=CatalogAnswer,
            tenant_id=tenant_id,
            max_tokens=1_500,
            effort="low",
        )
    )
