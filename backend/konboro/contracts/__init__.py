"""Stage contracts (00 §5): what each stage hands the next, field for field from the specs' §6.

Each stage writes one of these as JSON to S3 (`stage_runs.output_key`) and the next stage reads it back. A change
to a model is a change to the spec that defines it and to every spec that consumes it (00 §5).
"""

from pydantic import BaseModel

from .detection import DetectionResult
from .extraction import ExtractionResult
from .intake import IntakeResult
from .matching import MatchingResult
from .merge import MergeResult
from .pricing import QuoteVersionResult
from .validation import ValidationResult

STAGE_OUTPUTS: dict[int, type[BaseModel]] = {
    1: IntakeResult,
    2: ExtractionResult,
    3: DetectionResult,
    4: MergeResult,
    5: MatchingResult,
    6: ValidationResult,
    7: QuoteVersionResult,
}

__all__ = [
    "STAGE_OUTPUTS",
    "DetectionResult",
    "ExtractionResult",
    "IntakeResult",
    "MatchingResult",
    "MergeResult",
    "QuoteVersionResult",
    "ValidationResult",
]
