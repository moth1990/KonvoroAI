"""2.3 OCR (02 §2.3): an `OcrEngine` reads words off images, and the flow here turns them into spans on the page.

The engine is behind an interface because the choice is not made yet: S31 compares Google Vision and Azure on the
golden set. Until then `ClaudeVisionOcr` stands in (S10 decision), through the `ocr_transcription` route.
`FakeOcrEngine` is for tests.

The flow, engine-agnostic, for one page:
1. Every non-blank tile is read. Words get checked in code: inside the tile and not in its padding, over ink (the box
   is shrunk to the ink it holds), and not cut by a tile edge the page continues past; such a word is read whole in
   the neighbouring tile, which the overlap guarantees.
2. Copies of one word from overlapping tiles become one span. Copies that disagree leave the span at most
   `DISAGREE_CONFIDENCE`, so it is read again.
3. Spans below `ocr_min_confidence` are logged and dropped (02 §2.3 step 2).
4. An electrical-looking span below `reread_below` is read again on a crop at 600 DPI; the new reading replaces the
   old one only when its confidence is higher (step 3).
"""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol

from PIL import Image, ImageChops, ImageStat

from konboro.contracts.common import Bbox
from konboro_llm import ImageInput, LLMClient
from konboro_llm.stages import ocr_transcription

from ..intake.pages import png
from .config import ExtractionConfig
from .geometry import overlap_of_smaller
from .normalize import Text, canonical, looks_electrical
from .tiles import TileGeom

log = logging.getLogger("konboro.pipeline.s2")

INK = 160  # a grey level below this is ink
EDGE_PX = 3  # a box this close to a tile edge the page continues past is cut by it
SAME_WORD = 0.5  # copies whose boxes overlap this much (of the smaller) are one word
DISAGREE_CONFIDENCE = 0.6
REREAD_PAD = 0.6  # of the word's height, around it, in the re-read crop
REREAD_MIN_PAD_PT = 3.0
COLOURED = 60  # a pixel whose channels differ this much is coloured ink


@dataclass(frozen=True)
class OcrImage:
    data: bytes  # PNG
    size: tuple[int, int]
    key: str  # what the pixels are (page hash, render settings, where): cassettes key on it


@dataclass
class OcrWord:
    text: str
    box: tuple[float, float, float, float]  # pixels of the image
    rotation: int
    confidence: float


class OcrEngine(Protocol):
    name: str

    def read(self, image: OcrImage) -> list[OcrWord]: ...


class FakeOcrEngine:
    """Answers from a function of the image (tests)."""

    name = "fake"

    def __init__(self, answer: Callable[[OcrImage], list[OcrWord]]) -> None:
        self.answer = answer
        self.seen: list[OcrImage] = []

    def read(self, image: OcrImage) -> list[OcrWord]:
        self.seen.append(image)
        return self.answer(image)


class ClaudeVisionOcr:
    """The interim engine (S10 decision): a vision model through `konboro_llm`. It rates its own reading, so a
    "clear" word gets `CLEAR` and an "unsure" one `UNSURE`; the flow's checks do the rest."""

    name = "claude_vision"
    CLEAR = 0.9
    UNSURE = 0.6

    def __init__(self, llm: LLMClient, tenant_id: str | None = None) -> None:
        self.llm = llm
        self.tenant_id = tenant_id

    def read(self, image: OcrImage) -> list[OcrWord]:
        result = ocr_transcription.transcribe(
            self.llm, ImageInput(image.data, key=image.key), image.size, tenant_id=self.tenant_id
        )
        words: list[OcrWord] = []
        for w in result.data.words:
            if not w.text.strip() or len(w.box) != 4:
                continue
            x0, x1 = sorted((w.box[0], w.box[2]))
            y0, y1 = sorted((w.box[1], w.box[3]))
            conf = self.CLEAR if w.legible == "clear" else self.UNSURE
            words.append(OcrWord(w.text.strip(), (x0, y0, x1, y1), w.rotation, conf))
        return words


