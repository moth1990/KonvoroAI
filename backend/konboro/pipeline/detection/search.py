"""3.2, interim (S12 decision): the model looks for symbols on an image, and code checks every answer (00 §7.2).

The image is a tile (`search_tiles`), or a crop around text with no symbol near it (03 §3.6, `orphans.py`). For each
symbol the model reports, code:
- takes the family and class from the library's closed lists: a class names its family; a family without a valid
  class gets its default class and goes to the disambiguation call; neither known → dropped;
- reads a box with text through the abbreviation dictionary (03 §4.6): a known text sets the class, an unknown one
  goes to the disambiguation call;
- keeps the box inside the image's part of the page (padding is not page), drops it when its centre lies in the
  padding (03 §3.2 `padding_reject`) or it holds no ink, and shrinks it to its ink;
- marks it cut when it touches an edge the page continues past, so a whole copy in the next tile wins (3.5).
"""

import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from PIL import Image

from konboro.contracts.common import Bbox
from konboro_llm import ImageInput, LLMClient
from konboro_llm.stages import symbol_detection
from konboro_llm.stages.symbol_detection import SymbolAnswer

from ..extraction.ocr import EDGE_PX, ink_box
from .candidates import Candidate
from .config import DetectionConfig
from .library import Library
from .sheets import abbreviations_text, families_text, png

log = logging.getLogger("konboro.pipeline.s3")

_TAG = re.compile(r"^[A-Z]{1,4}\d{0,3}(?:[.\-][A-Z]{0,2}\d{1,3})*$")


@dataclass(frozen=True)
class SearchImage:
    """An image to search, and where it lies on the page."""

    image: Image.Image
    origin_px: tuple[int, int]  # its top left in render pixels (may be negative for a padded tile)
    padding_px: tuple[int, int, int, int]  # top, right, bottom, left: the part past the page
    page_px: tuple[int, int]  # the render's size
    key: str  # what the pixels are (cassettes key on it)
    tile_id: str = ""


@dataclass
class Prompt:
    """What every search on one drawing shares: the reference sheet and the lists, built once from the library."""

    library: Library
    sheet: ImageInput
    families: str = field(init=False)
    abbreviations: str = field(init=False)

    def __post_init__(self) -> None:
        self.families = families_text(self.library)
        self.abbreviations = abbreviations_text(self.library)


Ask = Callable[[SearchImage, str], list[SymbolAnswer]]  # an image and a hint → what the model saw


def model_asker(llm: LLMClient, prompt: Prompt, tenant_id: str | None) -> Ask:
    def ask(img: SearchImage, hint: str) -> list[SymbolAnswer]:
        result = symbol_detection.detect(
            llm,
            prompt.sheet,
            ImageInput(png(img.image), key=img.key),
            img.image.size,
            prompt.families,
            prompt.abbreviations,
            tenant_id,
            hint=hint,
        )
        return result.data.symbols

    return ask


def resolve_class(answer: SymbolAnswer, library: Library) -> tuple[str, str, str | None] | None:
    """(family, symbol_class, why it needs a decision) from the answer, the library and the box's text; None to
    drop it."""
    families = library.families
    if answer.box_text and answer.box_text.strip():
        named = library.classify_text(answer.box_text)
        if named is not None:
            return named.family, named.symbol_class, None
        family = answer.family if answer.family in families else None
        guess = library.classes.get(answer.symbol_class)
        if guess is not None:
            family = guess.family
        if family is None:
            return None
        default = guess.symbol_class if guess else families[family][0].symbol_class
        return family, default, "box_text_unknown"
    known = library.classes.get(answer.symbol_class)
    if known is not None:
        return known.family, known.symbol_class, None
    if answer.family in families:
        return answer.family, families[answer.family][0].symbol_class, "class_unknown"
    return None


def check(
    answers: list[SymbolAnswer], img: SearchImage, px_per_pt: float, library: Library, cfg: DetectionConfig
) -> list[Candidate]:
    top, right, bottom, left = img.padding_px
    w, h = img.image.size
    inside = (left, top, w - right, h - bottom)
    ox, oy = img.origin_px
    open_edges = (ox > 0, oy > 0, ox + w < img.page_px[0], oy + h < img.page_px[1])
    out: list[Candidate] = []
    for a in answers:
        if len(a.box) != 4:
            continue
        x0, x1 = sorted((a.box[0], a.box[2]))
        y0, y1 = sorted((a.box[1], a.box[3]))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if not (inside[0] <= cx <= inside[2] and inside[1] <= cy <= inside[3]):
            log.debug("symbol %s dropped: its centre is off the page (padding)", a.symbol_class)
            continue
        box = (max(x0, inside[0]), max(y0, inside[1]), min(x1, inside[2]), min(y1, inside[3]))
        found = ink_box(img.image, box)
        if found is None:
            log.debug("symbol %s dropped: no ink in its box", a.symbol_class)
            continue
        resolved = resolve_class(a, library)
        if resolved is None:
            log.info("symbol %r / %r dropped: not in the library", a.family, a.symbol_class)
            continue
        family, symbol_class, why = resolved
        (bx0, by0, bx1, by1), _ = found
        cut = (
            (open_edges[0] and bx0 <= EDGE_PX)
            or (open_edges[1] and by0 <= EDGE_PX)
            or (open_edges[2] and bx1 >= w - EDGE_PX)
            or (open_edges[3] and by1 >= h - EDGE_PX)
        )
        by_dictionary = bool(a.box_text and a.box_text.strip()) and why is None  # its text says what it is
        score = cfg.sure_score if (a.sure or by_dictionary) and why is None else cfg.unsure_score
        if why is None and score < cfg.sure_score:
            why = "unsure"
        tag = a.tag.strip() if a.tag and a.tag.strip() else None
        if tag is None and a.box_text and _TAG.match(a.box_text.strip().upper()):
            tag = a.box_text.strip()  # a coil box labelled with its own tag: R1, NVR
        page_box: Bbox = (
            round((bx0 + ox) / px_per_pt, 2),
            round((by0 + oy) / px_per_pt, 2),
            round((bx1 + ox) / px_per_pt, 2),
            round((by1 + oy) / px_per_pt, 2),
        )
        out.append(
            Candidate(
                bbox=page_box,
                family=family,
                symbol_class=symbol_class,
                role=a.role,
                detector_score=score,
                class_score=1.0 if by_dictionary else score,
                tag=tag,
                box_text=a.box_text.strip() if a.box_text else None,
                orientation=a.orientation,
                tile_id=img.tile_id,
                cut=cut,
                needs_decision=why,
                candidates=[(symbol_class, score)],
            )
        )
    return out


# (image, hint) pairs and the page's scale → what was found on each image, checked
Searcher = Callable[[list[tuple[SearchImage, str]], float], list[list[Candidate]]]


def searcher(ask: Ask, library: Library, cfg: DetectionConfig) -> Searcher:
    """Searches images in parallel (`cfg.workers` at a time), each answer checked."""

    def run(jobs: list[tuple[SearchImage, str]], px_per_pt: float) -> list[list[Candidate]]:
        def one(job: tuple[SearchImage, str]) -> list[Candidate]:
            img, hint = job
            return check(ask(img, hint), img, px_per_pt, library, cfg)

        with ThreadPoolExecutor(max_workers=cfg.workers) as pool:
            return list(pool.map(one, jobs))

    return run
