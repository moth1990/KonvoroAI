"""What a drawing's run cost, in US dollars (01 §4.6 "עלות", 12 §7; S28c).

The providers bill in dollars, so the run step shows dollars, with no exchange rate. Each `llm_calls` row is priced
when it is written (`call_cost`, the list prices below), so a later price change never rewrites what a run cost.
A run's cost is the sum of its drawing's rows in the pipeline's stages (1–8): every attempt, a failed or cancelled
run too. Chat, the chat builder and the review screen's actions are not in it (chat rows carry no stage; the review's
actions are code). The same sum is what the per-factory cost table of S30 reads.

Money is Decimal (00 §6.5); the API sends it as a string.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro_llm.types import Usage

MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class Price:
    """List prices per million tokens. A cache write (5-minute) is 1.25 times the input price."""

    input: Decimal
    output: Decimal
    cache_read: Decimal
    cache_write: Decimal


def _price(input_: str, output: str, cache_read: str) -> Price:
    i = Decimal(input_)
    return Price(i, Decimal(output), Decimal(cache_read), i * Decimal("1.25"))


# The Anthropic API's list prices (claude-api skill, cached 2026-10-06). Bedrock bills its own prices (S29).
PRICES: dict[str, Price] = {
    "claude-haiku-5-5": _price("0.10", "0.50", "0.01"),
    "claude-sonnet-5-5": _price("2.00", "10.00", "0.20"),
    "claude-opus-5-5": _price("4.00", "20.00", "0.20"),
}
# Haiku 5.5 doubles past 100K prompt tokens ($0.50 / $2.50).
LONG_PROMPT = 100_000
LONG_PRICES: dict[str, Price] = {"claude-haiku-5-5": _price("0.50", "2.50", "0.05")}
# A model missing from the table is priced as the dearest one: a run is never shown cheaper than it was.
UNKNOWN = PRICES["claude-opus-5-5"]

# The route keys of konboro_llm/config.py that the breakdown names by what they do, not by model.
ROUTE_LABELS = {"ocr_transcription": "קריאת טקסט"}
FAMILY_LABELS = {"haiku": "Haiku", "sonnet": "Sonnet", "opus": "Opus"}


def price_of(model: str, prompt_tokens: int = 0) -> Price:
    name = model.removeprefix("anthropic.")  # Bedrock's model IDs (konboro_llm AnthropicProvider.for_bedrock)
    if prompt_tokens > LONG_PROMPT and name in LONG_PRICES:
        return LONG_PRICES[name]
    return PRICES.get(name, UNKNOWN)


def call_cost(model: str, usage: Usage) -> Decimal:
    """One call's cost: every attempt's tokens, the cache's at their own price."""
    prompt = usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens
    p = price_of(model, prompt)
    total = (
        usage.input_tokens * p.input
        + usage.output_tokens * p.output
        + usage.cache_read_tokens * p.cache_read
        + usage.cache_write_tokens * p.cache_write
    )
    return (total / MILLION).quantize(Decimal("0.000001"))


def model_label(route: str, model: str) -> str:
    """How the breakdown names a call: what it does for the text reading, else the model's family."""
    if route in ROUTE_LABELS:
        return ROUTE_LABELS[route]
    name = model.removeprefix("anthropic.")
    return next((label for key, label in FAMILY_LABELS.items() if key in name), name)


@dataclass
class StageCost:
    usd: Decimal = Decimal(0)
    calls: int = 0
    models: dict[str, int] = field(default_factory=dict)  # label → calls, in the order first seen


@dataclass
class RunCost:
    usd: Decimal = Decimal(0)
    stages: dict[int, StageCost] = field(default_factory=dict)


def drawing_cost(s: Session, drawing_id: str) -> RunCost:
    """The run's cost so far, per stage, with the models and calls behind each (01 §4.6 "פירוט לפי שלב")."""
    rows = s.execute(
        select(
            m.LlmCall.pipeline_stage,
            m.LlmCall.stage,
            m.LlmCall.model,
            func.count(),
            func.coalesce(func.sum(m.LlmCall.cost_usd), 0),
        )
        .where(m.LlmCall.drawing_id == drawing_id, m.LlmCall.pipeline_stage.is_not(None))
        .group_by(m.LlmCall.pipeline_stage, m.LlmCall.stage, m.LlmCall.model)
        .order_by(m.LlmCall.pipeline_stage, func.min(m.LlmCall.created_at))
    ).all()
    run = RunCost()
    for stage, route, model, calls, usd in rows:
        if stage is None:  # filtered out above; for the type checker
            continue
        cost = run.stages.setdefault(int(stage), StageCost())
        cost.usd += Decimal(usd)
        cost.calls += calls
        label = model_label(route, model)
        cost.models[label] = cost.models.get(label, 0) + calls
        run.usd += Decimal(usd)
    return run


def usd_text(value: Decimal) -> str:
    """Dollars to the cent, for the API ("0.44"); the screen adds the sign."""
    return str(value.quantize(Decimal("0.01")))
