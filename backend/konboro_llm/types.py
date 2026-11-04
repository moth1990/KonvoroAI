"""Shared types for every LLM call in Konboro.

The rest of the codebase only sees these types. It never imports a vendor SDK.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class ImageInput:
    """An image (a drawing tile, a symbol crop) sent to a vision model."""

    data: bytes
    media_type: str = "image/png"  # image/png | image/jpeg | image/webp
    # What the pixels are, independent of how they were rendered: e.g. the page's content hash plus the render
    # settings. Cassettes key on it when set, so a recording replays on any platform's PDFium build.
    key: str | None = None


@dataclass(frozen=True)
class Example:
    """A few-shot example pulled from past user corrections (the learning loop)."""

    image: ImageInput | None
    text: str
    expected_json: str


@dataclass
class LLMRequest(Generic[T]):
    stage: str  # "text_association", "catalog_disambiguation", ...
    system: str
    user_text: str
    output_schema: type[T]  # pydantic model the answer must match
    images: list[ImageInput] = field(default_factory=list)
    examples: list[Example] = field(default_factory=list)
    tenant_id: str | None = None  # for logging and cost per factory, never sent to the model
    max_tokens: int = 4096
    # How hard the model thinks (low | medium | high | xhigh | max); None leaves the model's default. Transcribing
    # what is written needs little (S10, `ocr_transcription`).
    effort: str | None = None
    # Go straight to the route's fallback model: the stage's own check refused the first model's answers (04 §5.5)
    start_at_fallback: bool = False


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass
class LLMResult(Generic[T]):
    data: T  # already validated against output_schema
    provider: str
    model: str
    usage: Usage
    latency_ms: int
    attempts: int


class LLMError(Exception):
    """Raised when a provider fails or returns output that does not match the schema."""


# ---------------------------------------------------------------------------- tool loop (the chat coordinator, 08)


@dataclass(frozen=True)
class ToolSpec:
    """A tool the model may call. Its arguments are validated against `args_schema` before code runs it."""

    name: str
    description: str
    args_schema: type[BaseModel]


@dataclass(frozen=True)
class ToolCall:
    id: str  # the provider's id for this call, echoed back with its result
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: dict[str, Any]  # JSON for the model; never an amount of money (08 §5.4), the caller's job
    is_error: bool = False


@dataclass(frozen=True)
class Turn:
    """One message of a conversation, provider-neutral. A user turn has text or tool results; an assistant turn has
    text, tool calls, or both."""

    role: str  # "user" | "assistant"
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()


@dataclass
class ToolLoopRequest(Generic[T]):
    stage: str  # "chat_command"
    system: str  # fixed instructions: cached by the provider with the tool definitions (08 §5.2.1)
    turns: list[Turn]  # history, ending with the user's message
    tools: list[ToolSpec]
    output_schema: type[T]  # the final answer
    context: str = ""  # per-turn context after the cached part (the quote brief, the UI context)
    tenant_id: str | None = None
    max_tokens: int = 4096
    max_steps: int = 8  # model calls that may ask for tools; then one more call with tools off


@dataclass
class ToolStep:
    calls: list[ToolCall]
    results: list[ToolResult]


@dataclass
class ToolLoopResult(Generic[T]):
    data: T
    steps: list[ToolStep]
    provider: str
    model: str
    usage: Usage
    latency_ms: int
    calls: int  # model calls this loop made
