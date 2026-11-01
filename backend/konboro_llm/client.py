"""The only entry point the rest of the backend uses.

    result = llm.run(LLMRequest(stage="text_association", ...))
    result.data  # a validated pydantic object

It picks the provider and model for the stage, validates the answer against the schema,
retries once with the validation error, falls back to another model if configured,
and logs tokens and latency per stage and per factory. `on_call` gets every answered call too: the backend writes
it to `llm_calls` (00 §7.2), which konboro_llm doesn't know about.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from .base import LLMProvider
from .config import ROUTES, StageRoute
from .types import LLMError, LLMRequest, LLMResult, T

log = logging.getLogger("konboro.llm")

OnCall = Callable[[LLMRequest[Any], LLMResult[Any]], None]


class LLMClient:
    def __init__(
        self,
        providers: dict[str, LLMProvider],
        routes: dict[str, StageRoute] | None = None,
        on_call: OnCall | None = None,
    ):
        self.providers = providers
        self.routes = routes or ROUTES
        self.on_call = on_call

    def run(self, request: LLMRequest[T]) -> LLMResult[T]:
        route = self.routes.get(request.stage)
        if route is None:
            raise LLMError(f"no route configured for stage '{request.stage}'")
        if request.start_at_fallback:
            if route.fallback is None:
                raise LLMError(f"stage '{request.stage}' has no fallback model")
            route = route.fallback

        last_error: Exception | None = None
        while route is not None:
            try:
                return self._run_route(request, route)
            except LLMError as exc:
                last_error = exc
                log.warning("stage=%s model=%s failed: %s", request.stage, route.model, exc)
                route = route.fallback

        raise LLMError(f"all routes failed for stage '{request.stage}': {last_error}")

    def _run_route(self, request: LLMRequest[T], route: StageRoute) -> LLMResult[T]:
        provider = self.providers.get(route.provider)
        if provider is None:
            raise LLMError(f"provider '{route.provider}' is not registered")

        hint: str | None = None
        for attempt in range(1, route.max_attempts + 1):
            started = time.monotonic()
            raw = provider.complete_structured(request, route.model, retry_hint=hint)
            latency_ms = int((time.monotonic() - started) * 1000)

            try:
                data = request.output_schema.model_validate(raw.payload)
            except ValidationError as exc:
                hint = str(exc)[:1500]
                log.info("stage=%s attempt=%d schema mismatch, retrying", request.stage, attempt)
                continue

            result = LLMResult(
                data=data,
                provider=provider.name,
                model=raw.model,
                usage=raw.usage(),
                latency_ms=latency_ms,
                attempts=attempt,
            )
            self._log_usage(request, result)
            return result

        raise LLMError(f"output did not match schema after {route.max_attempts} attempts: {hint}")

    def _log_usage(self, request: LLMRequest[Any], result: LLMResult[Any]) -> None:
        # A log line for local runs; on_call is the record that cost per factory and per stage comes from.
        log.info(
            "llm_call stage=%s tenant=%s provider=%s model=%s in=%d out=%d ms=%d attempts=%d",
            request.stage,
            request.tenant_id,
            result.provider,
            result.model,
            result.usage.input_tokens,
            result.usage.output_tokens,
            result.latency_ms,
            result.attempts,
        )
        if self.on_call is not None:
            self.on_call(request, result)
