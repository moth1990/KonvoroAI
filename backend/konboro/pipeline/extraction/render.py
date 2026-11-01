"""2.1 rendering (02 §2.1): the DPI for each page, chosen by code, and `px_per_pt = dpi / 72`.

- 300 DPI, or 400 for a page stage 1 found `low_resolution`.
- A vector page: the DPI that makes its typical text `target_text_height_px` tall, never below `min_dpi` and never
  above the default. The cost of a page follows its area (02 §2.1, 6199-2-50).
- A photo: its own resolution. Rendering it larger adds pixels, not detail.
- Any page larger than `max_render_px` at that DPI is rendered smaller, so one A0 sheet can't exhaust the worker.
"""

import logging
import math

from konboro.contracts.intake import Page

from .config import ExtractionConfig

log = logging.getLogger("konboro.pipeline.s2")


def choose_dpi(page: Page, text_height_pt: float | None, cfg: ExtractionConfig, photo_dpi: float | None = None) -> int:
    if photo_dpi is not None:
        dpi = photo_dpi
    elif page.quality == "low_resolution":
        dpi = cfg.low_resolution_dpi
    elif page.geometry_source in ("vector", "mixed") and text_height_pt:
        dpi = min(cfg.dpi, max(cfg.min_dpi, 72.0 * cfg.target_text_height_px / text_height_pt))
    else:
        dpi = cfg.dpi
    w, h = page.size_pt
    largest = math.sqrt(cfg.max_render_px / max(1.0, w * h)) * 72.0
    if dpi > largest:
        log.warning(
            "page %s: %d DPI would be over %d px, rendered at %d", page.page_id, dpi, cfg.max_render_px, largest
        )
        dpi = largest
    return max(1, int(dpi))
