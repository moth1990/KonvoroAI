"""The 7 stages. Each takes a StageContext and returns its contract (00 §5.1). S05 ships stubs; later sessions
replace them one by one without touching the coordinator."""

from collections.abc import Callable

from pydantic import BaseModel

from ..audit import step as audit_step
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
    8: audit_step.run,  # an audit drawing goes here after stage 4 (11 §5, S15 decision 2)
}

# The names the user sees, everywhere in the app (01 §4.6: plain Hebrew, no abbreviations; prototype STAGES). The
# specs keep their technical names ("חילוץ ואריחים", "שיוך ומיזוג").
NAMES = {
    1: "קליטת השרטוט",
    2: "קריאת הטקסט",
    3: "זיהוי הרכיבים",
    4: "חיבור תוויות לרכיבים",
    5: "התאמה לקטלוג",
    6: "בדיקה",
    7: "תמחור",
    8: "בדיקת ההצעה",
}
