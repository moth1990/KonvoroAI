"""The provider contract. Every vendor (Anthropic, OpenAI, Google, a local model) implements this."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel

from .types import LLMRequest, ToolLoopRequest, Turn, Usage


class RawAnswer(BaseModel):
    """What a provider returns before validation against the stage schema."""

    payload: dict[str, Any]
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def usage(self) -> Usage:
        return Usage(self.input_tokens, self.output_tokens, self.cache_read_tokens, self.cache_write_tokens)


class RawToolCall(BaseModel):
    id: str
    name: str
    args: dict[str, Any]


class RawTurn(BaseModel):
    """One model call of a tool loop: either tool calls, or the final answer as JSON (`payload`)."""

    tool_calls: list[RawToolCall] = []
    text: str | None = None  # text the model wrote beside its tool calls; kept in the history
    payload: dict[str, Any] | None = None
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def usage(self) -> Usage:
        return Usage(self.input_tokens, self.output_tokens, self.cache_read_tokens, self.cache_write_tokens)


class LLMProvider(Protocol):
    name: str

    def complete_structured(self, request: LLMRequest[Any], model: str, retry_hint: str | None = None) -> RawAnswer:
        """Send the request and return a JSON object shaped like request.output_schema.

        retry_hint carries the validation error from a previous attempt, so the model can fix it.
        """
        ...


class ToolProvider(Protocol):
    """A provider that can run a tool loop's model calls. Separate from LLMProvider: the pipeline's stages never
    use tools."""

    name: str

    def complete_turn(
        self,
        request: ToolLoopRequest[Any],
        turns: list[Turn],
        model: str,
        allow_tools: bool = True,
        retry_hint: str | None = None,
    ) -> RawTurn:
        """One model call over `turns`. With `allow_tools` off the model must answer (tool_choice none)."""
        ...
