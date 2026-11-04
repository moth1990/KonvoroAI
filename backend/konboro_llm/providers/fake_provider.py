"""A provider for tests and for running the pipeline without spending tokens."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..base import RawAnswer, RawToolCall, RawTurn
from ..types import LLMRequest, ToolLoopRequest, Turn

Answer = dict[str, Any]


class FakeProvider:
    """Answers in order from a list, or from a function of the request: calls that run in parallel (stage 1
    classifies pages at the same time) need the function, so each request gets its own answer.

    A tool loop's call (`complete_turn`) takes the same answers: `{"tool_calls": [{"name", "args"}]}` asks for
    tools, `{"answer": {...}}` is the final answer. A function gets a `FakeTurn`, the request with its turns so far."""

    name = "fake"

    def __init__(self, answers: list[Answer] | Callable[[LLMRequest[Any]], Answer]):
        self._answer = answers if callable(answers) else None
        self._answers = [] if callable(answers) else list(answers)
        self.calls: list[tuple[str, str, str | None]] = []
        self.requests: list[LLMRequest[Any]] = []
        self.turns: list[FakeTurn] = []

    def complete_structured(self, request: LLMRequest[Any], model: str, retry_hint: str | None = None) -> RawAnswer:
        self.calls.append((request.stage, model, retry_hint))
        self.requests.append(request)
        if self._answer is not None:
            return RawAnswer(payload=self._answer(request), model=model, input_tokens=0, output_tokens=0)
        payload = self._answers.pop(0) if self._answers else {}
        return RawAnswer(payload=payload, model=model, input_tokens=0, output_tokens=0)

    def complete_turn(
        self,
        request: ToolLoopRequest[Any],
        turns: list[Turn],
        model: str,
        allow_tools: bool = True,
        retry_hint: str | None = None,
    ) -> RawTurn:
        self.calls.append((request.stage, model, retry_hint))
        turn = FakeTurn(request, list(turns), allow_tools, retry_hint)
        self.turns.append(turn)
        if self._answer is not None:
            out = self._answer(turn)  # type: ignore[arg-type]
        else:
            out = self._answers.pop(0) if self._answers else {"answer": {}}
        n = len(self.turns)
        calls = [
            RawToolCall(id=c.get("id", f"call_{n}_{i}"), name=c["name"], args=c.get("args", {}))
            for i, c in enumerate(out.get("tool_calls", []))
        ]
        return RawTurn(tool_calls=calls, payload=out.get("answer"), model=model, input_tokens=0, output_tokens=0)


class FakeTurn:
    """What a fake tool loop's answer function sees: the request, the turns so far, and the call's settings."""

    def __init__(self, request: ToolLoopRequest[Any], turns: list[Turn], allow_tools: bool, hint: str | None):
        self.request = request
        self.turns = turns
        self.allow_tools = allow_tools
        self.retry_hint = hint
        self.stage = request.stage
