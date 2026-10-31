"""The 7 stages. Each takes a StageContext and returns its contract (00 §5.1). S05 ships stubs; later sessions
replace them one by one without touching the coordinator."""

from collections.abc import Callable

from pydantic import BaseModel

from ..context import StageContext
from . import s1_intake, s2_extraction, s3_symbols, s4_association, s5_matching, s6_validation, s7_pricing

Stage = Callable[[StageContext], BaseModel]

STAGES: dict[int, Stage] = {
    1: s1_intake.run,
    2: s2_extraction.run,
    3: s3_symbols.run,
    4: s4_association.run,
    5: s5_matching.run,
    6: s6_validation.run,
    7: s7_pricing.run,
}

# For the new-quote screen's stage list (prototype STAGES, line 761).
NAMES = {
    1: "קליטה וסיווג עמודים",
    2: "חילוץ ואריחים",
    3: "זיהוי סימנים",
    4: "שיוך טקסט ומיזוג",
    5: "התאמה לקטלוג",
    6: "בדיקה",
    7: "תמחור",
}
