"""The drawing viewer's pyramid (12 §6): a Deep Zoom image (DZI) of the page render, which OpenSeadragon loads tile by
tile, so an A0 sheet opens like a map. Written here, in stage 2; S11 serves it.

OpenSeadragon reads `page.dzi` (the XML descriptor) and `page_files/{level}/{col}_{row}.png`. Level `max` is the
render itself, each level below is half the one above, down to a single pixel.

The tiles are stored packed, not one object each: `tiles.bin` holds every tile's PNG back to back, and `index.json`
maps `"{level}/{col}_{row}"` to `[offset, length]`. An A0 sheet has about 500 tiles; one object per tile made stage 2
slow on the local S3 stand-in and costs a PUT each in AWS. S11 serves `page_files/…` with a ranged read of the pack.
"""

import io
import json
import math
from collections.abc import Iterator

from PIL import Image

DZI_NS = "http://schemas.microsoft.com/deepzoom/2008"


def descriptor(width: int, height: int, tile: int, overlap: int) -> bytes:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<Image xmlns="{DZI_NS}" Format="png" Overlap="{overlap}" '
        f'TileSize="{tile}"><Size Width="{width}" Height="{height}"/></Image>\n'
    ).encode()


def max_level(width: int, height: int) -> int:
    return math.ceil(math.log2(max(width, height, 1)))


def tiles(image: Image.Image, tile: int, overlap: int) -> Iterator[tuple[int, int, int, bytes]]:
    """(level, col, row, PNG) for every tile of every level."""
    top = max_level(image.width, image.height)
    level_image = image.convert("RGB")
    for level in range(top, -1, -1):
        w, h = level_image.size
        for row in range(math.ceil(h / tile)):
            for col in range(math.ceil(w / tile)):
                x0, y0 = col * tile - (overlap if col else 0), row * tile - (overlap if row else 0)
                x1, y1 = min(w, (col + 1) * tile + overlap), min(h, (row + 1) * tile + overlap)
                out = io.BytesIO()
                level_image.crop((x0, y0, x1, y1)).save(out, "PNG")
                yield level, col, row, out.getvalue()
        if level:
            level_image = level_image.resize(
                (max(1, math.ceil(w / 2)), max(1, math.ceil(h / 2))), Image.Resampling.LANCZOS
            )


def pack(image: Image.Image, tile: int, overlap: int) -> tuple[bytes, bytes]:
    """`tiles.bin` and `index.json` for the image's pyramid."""
    blob = io.BytesIO()
    index: dict[str, list[int]] = {}
    for level, col, row, body in tiles(image, tile, overlap):
        index[f"{level}/{col}_{row}"] = [blob.tell(), len(body)]
        blob.write(body)
    return blob.getvalue(), json.dumps(index, separators=(",", ":")).encode()
