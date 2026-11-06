"""The chat home's routing (13 §4.3, S27): what an estimator typed on "מה בונים היום?", when code can't tell.

Code routes first (`konboro.services.home_route`): a panel description, an audit request, a question that names one
of the factory's quotes, the price list. Only what is left comes here, and the model picks one intent from a closed
list. It is shown the text alone, with amounts stripped: never a quote's name, a customer or a price (S25b decision 1,
non-negotiable 6). Code decides where each intent goes, and an unclear one gets a short question with choices, never an
action ("the routing is a suggestion, not an action").
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..client import LLMClient
from ..types import LLMRequest, LLMResult

STAGE = "home_intent"

Intent = Literal["build", "new_drawing", "audit", "quote_question", "price_list", "unclear"]

SYSTEM = """\
You route what an estimator in an electrical-panel factory typed on the home screen of a quoting system. Choose one \
intent:
- build: they describe a panel or list products to quote without a drawing ("לוח של מטבח עם 6 מא\"זים ופחת").
- new_drawing: they want to quote from a drawing or a file they have ("יש לי שרטוט חדש", "להעלות קובץ").
- audit: they want an existing quote of theirs checked against its drawing ("תבדוק לי את ההצעה ששלחתי").
- quote_question: a question or a change about a quote that already exists ("מה חסר בהצעה של הגן?", "תשנה את \
ההצעה האחרונה לשניידר").
- price_list: about their price list or product prices ("כמה עולה אצלי מגען?", "לעדכן מחיר").
- unclear: anything else, or when two intents fit equally.
`confidence` is from 0 to 1. Never choose an intent you are not sure of: unclear is a good answer."""


class IntentAnswer(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0, le=1)


def route(client: LLMClient, text: str, tenant_id: str | None = None) -> LLMResult[IntentAnswer]:
    return client.run(
        LLMRequest(
            stage=STAGE,
            system=SYSTEM,
            user_text=f"Typed on the home screen:\n{text}",
            output_schema=IntentAnswer,
            tenant_id=tenant_id,
            max_tokens=256,
        )
    )