@dataclass
class Reading:
    """One word read on one tile, placed on the page."""

    text: str
    bbox: Bbox  # points
    rotation: int
    confidence: float
    cut: bool
    color: str | None


def ink_box(
    image: Image.Image, box: tuple[float, float, float, float]
) -> tuple[tuple[int, int, int, int], str | None] | None:
    """The box shrunk to the ink inside it, and the ink's colour when it is not black; None when it holds no ink."""
    x0, y0 = max(0, int(box[0])), max(0, int(box[1]))
    x1, y1 = min(image.width, int(box[2] + 0.999)), min(image.height, int(box[3] + 0.999))
    if x1 - x0 < 1 or y1 - y0 < 1:
        return None
    region = image.crop((x0, y0, x1, y1))
    mask = region.convert("L").point(lambda v: 255 if v < INK else 0)
    inner = mask.getbbox()
    if inner is None:
        return None
    return (x0 + inner[0], y0 + inner[1], x0 + inner[2], y0 + inner[3]), _colour(region, mask)


def _colour(region: Image.Image, mask: Image.Image) -> str | None:
    rgb = region.convert("RGB")
    r, g, b = rgb.split()
    spread = ImageChops.subtract(
        ImageChops.lighter(ImageChops.lighter(r, g), b), ImageChops.darker(ImageChops.darker(r, g), b)
    )
    coloured = ImageChops.multiply(spread.point(lambda v: 255 if v >= COLOURED else 0), mask)
    ink, hue = mask.histogram()[255], coloured.histogram()[255]
    if not ink or hue < 0.3 * ink:
        return None
    avg = tuple(round(v) for v in ImageStat.Stat(rgb, mask=coloured).mean)
    return "#{:02x}{:02x}{:02x}".format(*avg)


def _check(
    words: list[OcrWord], tile_img: Image.Image, t: TileGeom, image_px: tuple[int, int], px_per_pt: float
) -> list[Reading]:
    top, right, bottom, left = t.padding_px
    size = tile_img.width
    inside = (left, top, size - right, size - bottom)  # the part of the tile on the page
    # an edge the page continues past cuts words; the page's own edge doesn't
    open_edges = (t.bbox_px[0] > 0, t.bbox_px[1] > 0, t.bbox_px[2] < image_px[0], t.bbox_px[3] < image_px[1])
    out: list[Reading] = []
    for w in words:
        box = (max(w.box[0], inside[0]), max(w.box[1], inside[1]), min(w.box[2], inside[2]), min(w.box[3], inside[3]))
        found = ink_box(tile_img, box)
        if found is None:
            log.debug("ocr word %r dropped: no ink in its box", w.text)
            continue
        (x0, y0, x1, y1), color = found
        is_cut = (
            (open_edges[0] and x0 <= EDGE_PX)
            or (open_edges[1] and y0 <= EDGE_PX)
            or (open_edges[2] and x1 >= size - EDGE_PX)
            or (open_edges[3] and y1 >= size - EDGE_PX)
        )
        ox, oy = t.bbox_px[0], t.bbox_px[1]
        page_box = (
            round((x0 + ox) / px_per_pt, 2),
            round((y0 + oy) / px_per_pt, 2),
            round((x1 + ox) / px_per_pt, 2),
            round((y1 + oy) / px_per_pt, 2),
        )
        out.append(Reading(w.text, page_box, w.rotation, w.confidence, is_cut, color))
    return out


def _same(a: str, b: str) -> bool:
    return canonical(a).replace(" ", "").casefold() == canonical(b).replace(" ", "").casefold()


def combine(readings: list[Reading]) -> list[Reading]:
    """Copies of one word from overlapping tiles → one reading. Whole copies win over cut ones; agreeing copies
    keep the best confidence; disagreeing whole copies keep the most confident text at `DISAGREE_CONFIDENCE`."""
    groups: list[list[Reading]] = []
    for r in sorted(readings, key=lambda r: (r.cut, -r.confidence)):
        for g in groups:
            if g[0].rotation == r.rotation and overlap_of_smaller(g[0].bbox, r.bbox) >= SAME_WORD:
                g.append(r)
                break
        else:
            groups.append([r])
    out: list[Reading] = []
    for g in groups:
        whole = [r for r in g if not r.cut] or g
        best = whole[0]
        if any(not _same(r.text, best.text) for r in whole[1:]):
            best = Reading(
                best.text, best.bbox, best.rotation, min(best.confidence, DISAGREE_CONFIDENCE), best.cut, best.color
            )
        out.append(best)
    return out


