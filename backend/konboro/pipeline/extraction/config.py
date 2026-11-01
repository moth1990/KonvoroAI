"""Stage 2's settings (02 §4.2 "הגדרות חיתוך", §2.1, §2.3, §2.6). Defaults are the spec's; tests pass their own.

They live in code, not in the environment: they change what the OCR engine is shown, so a change means recording
the eval cassettes again, like a prompt change.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractionConfig:
    # 2.1 rendering
    dpi: int = 300
    low_resolution_dpi: int = 400
    target_text_height_px: float = 30.0  # a large vector page is rendered so its text is this tall
    min_dpi: int = 150
    max_render_px: int = 120_000_000  # a page larger than this at its DPI is rendered smaller, and says so
    # 2.3 OCR
    ocr_min_confidence: float = 0.4  # below this a span is logged and dropped
    reread_below: float = 0.8  # an electrical-looking span from `ocr_min_confidence` up to this is read again
    reread_dpi: int = 600
    ocr_workers: int = 8  # tiles read at the same time
    # 2.6 tiling
    tile_size_px: int = 1024
    overlap_px: int = 256
    # The share of white pixels above which a tile is blank. 02 §2.6 says 98%, but a line drawing is that white:
    # on 6199-2-50 tiles holding symbols and text have 0.2–2% ink. A tile is blank at under 0.1% (S10).
    blank_threshold: float = 0.999
    # 02 §8
    vector_too_complex: int = 500_000  # paths
    low_confidence_share: float = 0.2  # `ocr_low_confidence` when more spans than this are below 0.6
    # 12 §6: the viewer's pyramid
    dzi_tile_px: int = 510
    dzi_overlap_px: int = 1


DEFAULT = ExtractionConfig()
