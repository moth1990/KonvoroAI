"""Chat history compaction (08 §5.2.1): older turns of a conversation in one paragraph, by a small model.

The turns it gets already carry only references for money (`{{$T1}}`), never amounts; the caller still checks the
summary for amounts before saving it (`konboro.chat.check`).
"""

from __future__ import annotations

from pydantic import BaseModel

from ..client import LLMClient
from ..types import LLMRequest, LLMResult

STAGE = "chat_compaction"

SYSTEM = """\
You summarize the older part of a conversation between an estimator and the assistant of a quoting system, so the \
conversation can continue without it. Keep what was asked, what was found, which proposals were prepared (CH1…) and \
what the estimator decided, with the line and panel names (L3, B1) as they appear. Write one short Hebrew paragraph. \
Never write an amount of money, a price, a currency sign or a reference like {{$T1}}."""


class Summary(BaseModel):
    summary: str


def compact(client: LLMClient, previous: str | None, turns: str, tenant_id: str | None = None) -> LLMResult[Summary]:
    before = f"Summary so far:\n{previous}\n\n" if previous else ""
    return client.run(
        LLMRequest(
            stage=STAGE,
            system=SYSTEM,
            user_text=f"{before}Older turns:\n{turns}",
            output_schema=Summary,
            tenant_id=tenant_id,
            max_tokens=1024,
        )
    )