def read_page(
    engine: OcrEngine,
    image: Image.Image,
    tiles: list[tuple[TileGeom, Image.Image]],
    px_per_pt: float,
    key: str,
    cfg: ExtractionConfig,
) -> list[Reading]:
    """Steps 1–3: the page's tiles (already cut, blank ones left out), read, checked and combined."""

    def one(item: tuple[TileGeom, Image.Image]) -> list[Reading]:
        t, img = item
        found = engine.read(OcrImage(png(img), img.size, f"{key}:tile:{t.bbox_px}"))
        return _check(found, img, t, image.size, px_per_pt)

    with ThreadPoolExecutor(max_workers=cfg.ocr_workers) as pool:
        readings = [r for rs in pool.map(one, tiles) for r in rs]
    combined = combine(readings)
    kept = [r for r in combined if r.confidence >= cfg.ocr_min_confidence]
    for r in combined:
        if r.confidence < cfg.ocr_min_confidence:
            log.info("ocr span %r at %s dropped: confidence %.2f", r.text, r.bbox, r.confidence)
    return kept


CropRender = Callable[[Bbox, int], Image.Image]  # a box in points and a DPI → that part of the page


def reread(
    engine: OcrEngine,
    readings: list[Reading],
    crop: CropRender,
    size_pt: tuple[float, float],
    key: str,
    cfg: ExtractionConfig,
) -> int:
    """Step 4, in place: read again what is unsure and looks electrical. Returns how many readings changed."""
    todo = [r for r in readings if r.confidence < cfg.reread_below and looks_electrical(r.text)]

    def one(r: Reading) -> tuple[Reading, list[OcrWord], Image.Image, Bbox]:
        x0, y0, x1, y1 = r.bbox
        pad = max(REREAD_MIN_PAD_PT, REREAD_PAD * min(x1 - x0, y1 - y0))
        box = (max(0.0, x0 - pad), max(0.0, y0 - pad), min(size_pt[0], x1 + pad), min(size_pt[1], y1 + pad))
        img = crop(box, cfg.reread_dpi)
        rounded = tuple(round(v, 1) for v in box)
        return r, engine.read(OcrImage(png(img), img.size, f"{key}:reread:{cfg.reread_dpi}:{rounded}")), img, box

    changed = 0
    with ThreadPoolExecutor(max_workers=cfg.ocr_workers) as pool:
        for r, words, img, box in pool.map(one, todo):
            scale = img.width / max(1e-6, box[2] - box[0])
            target = (
                (r.bbox[0] - box[0]) * scale,
                (r.bbox[1] - box[1]) * scale,
                (r.bbox[2] - box[0]) * scale,
                (r.bbox[3] - box[1]) * scale,
            )
            near = [w for w in words if overlap_of_smaller(w.box, target) >= SAME_WORD]
            if not near:
                continue
            best = max(near, key=lambda w: w.confidence)
            if best.confidence <= r.confidence:
                continue
            found = ink_box(img, best.box)
            if found is None:
                continue
            (bx0, by0, bx1, by1), _ = found
            r.text, r.confidence, r.rotation = best.text, best.confidence, best.rotation
            r.bbox = (
                round(box[0] + bx0 / scale, 2),
                round(box[1] + by0 / scale, 2),
                round(box[0] + bx1 / scale, 2),
                round(box[1] + by1 / scale, 2),
            )
            changed += 1
    return changed


def as_text(r: Reading) -> Text:
    return Text(raw_text=r.text, bbox=r.bbox, rotation=r.rotation, confidence=r.confidence, source="ocr", color=r.color)
