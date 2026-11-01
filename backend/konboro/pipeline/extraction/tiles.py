"""2.6 tiling (02 §2.6): a grid of square tiles with overlap over the whole page, for stage 3, and for OCR.

The whole page, not the union of the panels stage 1 found (BUG-019): those boxes come from a 1024 px overview and
miss parts of the drawing. On 26-993 page 3 they held the two feed boards only, and the lower half of the sheet,
with seven components, was never read. Empty paper costs nothing: blank tiles are skipped.

Tiles start at the area's top left, one stride (`tile − overlap`) apart, and cover it to its far edges. Only past the
page's edge is a tile padded white, and `padding_px` says how much, so stage 3 can drop a detection there.

**Coverage (02 §2.6, §10):** any box no larger than the overlap that lies inside the area lies whole inside one tile.
A box starting at `a` falls in the tile `k = ⌊(a − x0) / stride⌋`, which runs to `x0 + k·stride + tile`, past
`a + overlap`. `tests/unit/test_extraction.py` checks it.
"""

import math
from dataclasses import dataclass

from PIL import Image

from konboro.contracts.common import Bbox

WHITE = 245  # a grey level at or above this counts as white paper


@dataclass(frozen=True)
class TileGeom:
    row: int
    col: int
    bbox_px: tuple[int, int, int, int]  # the whole square, in render pixels; may run past the page
    padding_px: tuple[int, int, int, int]  # top, right, bottom, left: the part past the page

    def bbox_pt(self, px_per_pt: float) -> Bbox:
        return tuple(round(v / px_per_pt, 2) for v in self.bbox_px)  # type: ignore[return-value]


def _starts(lo: int, hi: int, tile: int, stride: int) -> list[int]:
    n = 1 if hi - lo <= tile else math.ceil((hi - lo - tile) / stride) + 1
    return [lo + k * stride for k in range(n)]


def grid(area_px: tuple[int, int, int, int], image_px: tuple[int, int], tile: int, overlap: int) -> list[TileGeom]:
    if overlap >= tile:
        raise ValueError("the overlap must be smaller than the tile")
    stride = tile - overlap
    x0, y0, x1, y1 = area_px
    w, h = image_px
    out: list[TileGeom] = []
    for row, top in enumerate(_starts(y0, y1, tile, stride)):
        for col, left in enumerate(_starts(x0, x1, tile, stride)):
            box = (left, top, left + tile, top + tile)
            pad = (max(0, -top), max(0, box[2] - w), max(0, box[3] - h), max(0, -left))
            out.append(TileGeom(row, col, box, pad))
    return out


def cut(image: Image.Image, t: TileGeom) -> Image.Image:
    """The tile's pixels, white where it runs past the page."""
    out = Image.new("RGB", (t.bbox_px[2] - t.bbox_px[0], t.bbox_px[3] - t.bbox_px[1]), "white")
    x0, y0 = max(0, t.bbox_px[0]), max(0, t.bbox_px[1])
    x1, y1 = min(image.width, t.bbox_px[2]), min(image.height, t.bbox_px[3])
    if x1 > x0 and y1 > y0:
        out.paste(image.crop((x0, y0, x1, y1)), (x0 - t.bbox_px[0], y0 - t.bbox_px[1]))
    return out


def white_share(image: Image.Image) -> float:
    hist = image.convert("L").histogram()
    return sum(hist[WHITE:]) / max(1, sum(hist))
