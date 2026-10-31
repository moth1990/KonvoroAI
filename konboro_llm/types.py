"""Shared types for every LLM call in Konboro.

The rest of the codebase only sees these types. It never imports a vendor SDK.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class ImageInput:
    """An image (a drawing tile, a symbol crop) sent to a vision model."""

    data: bytes
    media_type: str = "image/png"  # image/png | image/jpeg | image/webp


@dataclass(frozen=True)
class Example:
    """A few-shot example pulled from past user corrections (the learning loop)."""

    image: ImageInput | None
    text: str
    expected_json: str


@dataclass
class LLMRequest(Generic[T]):
    stage: str                      # "text_association", "catalog_disambiguation", ...
    system: str
    user_text: str
    output_schema: type[T]          # pydantic model the answer must match
    images: list[ImageInput] = field(default_factory=list)
    examples: list[Example] = field(default_factory=list)
    tenant_id: str | None = None    # for logging and cost per factory, never sent to the model
    max_tokens: int = 4096


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass
class LLMResult(Generic[T]):
    data: T                         # already validated against output_schema
    provider: str
    model: str
    usage: Usage
    latency_ms: int
    attempts: int


class LLMError(Exception):
    """Raised when a provider fails or returns output that does not match the schema."""
