"""The code checks of stage 1 (01 §5.2–5.3): where geometry and text come from, and whether a picture is readable.

Thresholds are 01's starting values, to be calibrated on the golden set (01 §12 item 5).
"""

import unicodedata
from dataclasses import dataclass
from typing import Literal

from PIL import Image, ImageFilter, ImageStat

from .pages import PageRead

GeometrySource = Literal["vector", "raster", "mixed"]
TextSource = Literal["pdf_text", "ocr", "mixed"]
Quality = Literal["ok", "low_resolution", "blurry", "cropped"]

RASTER_COVERAGE = 0.9  # raster_coverage_threshold
GARBAGE_RATIO = 0.3  # garbage_ratio_threshold
TEXT_COVERAGE = 0.5  # text_coverage_threshold
MIN_VECTOR_OPS = 50  # fewer drawing operations than this is "a few" (01 §5.2)
MIXED_IMAGE_COVER = 0.25  # an image this large next to real vector work makes the page mixed

# Quality on a 1024 px grey render (01 §5.3). Calibrated on BOM-HW-1, a sharp phone photo (~2,270), and on blurred
# copies of it: 554 at a Gaussian radius of 1 px, 183 at 1.5 px, where the handwriting stops being readable.
QUALITY_PX = 1024
BLUR_VARIANCE = 250.0
MIN_LONG_SIDE_PX = 1000  # a photo smaller than this cannot be read reliably
EDGE_BAND = 0.01
EDGE_INK = 0.35  # the share of dark pixels in an edge band that says the drawing runs off the picture


def geometry_source(page: PageRead) -> GeometrySource:
    if page.image_cover > RASTER_COVERAGE and page.vector_ops < MIN_VECTOR_OPS:
        return "raster"
    if page.image_cover >= MIXED_IMAGE_COVER and page.vector_ops >= MIN_VECTOR_OPS:
        return "mixed"
    return "vector"


def garbage_ratio(text: str) -> float:
    """The share of characters that can't be drawing text: control characters, private-use glyphs of an unmapped
    font, replacement characters. Letters (Hebrew, Latin), digits, punctuation and symbols are fine."""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    bad = sum(1 for c in chars if c == "�" or unicodedata.category(c) in ("Cc", "Co", "Cn", "Cs"))
    return bad / len(chars)


def text_coverage(page: PageRead) -> float:
    """How much of what looks like lettering is real text. A CAD export that drew its letters as lines has
    thousands of glyph-sized paths and almost no characters (26-993: 11 characters, 2,493 such paths)."""
    if page.chars == 0:
        return 0.0
    return page.chars / (page.chars + page.glyph_paths)


def text_source(page: PageRead) -> TextSource:
    if page.fmt != "pdf" or page.chars == 0 or garbage_ratio(page.text) > GARBAGE_RATIO:
        return "ocr"
    coverage = text_coverage(page)
    if coverage >= TEXT_COVERAGE:
        return "pdf_text"
    return "mixed" if coverage >= TEXT_COVERAGE / 5 else "ocr"


def text_rotation(page: PageRead) -> int:
    """For a page with a real text layer: the turn that makes its text read left to right (01 §5.3)."""
    if text_source(page) != "pdf_text" or page.char_angle is None:
        return 0
    return (360 - page.char_angle) % 360


@dataclass(frozen=True)
class QualityResult:
    quality: Quality
    sharpness: float | None = None


def sharpness(image: Image.Image) -> float:
    """The variance of the Laplacian: low on a blurred picture."""
    grey = image.convert("L")
    grey.thumbnail((QUALITY_PX, QUALITY_PX))
    edges = grey.filter(ImageFilter.Kernel((3, 3), (0, 1, 0, 1, -4, 1, 0, 1, 0), scale=1, offset=128))
    return float(ImageStat.Stat(edges).var[0])


def _edge_ink(image: Image.Image) -> float:
    grey = image.convert("L")
    grey.thumbnail((QUALITY_PX, QUALITY_PX))
    w, h = grey.size
    band = max(1, round(min(w, h) * EDGE_BAND))
    boxes = [(0, 0, w, band), (0, h - band, w, h), (0, 0, band, h), (w - band, 0, w, h)]
    worst = 0.0
    for box in boxes:
        part = grey.crop(box)
        values = part.histogram()
        dark = sum(values[:96])
        worst = max(worst, dark / max(1, part.width * part.height))
    return worst


def quality(page: PageRead, geometry: GeometrySource, image: Image.Image | None) -> QualityResult:
    """Vector pages are always readable. A picture is checked for blur first: blurry stops the stage for that
    page (fail fast, 01 §5.3); low resolution and cropping are warnings."""
    if geometry == "vector" or image is None:
        return QualityResult("ok")
    score = sharpness(image)
    if score < BLUR_VARIANCE:
        return QualityResult("blurry", score)
    if page._image is not None and max(page._image.size) < MIN_LONG_SIDE_PX:
        return QualityResult("low_resolution", score)
    if _edge_ink(image) > EDGE_INK:
        return QualityResult("cropped", score)
    return QualityResult("ok", score)
