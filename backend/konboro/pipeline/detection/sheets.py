"""What the model is shown besides the drawing: the reference sheet (every example, numbered, with its class under it)
and the text that lists the families, classes and known box texts. Both depend only on the library, so a drawing's
tiles all share one sheet, and its cassette key is the library's version."""

import io
from collections.abc import Callable

from PIL import Image, ImageDraw, ImageFont

from .library import Library, ReferenceImage
from .reference import path

CELL = 128
LABEL_PX = 22
COLUMNS = 8

ImageLoader = Callable[[ReferenceImage], Image.Image]


def load_curated(ref: ReferenceImage) -> Image.Image:
    return Image.open(path(ref.image_key)).convert("RGB")


def sheet(refs: list[tuple[str, Image.Image]], columns: int = COLUMNS) -> Image.Image:
    """A grid of examples, each with "n. class" under it."""
    rows = (len(refs) + columns - 1) // columns
    out = Image.new("RGB", (columns * CELL, max(1, rows) * (CELL + LABEL_PX)), "white")
    draw = ImageDraw.Draw(out)
    font = ImageFont.load_default(size=13)
    for i, (label, image) in enumerate(refs):
        x, y = (i % columns) * CELL, (i // columns) * (CELL + LABEL_PX)
        image = image.copy()
        image.thumbnail((CELL - 8, CELL - 8))
        out.paste(image, (x + (CELL - image.width) // 2, y + (CELL - image.height) // 2))
        draw.rectangle((x, y, x + CELL - 1, y + CELL + LABEL_PX - 1), outline=(200, 200, 200))
        draw.text((x + CELL // 2, y + CELL + LABEL_PX // 2), f"{i + 1}. {label}", fill="black", font=font, anchor="mm")
    return out


def reference_sheet(library: Library, load: ImageLoader = load_curated) -> Image.Image:
    refs = [r for r in library.references if r.symbol_class in library.classes]
    return sheet([(r.symbol_class, load(r)) for r in refs])


def png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()


def families_text(library: Library, skip: tuple[str, ...] = ("junction",)) -> str:
    from .library import FAMILIES

    looks = {f.family: f.looks for f in FAMILIES}
    lines = []
    for family, classes in library.families.items():
        if family in skip:
            continue
        names = ", ".join(c.symbol_class for c in classes)
        lines.append(f"- {family}: {looks.get(family, family)} → {names}")
    return "\n".join(lines)


def abbreviations_text(library: Library) -> str:
    """The dictionary as the model reads it: `"text" = class`, the letters-only entries also stand for a numbered
    designator ("C" covers "C1")."""
    by_class: dict[str, list[str]] = {}
    for text, symbol_class in library.abbreviations.items():
        by_class.setdefault(symbol_class, []).append(library.written.get(text, text))
    parts = [f"{' / '.join(sorted(texts))} = {c}" for c, texts in sorted(by_class.items())]
    return "; ".join(parts) + ' (a letters-only entry also covers a numbered tag: "C" covers C1, C12)'
