"""A provider for tests and for running the pipeline without spending tokens."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..base import RawAnswer
from ..types import LLMRequest

Answer = dict[str, Any]


class FakeProvider:
    """Answers in order from a list, or from a function of the request: calls that run in parallel (stage 1
    classifies pages at the same time) need the function, so each request gets its own answer."""

    name = "fake"

    def __init__(self, answers: list[Answer] | Callable[[LLMRequest[Any]], Answer]):
        self._answer = answers if callable(answers) else None
        self._answers = [] if callable(answers) else list(answers)
        self.calls: list[tuple[str, str, str | None]] = []
        self.requests: list[LLMRequest[Any]] = []

    def complete_structured(self, request: LLMRequest[Any], model: str, retry_hint: str | None = None) -> RawAnswer:
        self.calls.append((request.stage, model, retry_hint))
        self.requests.append(request)
        if self._answer is not None:
            return RawAnswer(payload=self._answer(request), model=model, input_tokens=0, output_tokens=0)
        payload = self._answers.pop(0) if self._answers else {}
        return RawAnswer(payload=payload, model=model, input_tokens=0, output_tokens=0)
