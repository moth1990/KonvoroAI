"""The chat builder (13 §4.2, S27): an estimator's message, typed or transcribed, as BOM lines and changes.

The model is shown the message (amounts stripped by the caller, 08 §5.4), the build's panels and the draft's lines by
short name (`L1`: description and quantity; never a price, a cost or a customer), and the product words the BOM path
knows. It writes each product as a BOM line in the drawing's spelling (04 §5.1), with the words of the message it
came from, and each change to a line by its short name. Code checks every number against the message and every line
against the draft (`konboro.pipeline.bom.chat.check`), and stage 4's BOM reading turns the text into values: the
model never sets a family or a value itself.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..client import LLMClient
from ..types import LLMRequest, LLMResult

STAGE = "chat_bom_extraction"

SYSTEM = """\
You read what an estimator in an Israeli electrical-panel factory says about a panel they are quoting, typed or \
spoken and transcribed, and write it as lines of a bill of materials. They describe products ("12 מא"ז 1X16, פחת \
4X40") and correct what they described before ("לא 12, 10", "תוריד את הפחת", "עוד שניים כאלה").

How to write a product line (`text`):
- Start with the product word, from the list you are given, as the estimator meant it: "מא\"ז" for a miniature \
breaker, "מפסק" for a breaker or main switch whose type they didn't say, "פחת" for a residual-current device.
- Then its values as a drawing writes them: poles and current as "3X16A" (spoken "שלוש על שש עשרה"; "חד פאזי" is \
1P and "תלת פאזי" 3P), curve and current as "C16", breaking capacity "10kA", residual current "30mA", poles alone \
"4P". A brand or a model code ("ABB", "S203M") as they said it.
- Numbers in digits, a current or a current range with its "A" ("2.5-4" for a motor protector is "2.5-4A"). Write \
only values the estimator said, in this message: never a default, a typical value or a value you think is likely. \
"פחת 4X40" stays "פחת 4X40A", with no mA. A value said in words is written in digits.
- Keep units as said: never turn "0.03" into "30mA".

`quantity` is how many they said ("שנים עשר" = 12); 1 when they said none. `quote` is the exact words of the message \
the line came from, copied character for character. `panel` is the panel they named for it ("בלוח 2"), or null.

Changes to the draft's lines, by the line's short name (L1, L2…) as you are shown them, each with the product's \
catalog description and the words the estimator used for it ("נאמר"): `set_qty` with the new \
quantity ("לא 12, 10"), `add_qty` with how many to add ("עוד שניים כאלה"), `remove` ("תוריד את הפחת"). Never a \
change to a line you weren't shown. When the estimator repeats a product the draft has, with a count, that is an \
`add_qty` on its line, not a new line. `quote` is the words the change came from.

When something they said can't be written (a product with no current at all, or an unclear correction), leave it \
out and ask one short question in Hebrew in `question`, naming lines by what they are ("המפסק 4P 63A"), never by \
their short names, which the estimator doesn't see. Otherwise `question` is null. Never write a price or an amount \
of money anywhere."""

PROMPT = """\
Product words you may start a line with:
{terms}

Panels of this quote: {panels}

Lines of the draft:
{lines}
{previous}
Message:
{message}"""

PREVIOUS = """
The estimator's previous message, which you answered with a question (the message below may answer it; its numbers \
must still be in the message below):
{text}
Your question: {question}
"""


class ExtractedItem(BaseModel):
    text: str = Field(description='The product as a BOM line, e.g. "מא\\"ז 1X16A"')
    quantity: int = Field(ge=0)
    panel: str | None = None
    quote: str = Field(description="The words of the message it came from, exactly")


class ExtractedChange(BaseModel):
    line: str = Field(description="The line's short name, e.g. L2")
    action: Literal["set_qty", "add_qty", "remove"]
    quantity: int | None = None
    quote: str


class BuildAnswer(BaseModel):
    items: list[ExtractedItem] = []
    changes: list[ExtractedChange] = []
    question: str | None = None


def extract(
    client: LLMClient,
    message: str,
    lines: str,
    panels: str,
    product_words: str,
    tenant_id: str | None = None,
    previous: tuple[str, str] | None = None,
) -> LLMResult[BuildAnswer]:
    """`previous`: the message before and the question asked about it, when the last answer was a question."""
    before = PREVIOUS.format(text=previous[0], question=previous[1]) if previous else ""
    return client.run(
        LLMRequest(
            stage=STAGE,
            system=SYSTEM,
            user_text=PROMPT.format(
                terms=product_words, panels=panels, lines=lines or "(none yet)", previous=before, message=message
            ),
            output_schema=BuildAnswer,
            tenant_id=tenant_id,
            max_tokens=2048,
            effort="low",
        )
    )
