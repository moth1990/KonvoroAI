"""The LLM client the pipeline hands each stage (`StageContext.llm`), and its cost log.

- `live_providers`: Claude, when `ANTHROPIC_API_KEY` is set. Without a key there is no provider, and a stage that
  calls the model fails with a clear "provider not registered" (stubs never call it).
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
from konboro_llm import LLMError, LLMRequest, LLMResult
from konboro_llm.base import LLMProvider, RawAnswer
from konboro_llm.client import OnCall
from konboro_llm.providers import CassetteProvider

EvalMode = Literal["replay", "live"]


def live_providers() -> dict[str, LLMProvider]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {}
    from konboro_llm.providers.anthropic_provider import AnthropicProvider

    return {"anthropic": AnthropicProvider()}


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
