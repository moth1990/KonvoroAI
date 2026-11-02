"""Stage 4's settings (04 §5.2–5.8, §6.4, §8). Defaults are the spec's starting values; tests pass their own.

They live in code, not in the environment: several change what the tile agent is shown, so a change means recording
the eval cassettes again, like a prompt change.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AssociationConfig:
    # 5.2 geometric association
    radius_factor: float = 3.0  # `assoc_radius` = 3 × the symbol's height
    min_height_pt: float = 10.0  # a symbol boxed smaller than this still reaches its label
    align_bonus: float = 1.15  # the text lies above, below or beside the symbol, within its extent
    direction_bonus: float = 1.05  # the text runs the way the symbol does
    context_fit: float = 0.6  # a span that only tells a model, a brand, a multiplicity: weaker than an attribute
    resolved_confidence: float = 0.9  # 5.2 item 4: each must-read attribute's association
    resolved_gap: float = 0.2  # 5.2 item 4: the competing symbol's score is this much lower, or more
    near_competitor: float = 0.8  # association confidence when another symbol is almost as close
    # 5.2 shared labels found by code (S13 decision): one label over a row of symbols with no text of their own
    row_tolerance: float = 0.5  # of the symbol's height: centres this close are one row
    row_gap_factor: float = 2.5  # a row breaks where symbols are further apart than this × their height
    # the neutral pole drawn on its own line (S13 decision)
    neutral_reach: float = 3.0  # × the breaker's height, sideways
    # 5.1.1 multiplicity
    inherited_penalty: float = 0.8
    line_gap_pt: float = 4.0  # words this close on one baseline are one line of text, or 1.5 × their height
    # 5.1.2 supply scope
    scope_reach: float = 3.0  # × the symbol's height: a phrase this close takes the symbol out of the panel
    # 5.4 tile agent
    workers: int = 8  # tiles sent at the same time
    agent_radius_factor: float = 1.5  # a cited span may lie this much further than `assoc_radius`
    # 6.4 confidence
    graphic_max: float = 0.85
    conflict_penalty: float = 0.8
    fallback_max: float = 0.6
    missing_max: float = 0.4
    accepted_from: float = 0.85
    # 8
    high_missing_share: float = 0.10


DEFAULT = AssociationConfig()
