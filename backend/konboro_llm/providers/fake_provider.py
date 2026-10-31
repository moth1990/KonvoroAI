"""A provider for tests and for running the pipeline without spending tokens."""

from __future__ import annotations

from typing import Any

from ..base import RawAnswer
from ..types import LLMRequest


class FakeProvider:
    name = "fake"

    def __init__(self, answers: list[dict[str, Any]]):
        self._answers = list(answers)
        self.calls: list[tuple[str, str, str | None]] = []

    def complete_structured(self, request: LLMRequest[Any], model: str, retry_hint: str | None = None) -> RawAnswer:
        self.calls.append((request.stage, model, retry_hint))
        payload = self._answers.pop(0) if self._answers else {}
        return RawAnswer(payload=payload, model=model, input_tokens=0, output_tokens=0)
