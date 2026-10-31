"""The provider contract. Every vendor (Anthropic, OpenAI, Google, a local model) implements this."""
from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from .types import LLMRequest, Usage


class RawAnswer(BaseModel):
    """What a provider returns before validation against the stage schema."""

    payload: dict
    model: str
    input_tokens: int
    output_tokens: int

    def usage(self) -> Usage:
        return Usage(self.input_tokens, self.output_tokens)


class LLMProvider(Protocol):
    name: str

    def complete_structured(self, request: LLMRequest, model: str, retry_hint: str | None = None) -> RawAnswer:
        """Send the request and return a JSON object shaped like request.output_schema.

        retry_hint carries the validation error from a previous attempt, so the model can fix it.
        """
        ...
