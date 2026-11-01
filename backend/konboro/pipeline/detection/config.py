"""Stage 3's settings (03 §3.2–3.7, §6.3, §8). Defaults are the spec's; tests pass their own.

They live in code, not in the environment: several change what the model is shown, so a change means recording
the eval cassettes again, like a prompt change.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DetectionConfig:
    # 3.2, interim (S12): the model rates each symbol sure or unsure; these are the scores that stand for it
    sure_score: float = 0.9
    unsure_score: float = 0.7  # × a confirming disambiguation (0.7–0.9) stays yellow, not red (03 §6.3)
    workers: int = 8  # tiles searched at the same time
    # 3.4
    llm_budget_share: float = 0.25  # `llm_budget_exceeded`: no more disambiguation calls past this share of a page
    max_candidates: int = 5
    disambiguation_margin: float = 0.5  # around the symbol, of its size
    # 3.5
    dedup_iou: float = 0.5
    dedup_overlap: float = 0.7  # or this much of the smaller box: one sighting boxed tighter than another
    dedup_touch_pt: float = 3.0  # or the same tag, along the same wire, this close: one symbol boxed in two parts
    # 3.6
    orphan_radius_pt: float = 40.0
    orphan_crop_pad_pt: float = 90.0  # around a group of orphan texts, in the re-detection crop
    max_orphan_searches: int = 12  # per page; the rest go to stage 4 as orphan texts
    # 3.7
    designator_radius: float = 2.0  # symbol heights (03 §3.7 item 1)
    designator_min_radius_pt: float = 14.0  # a breaker is ~10 pt tall; its tag sits beside it
    no_tag_share: float = 0.5  # a drawing where at least this share of devices have a tag flags the rest
    # crops (03 §6.2 `crop_uri`)
    crop_margin: float = 0.15
    # 6.3 status bands (00 §6.3)
    accepted_from: float = 0.85
    uncertain_from: float = 0.5
    # 8
    high_unknown_share: float = 0.15
    many_orphans_share: float = 0.10


DEFAULT = DetectionConfig()

# Tags of stage 2 that mean a device sits nearby (03 §3.6 "C16", "30mA"). Cable cores, cable type, voltage and power
# are written on cables and loads.
DEVICE_TAGS = ("current_a", "curve", "residual_ma", "breaking_capacity_ka", "poles", "setting_a")
