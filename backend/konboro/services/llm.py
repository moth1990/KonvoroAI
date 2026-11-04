"""The LLM client the pipeline hands each stage (`StageContext.llm`), and its cost log.

- `live_providers`: Claude, when there is a key (the worker passes its setting; otherwise `ANTHROPIC_API_KEY`).
  Without a key there is no provider, and a stage that calls the model fails with a clear "provider not
  registered" (stubs never call it).
- `recorded_model`, `runs_on_stand_in`: the stand-in model's answers are marked where they are stored, so a run on
  the real model never reuses them (BUG-041).
- `eval_providers`: what `make eval` runs on (dev-strategy §6). `replay` reads `eval/cassettes/`; `live` calls
  Claude, and with `record` writes what it got back as cassettes.
- `usage_recorder`: every answered call becomes an `llm_calls` row (00 §7.2), in its own transaction, so a stage
  that fails afterwards still leaves its cost behind.
"""

import os
import threading
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Engine

from konboro.db.ids import new_id
from konboro.db.models import LlmCall
from konboro.db.session import tenant_session
from konboro_llm import LLMClient, LLMError, LLMRequest, LLMResult
from konboro_llm.base import LLMProvider, RawAnswer, RawTurn
from konboro_llm.client import OnCall
from konboro_llm.providers import CassetteProvider, FakeProvider

EvalMode = Literal["replay", "live"]

# Prefix on a stored model name whose answer came from the stand-in (konboro.devtools.fake_llm), e.g.
# "stand-in:claude-haiku-5-5". A page reused from another copies the name, so the mark follows every reuse.
STAND_IN_PREFIX = "stand-in:"


def live_providers(api_key: str | None = None) -> dict[str, LLMProvider]:
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return {}
    from konboro_llm.providers.anthropic_provider import AnthropicProvider

    return {"anthropic": AnthropicProvider(api_key=key)}


def chat_providers(settings: Any) -> dict[str, Any]:
    """The API's model, for the chat (08). Tests always get the stand-in, whatever the .env has; a local API without
    a key gets it too, loudly; anywhere else Claude or nothing."""
    from konboro.devtools.fake_llm import fake_providers

    if settings.env == "test":
        return fake_providers()
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    live = live_providers(key)
    if live or settings.env != "local":
        return live
    import logging

    logging.getLogger("konboro.chat").warning("no ANTHROPIC_API_KEY: the chat answers from the stand-in model")
    return fake_providers()


def is_stand_in(provider_name: str) -> bool:
    return provider_name == FakeProvider.name


def recorded_model(result: LLMResult[Any]) -> str:
    """The model name to store with a result: marked when the stand-in answered."""
    return f"{STAND_IN_PREFIX}{result.model}" if is_stand_in(result.provider) else result.model


def runs_on_stand_in(llm: LLMClient, stage: str) -> bool:
    """Whether `stage` is answered by the stand-in in this run (no key, tests, E2E)."""
    route = llm.routes.get(stage)
    provider = llm.providers.get(route.provider) if route else None
    return provider is not None and is_stand_in(provider.name)


def eval_providers(
    mode: EvalMode, cassettes: Path, *, record: bool | Literal["missing"] = False, max_usd: float | None = None
) -> dict[str, LLMProvider]:
    """`record="missing"` keeps what is recorded and records only new calls (`fill`). `max_usd` stops a live run
    once its calls cost that much at list prices (`SpendingCap`)."""
    if mode == "replay":
        if record:
            raise ValueError("EVAL_RECORD needs EVAL_MODE=live: there is nothing to record from in replay")
        return {"anthropic": CassetteProvider(cassettes, "replay")}
    live = live_providers()
    if not live:
        raise RuntimeError("EVAL_MODE=live needs ANTHROPIC_API_KEY")
    provider: LLMProvider = live["anthropic"]
    if max_usd is not None:
        provider = SpendingCap(provider, max_usd)
    if record:
        return {"anthropic": CassetteProvider(cassettes, "fill" if record == "missing" else "record", wrapped=provider)}
    return {"anthropic": provider}


# List prices per million tokens (input, output), for the live eval's spending cap only; billing is the provider's.
PRICES_USD = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0)}


class SpendingCap:
    """A live provider that refuses calls once the ones before cost `max_usd` (S10: the OCR recording's ceiling).
    The call that crosses the line still finishes; the next one raises."""

    def __init__(self, wrapped: LLMProvider, max_usd: float) -> None:
        self.wrapped = wrapped
        self.name = wrapped.name
        self.max_usd = max_usd
        self.spent_usd = 0.0
        self._lock = threading.Lock()

    def complete_structured(self, request: LLMRequest[Any], model: str, retry_hint: str | None = None) -> RawAnswer:
        with self._lock:
            if self.spent_usd >= self.max_usd:
                raise LLMError(f"spending cap reached: ${self.spent_usd:.2f} of ${self.max_usd:.2f}")
        answer = self.wrapped.complete_structured(request, model, retry_hint)
        price_in, price_out = PRICES_USD.get(model, max(PRICES_USD.values()))
        cost = (answer.input_tokens * price_in + answer.output_tokens * price_out) / 1_000_000
        with self._lock:
            self.spent_usd += cost
        return answer

    def complete_turn(
        self, request: Any, turns: Any, model: str, allow_tools: bool = True, retry_hint: str | None = None
    ) -> RawTurn:
        with self._lock:
            if self.spent_usd >= self.max_usd:
                raise LLMError(f"spending cap reached: ${self.spent_usd:.2f} of ${self.max_usd:.2f}")
        answer: RawTurn = self.wrapped.complete_turn(request, turns, model, allow_tools, retry_hint)  # type: ignore[attr-defined]
        price_in, price_out = PRICES_USD.get(model, max(PRICES_USD.values()))
        cost = (answer.input_tokens * price_in + answer.output_tokens * price_out) / 1_000_000
        with self._lock:
            self.spent_usd += cost
        return answer


def usage_recorder(engine: Engine, tenant_id: str, drawing_id: str | None = None) -> OnCall:
    def record(request: LLMRequest[Any], result: LLMResult[Any]) -> None:
        with tenant_session(tenant_id, engine) as s:
            s.add(
                LlmCall(
                    id=new_id("llm"),
                    tenant_id=tenant_id,
                    stage=request.stage,
                    provider=result.provider,
                    model=result.model,
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                    latency_ms=result.latency_ms,
                    attempts=result.attempts,
                    drawing_id=drawing_id,
                )
            )

    return record
