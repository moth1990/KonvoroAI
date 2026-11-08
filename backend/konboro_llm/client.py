"""The only entry point the rest of the backend uses.

    result = llm.run(LLMRequest(stage="text_association", ...))
    result.data  # a validated pydantic object

It picks the provider and model for the stage, validates the answer against the schema,
retries once with the validation error, falls back to another model if configured,
and logs tokens and latency per stage and per factory. `on_call` gets every call too, one that never gave a valid
answer with `ok` false and the tokens of all its attempts (S28c): the backend writes it to `llm_calls` (00 §7.2),
which konboro_llm doesn't know about.

    result = llm.run_tools(ToolLoopRequest(stage="chat_command", ...), execute)

is the chat coordinator's loop (08 §4), the one place a model chooses what runs next. The model asks for tools;
the client checks each call's arguments against the tool's schema and hands it to `execute`, which is code. The
loop ends with the model's final answer, validated like any stage's. Every model call of the loop goes to `on_call`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from .base import LLMProvider, RawTurn, ToolProvider
from .config import ROUTES, StageRoute
from .types import (
    LLMAccountError,
    LLMError,
    LLMRequest,
    LLMResult,
    T,
    ToolCall,
    ToolLoopRequest,
    ToolLoopResult,
    ToolResult,
    ToolStep,
    Turn,
    Usage,
)

log = logging.getLogger("konboro.llm")

# The request is an LLMRequest or a ToolLoopRequest (both carry `stage` and `tenant_id`); a tool loop's result has
# no `data` until its last call.
OnCall = Callable[[Any, LLMResult[Any]], None]
# Runs one tool call whose arguments already passed the tool's schema, and returns its JSON result.
Execute = Callable[[ToolCall, BaseModel], dict[str, Any]]
ANSWER_HINT = "Answer now with the final JSON object only."


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
            except LLMAccountError:
                raise  # the fallback is refused too (BUG-061)
            except LLMError as exc:
                last_error = exc
                log.warning("stage=%s model=%s failed: %s", request.stage, route.model, exc)
                route = route.fallback

        raise LLMError(f"all routes failed for stage '{request.stage}': {last_error}")

    def _run_route(self, request: LLMRequest[T], route: StageRoute) -> LLMResult[T]:
        provider = self.providers.get(route.provider)
        if provider is None:
            raise LLMError(f"provider '{route.provider}' is not registered")

        # Every attempt is billed, a schema mismatch or an unusable answer too: the row that is written carries
        # them all, and a route that never answers writes one with `ok` false (01 §4.6, S28c).
        spent = Usage(0, 0)
        hint: str | None = None
        started = time.monotonic()
        model = route.model
        for attempt in range(1, route.max_attempts + 1):
            try:
                raw = provider.complete_structured(request, route.model, retry_hint=hint)
            except LLMError as exc:
                if exc.usage is not None:
                    spent += exc.usage
                self._log_failure(request, provider.name, exc.model or model, spent, started, attempt)
                raise
            spent += raw.usage()
            model = raw.model

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
                usage=spent,
                latency_ms=int((time.monotonic() - started) * 1000),
                attempts=attempt,
            )
            self._log_usage(request, result)
            return result

        self._log_failure(request, provider.name, model, spent, started, route.max_attempts)
        raise LLMError(f"output did not match schema after {route.max_attempts} attempts: {hint}")

    def _log_failure(
        self, request: Any, provider: str, model: str, spent: Usage, started: float, attempts: int
    ) -> None:
        failed: LLMResult[Any] = LLMResult(
            data=None,
            provider=provider,
            model=model,
            usage=spent,
            latency_ms=int((time.monotonic() - started) * 1000),
            attempts=attempts,
            ok=False,
        )
        self._log_usage(request, failed)

    # ------------------------------------------------------------------ tool loop

    def run_tools(self, request: ToolLoopRequest[T], execute: Execute) -> ToolLoopResult[T]:
        route = self.routes.get(request.stage)
        if route is None:
            raise LLMError(f"no route configured for stage '{request.stage}'")
        specs = {t.name: t for t in request.tools}
        turns = list(request.turns)
        steps: list[ToolStep] = []
        used = Usage(0, 0)
        calls = 0
        started = time.monotonic()
        for step in range(request.max_steps + 1):
            allow = step < request.max_steps  # the last call has tools off, so the loop always ends in an answer
            hint: str | None = None
            raw: RawTurn | None = None
            for _attempt in range(route.max_attempts):
                raw, provider = self._turn(request, turns, route, allow, hint)
                calls += 1
                used = Usage(used.input_tokens + raw.input_tokens, used.output_tokens + raw.output_tokens)
                if raw.tool_calls and allow:
                    break
                if raw.payload is None:
                    hint = ANSWER_HINT
                    continue
                try:
                    data = request.output_schema.model_validate(raw.payload)
                except ValidationError as exc:
                    hint = str(exc)[:1500]
                    log.info("stage=%s final answer schema mismatch, retrying", request.stage)
                    continue
                return ToolLoopResult(
                    data=data,
                    steps=steps,
                    provider=provider,
                    model=raw.model,
                    usage=used,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    calls=calls,
                )
            else:
                raise LLMError(
                    f"stage '{request.stage}' gave no valid answer after {route.max_attempts} attempts: {hint}"
                )
            assert raw is not None  # noqa: S101 (the attempt loop ran at least once)
            asked = [ToolCall(id=c.id, name=c.name, args=c.args) for c in raw.tool_calls]
            results = [self._execute(specs, execute, c) for c in asked]
            turns += [
                Turn("assistant", text=raw.text, tool_calls=tuple(asked)),
                Turn("user", tool_results=tuple(results)),
            ]
            steps.append(ToolStep(asked, results))
        raise LLMError(f"stage '{request.stage}' did not answer")  # unreachable: the last step has tools off

    def _turn(
        self, request: ToolLoopRequest[Any], turns: list[Turn], route: StageRoute, allow: bool, hint: str | None
    ) -> tuple[RawTurn, str]:
        """One model call, on the route's model or else its fallbacks. A fallback continues the same loop: the tools
        that already ran are not run again."""
        last: Exception | None = None
        current: StageRoute | None = route
        while current is not None:
            provider = self.providers.get(current.provider)
            if provider is None or not hasattr(provider, "complete_turn"):
                last = LLMError(f"provider '{current.provider}' cannot run tools")
                current = current.fallback
                continue
            tool_provider: ToolProvider = provider  # type: ignore[assignment]
            begun = time.monotonic()
            try:
                raw = tool_provider.complete_turn(request, turns, current.model, allow_tools=allow, retry_hint=hint)
            except LLMError as exc:
                spent = exc.usage or Usage(0, 0)
                self._log_failure(request, tool_provider.name, exc.model or current.model, spent, begun, 1)
                if isinstance(exc, LLMAccountError):
                    raise  # the fallback is refused too (BUG-061)
                last = exc
                log.warning("stage=%s model=%s failed: %s", request.stage, current.model, exc)
                current = current.fallback
                continue
            result: LLMResult[Any] = LLMResult(
                data=None,
                provider=tool_provider.name,
                model=raw.model,
                usage=raw.usage(),
                latency_ms=int((time.monotonic() - begun) * 1000),
                attempts=1,
            )
            self._log_usage(request, result)
            return raw, tool_provider.name
        raise LLMError(f"all routes failed for stage '{request.stage}': {last}")

    @staticmethod
    def _execute(specs: dict[str, Any], execute: Execute, call: ToolCall) -> ToolResult:
        spec = specs.get(call.name)
        if spec is None:
            return ToolResult(call.id, {"error": "unknown_tool", "tool": call.name}, is_error=True)
        try:
            args = spec.args_schema.model_validate(call.args)
        except ValidationError as exc:
            return ToolResult(call.id, {"error": "invalid_arguments", "detail": str(exc)[:1500]}, is_error=True)
        try:
            return ToolResult(call.id, execute(call, args))
        except Exception:  # a failing tool is an answer the model can work with (08 §11 `tool_failed`)
            log.exception("stage tool %s failed", call.name)
            return ToolResult(call.id, {"error": "tool_failed"}, is_error=True)

    def _log_usage(self, request: Any, result: LLMResult[Any]) -> None:
        # A log line for local runs; on_call is the record that cost per factory and per stage comes from.
        log.info(
            "llm_call stage=%s tenant=%s provider=%s model=%s in=%d out=%d cache_r=%d cache_w=%d ms=%d attempts=%d"
            " ok=%s",
            request.stage,
            request.tenant_id,
            result.provider,
            result.model,
            result.usage.input_tokens,
            result.usage.output_tokens,
            result.usage.cache_read_tokens,
            result.usage.cache_write_tokens,
            result.latency_ms,
            result.attempts,
            result.ok,
        )
        if self.on_call is not None:
            self.on_call(request, result)
