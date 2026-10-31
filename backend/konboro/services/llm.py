"""The LLM client the pipeline hands each stage (`StageContext.llm`), and its cost log.

- `live_providers`: Claude, when `ANTHROPIC_API_KEY` is set. Without a key there is no provider, and a stage that
  calls the model fails with a clear "provider not registered" (stubs never call it).
- `eval_providers`: what `make eval` runs on (dev-strategy §6). `replay` reads `eval/cassettes/`; `live` calls
  Claude, and with `record` writes what it got back as cassettes.
- `usage_recorder`: every answered call becomes an `llm_calls` row (00 §7.2), in its own transaction, so a stage
  that fails afterwards still leaves its cost behind.
"""

import os
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Engine

from konboro.db.ids import new_id
from konboro.db.models import LlmCall
from konboro.db.session import tenant_session
from konboro_llm import LLMRequest, LLMResult
from konboro_llm.base import LLMProvider
from konboro_llm.client import OnCall
from konboro_llm.providers import CassetteProvider

EvalMode = Literal["replay", "live"]


def live_providers() -> dict[str, LLMProvider]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {}
    from konboro_llm.providers.anthropic_provider import AnthropicProvider

    return {"anthropic": AnthropicProvider()}


def eval_providers(mode: EvalMode, cassettes: Path, *, record: bool = False) -> dict[str, LLMProvider]:
    if mode == "replay":
        if record:
            raise ValueError("EVAL_RECORD=1 needs EVAL_MODE=live: there is nothing to record from in replay")
        return {"anthropic": CassetteProvider(cassettes, "replay")}
    live = live_providers()
    if not live:
        raise RuntimeError("EVAL_MODE=live needs ANTHROPIC_API_KEY")
    if record:
        return {"anthropic": CassetteProvider(cassettes, "record", wrapped=live["anthropic"])}
    return live


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
