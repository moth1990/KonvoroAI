"""What a stage gets to work with: the tenant's session, its files, the outputs of the stages before it, and the
model gateway (every LLM call goes through `llm`, CLAUDE.md non-negotiable 2)."""

from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from konboro.contracts import STAGE_OUTPUTS
from konboro.db.models import Drawing, StageRun
from konboro.services.storage import Storage
from konboro_llm import LLMClient

M = TypeVar("M", bound=BaseModel)


@dataclass
class StageContext:
    session: Session  # inside tenant_session: RLS limits every query to this tenant
    storage: Storage
    drawing: Drawing
    stage: int
    llm: LLMClient  # every answered call is written to llm_calls for this tenant and drawing

    @property
    def tenant_id(self) -> str:
        return self.drawing.tenant_id

    @property
    def trace_id(self) -> str:
        return str(self.drawing.trace_id)

    def output(self, stage: int, model: type[M]) -> M:
        """A previous stage's contract, read back from S3 (00 §5: a stage reads only what the stages before it
        wrote)."""
        if STAGE_OUTPUTS[stage] is not model:
            raise TypeError(f"stage {stage} writes {STAGE_OUTPUTS[stage].__name__}, not {model.__name__}")
        run = self.session.get_one(StageRun, (self.tenant_id, self.drawing.id, stage))
        if run.output_key is None:
            raise LookupError(f"stage {stage} has no output for {self.drawing.id}")
        return model.model_validate_json(self.storage.get(self.tenant_id, run.output_key))
