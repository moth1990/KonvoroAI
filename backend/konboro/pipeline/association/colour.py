"""04 §5.6 (BUG-057): a lamp's or a button's colour from its symbol's fill, read by code from the page's render.

The factory behind NEVIS-1, NURSERY-1 and MINHAROT-1 writes no colour beside its lamps: it fills the symbol green or
red. That fill is in the drawing, so it is evidence (`graphic`, as drawn poles are, 00 §5.3); no model reads it.

The symbol's box counts as filled when enough of it is solid in one saturated hue: a pixel counts only when its eight
neighbours share its hue, so lines (a black symbol, or one drawn in a coloured CAD layer) count for nothing, and two
hues of about the same size name no colour. A colour written as text always wins (the caller asks only when none was
read).
"""

import colorsys
from collections import Counter

from PIL import Image

from konboro.contracts.common import Bbox

from .config import DEFAULT, AssociationConfig

# hue in degrees → the grammar's colour values (`grammar.COLOURS`)
HUES: tuple[tuple[int, int, str], ...] = (
    (0, 20, "red"),
    (40, 70, "yellow"),
    (80, 170, "green"),
    (190, 260, "blue"),
    (330, 360, "red"),
)
SAMPLE_PX = 64  # the box is scaled to at most this many pixels a side before counting


def _name(hue: float) -> str | None:
    degrees = hue * 360  # colorsys gives [0, 1)
    return next((name for lo, hi, name in HUES if lo <= degrees < hi), None)


def fill(render: Image.Image, bbox: Bbox, px_per_pt: float, cfg: AssociationConfig = DEFAULT) -> str | None:
    """The colour that fills the symbol in `bbox` (PDF points), or None."""
    x0, y0, x1, y1 = (round(v * px_per_pt) for v in bbox)
    if x1 <= x0 or y1 <= y0:
        return None
    crop = render.crop((x0, y0, x1, y1)).convert("RGB")
    crop.thumbnail((SAMPLE_PX, SAMPLE_PX))
    w, h = crop.size
    data = crop.tobytes()  # RGB, row by row
    names: dict[bytes, str | None] = {}
    grid: list[list[str | None]] = []
    for y in range(h):
        row: list[str | None] = []
        for x in range(w):
            rgb = data[3 * (y * w + x) : 3 * (y * w + x) + 3]
            if rgb not in names:
                hh, s, v = colorsys.rgb_to_hsv(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)
                names[rgb] = _name(hh) if s >= cfg.fill_saturation and v >= cfg.fill_value else None
            row.append(names[rgb])
        grid.append(row)
    # a filled area, not a line: the pixel and its eight neighbours are all the one hue
    solid: Counter[str] = Counter()
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            name = grid[y][x]
            if name is not None and all(grid[y + dy][x + dx] == name for dy in (-1, 0, 1) for dx in (-1, 0, 1)):
                solid[name] += 1
    if not solid:
        return None
    (name, n), *_ = solid.most_common(1)
    if n / (w * h) < cfg.fill_min_share or n / sum(solid.values()) < cfg.fill_dominance:
        return None
    return name
