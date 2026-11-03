"""Stage 5's settings (05 §5.6–5.8, §6.3). Defaults are the spec's starting values, to be calibrated on the golden set
(05 §6.3: green lines wrong at most 1% of the time); tests pass their own.

They live in code, not in the environment: some change what the agent is shown, so a change means recording the eval
cassettes again, like a prompt change.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MatchingConfig:
    # 6.3 match confidence by method
    explicit_sku: float = 0.99
    explicit_series: float = 0.97
    memory: float = 0.97
    rules_unique: float = 0.95
    rules_ranked: float = 0.90
    llm_max: float = 0.85
    # 6.3 penalties
    defaulted_penalty: float = 0.9  # per attribute filled from notes or a tenant default (not a system default)
    substitution_penalty: float = 0.9
    inferred_penalty: float = 0.85  # per attribute inferred from the circuit (05 §5.5.1)
    # 05 §5.5.1: an inferred value, a cable-poles conflict or an untyped breaker keeps the line yellow until the
    # estimator approves it: the confidence stays below green
    yellow_max: float = 0.84
    # 5.8 the agent
    agent_candidates: int = 5
    agent_min_confidence: float = 0.6  # below this the answer is `ambiguous`, with the candidates as alternatives
    agent_retries: int = 1  # an answer off the list is sent back once with the error (5.8)
    # 5.9
    alternatives: int = 3
    # 8 `high_unmatched_ratio`
    high_unmatched_ratio: float = 0.10


# 05 §5.5 item 3: system defaults, global, for attributes that almost always have a standard value. A tenant default
# overrides them. The first: an RCD's residual current is 30 mA (the product owner's decision, after BOM-HW-1).
SYSTEM_DEFAULTS: dict[str, dict[str, Any]] = {
    "rcd": {"residual_ma": 30},
    "rcbo": {"residual_ma": 30},
}

DEFAULT = MatchingConfig()
TIE_BREAKS = ("frequency", "price", "ask")  # 05 §13 item 1; `frequency` by default
