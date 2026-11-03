"""05 §5.8: the agent that chooses between candidates no rule could tell apart, and the code that checks it.

What it is shown is built here, so it is one place to check that no price, cost or customer detail goes out (05 §12):
the component as read, the candidates' sku, brand, series, description and attributes, the notes about its family and
the factory's preferences in short. The answer's sku must be one of the candidates; an answer off the list is sent
back once with the error, then dropped (`ambiguous`). Its confidence is capped (0.85, 05 §6.3).
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from konboro.contracts.merge import Component
from konboro_llm.stages.catalog_disambiguation import CatalogAnswer

from .catalog import Item
from .config import DEFAULT, MatchingConfig
from .query import Need

# (component, candidates, context, error of the previous answer) → the answer
Ask = Callable[[str, str, str, str | None], CatalogAnswer]


@dataclass
class AgentDecision:
    item: Item | None
    confidence: float
    reason: str
    missing: list[str] = field(default_factory=list)
    answer: dict[str, Any] | None = None  # `llm_decision` (05 §6.2)
    calls: int = 0


def component_text(component: Component, needs: list[Need]) -> str:
    lines = [f"family: {component.family}, class: {component.symbol_class}"]
    for n in needs:
        lines.append(f"- {n.name} = {n.value} ({n.source})")
    if component.explicit_texts:
        lines.append("written beside it in the drawing: " + " | ".join(component.explicit_texts))
    if component.brand_hint:
        lines.append(f"brand written beside it: {component.brand_hint}")
    return "\n".join(lines)


def candidates_text(items: list[Item]) -> str:
    return "\n".join(
        f"{n}. sku: {i.sku} | brand: {i.brand} | series: {i.series or '-'} | {i.description} | "
        + json.dumps(i.attributes, ensure_ascii=False, sort_keys=True)
        for n, i in enumerate(items, start=1)
    )


def context_text(notes: list[str], preferences: list[str]) -> str:
    parts = []
    if notes:
        parts.append("Notes in the drawing about this family:\n" + "\n".join(f"- {n}" for n in notes))
    if preferences:
        parts.append("The factory's preferences:\n" + "\n".join(f"- {p}" for p in preferences))
    return ("\n\n".join(parts) + "\n") if parts else ""


def decide(
    ask: Ask,
    component: Component,
    needs: list[Need],
    candidates: list[Item],
    notes: list[str],
    preferences: list[str],
    cfg: MatchingConfig = DEFAULT,
) -> AgentDecision:
    shown = candidates[: cfg.agent_candidates]
    by_sku = {i.sku: i for i in shown}
    who, what, where = component_text(component, needs), candidates_text(shown), context_text(notes, preferences)
    error: str | None = None
    calls = 0
    for _ in range(cfg.agent_retries + 1):
        answer = ask(who, what, where, error)
        calls += 1
        raw = answer.model_dump(mode="json")
        if answer.chosen_sku is None:
            return AgentDecision(None, 0.0, answer.reason, list(answer.missing_attributes), raw, calls)
        item = by_sku.get(answer.chosen_sku)
        if item is not None:
            return AgentDecision(item, min(answer.confidence, cfg.llm_max), answer.reason, [], raw, calls)
        error = f"{answer.chosen_sku!r} is not one of the candidates; choose a listed sku, or null"
    return AgentDecision(None, 0.0, "", [], None, calls)
