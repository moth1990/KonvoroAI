"""Anthropic implementation, using the official Python SDK (pip install anthropic).

Structured output is done by forcing a single tool whose input_schema is the stage's
pydantic schema. The model must "call" that tool, so the answer is always a JSON object.
"""

from __future__ import annotations

import base64
from typing import Any

import anthropic

from ..base import RawAnswer
from ..types import ImageInput, LLMError, LLMRequest

TOOL_NAME = "submit_result"


class AnthropicProvider:
    """Claude through the Anthropic API, or through Amazon Bedrock (see for_bedrock).

    Stage routes in config.py use platform-neutral model names ("claude-sonnet-5-5").
    model_prefix turns them into the platform's model ID ("anthropic.claude-sonnet-5-5" on Bedrock).
    """

    name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        max_retries: int = 3,
        timeout_s: float = 120,
        client: Any = None,
        model_prefix: str = "",
    ):
        # The SDK already retries on 429/5xx with backoff; max_retries controls that.
        # Typed as Any: requests are built as plain dicts, and tests pass a stand-in client.
        self._client: Any = client or anthropic.Anthropic(api_key=api_key, max_retries=max_retries, timeout=timeout_s)
        self._model_prefix = model_prefix

    @classmethod
    def for_bedrock(cls, aws_region: str, max_retries: int = 3, timeout_s: float = 120) -> AnthropicProvider:
        """Claude on Amazon Bedrock. Credentials come from the standard AWS chain (IAM role on ECS)."""
        client = anthropic.AnthropicBedrockMantle(aws_region=aws_region, max_retries=max_retries, timeout=timeout_s)
        return cls(client=client, model_prefix="anthropic.")

    def model_id(self, model: str) -> str:
        return model if model.startswith(self._model_prefix) else f"{self._model_prefix}{model}"

    def complete_structured(self, request: LLMRequest[Any], model: str, retry_hint: str | None = None) -> RawAnswer:
        tool = {
            "name": TOOL_NAME,
            "description": "Return the extraction result. Always call this tool exactly once.",
            "input_schema": request.output_schema.model_json_schema(),
        }

        try:
            response = self._client.messages.create(
                model=self.model_id(model),
                max_tokens=request.max_tokens,
                system=request.system,
                messages=self._build_messages(request, retry_hint),
                tools=[tool],
                tool_choice={"type": "tool", "name": TOOL_NAME},
            )
        except anthropic.APIError as exc:
            raise LLMError(f"anthropic call failed: {exc}") from exc

        tool_block = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_block is None:
            raise LLMError("model did not return a tool_use block")

        return RawAnswer(
            payload=tool_block.input,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    # ------------------------------------------------------------------ helpers

    def _build_messages(self, request: LLMRequest[Any], retry_hint: str | None) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = []

        # Few-shot examples from the learning loop go first.
        for i, ex in enumerate(request.examples, start=1):
            content.append({"type": "text", "text": f"Example {i}:"})
            if ex.image is not None:
                content.append(self._image_block(ex.image))
            content.append({"type": "text", "text": f"{ex.text}\nCorrect result:\n{ex.expected_json}"})

        for img in request.images:
            content.append(self._image_block(img))

        text = request.user_text
        if retry_hint:
            text += f"\n\nYour previous answer did not match the schema: {retry_hint}\nFix it."
        content.append({"type": "text", "text": text})

        return [{"role": "user", "content": content}]

    @staticmethod
    def _image_block(img: ImageInput) -> dict[str, Any]:
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img.media_type,
                "data": base64.standard_b64encode(img.data).decode("ascii"),
            },
        }
