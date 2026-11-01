"""Reading pages (01 §5.1–5.2): what is on each page, its content hash, and images of it at any size.

PDFs go through PDFium, always behind its lock (konboro.services.pdf, BUG-010). Images are turned upright from
their EXIF tag, and their size in points comes from their DPI (01 §6.4).

The page hash is of the page's content, not of pixels: the drawing operations (each path's points, each text run,
each image's raw data) with numbers rounded to 0.01 pt. Pixels would differ between PDFium builds, and the hash keys
reuse (01 §5.1) and the eval cassettes, which must replay on any platform.
"""

import hashlib
import io
import math
import struct
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field

import pi_heif
from PIL import Image, ImageOps

from konboro.services.pdf import document
from konboro.services.pdf import raw as pdfium_c

pi_heif.register_heif_opener()

DEFAULT_DPI = 72.0  # an image without a DPI: one pixel is one point
GLYPH_PT = 12.0  # a path smaller than this both ways looks like a letter drawn as lines (01 §5.2)
MAX_RENDER_PX = 40_000_000  # a crop never renders larger than this, whatever the page size


@dataclass
class PageRead:
    """What code reads from one page before any model sees it."""

    file_id: str
    fmt: str
    index: int  # 0-based in its file
    size_pt: tuple[float, float]  # after rotation
    rotation: int  # 0, 90, 180 or 270: the PDF's /Rotate, or the photo's EXIF turn
    sha256: str
    dpi: float = DEFAULT_DPI
    text: str = ""
    chars: int = 0
    vector_ops: int = 0
    glyph_paths: int = 0
    image_cover: float = 0.0  # the share of the page under images
    char_angle: int | None = None  # the dominant text direction, when there is text
    extra_rotation: int = 0  # set later, when the classifier finds the page sideways
    _image: Image.Image | None = field(default=None, repr=False)  # photos only: the upright image

    @property
    def page_no(self) -> int:
        return self.index + 1


def _round(v: float) -> int:
    return round(v * 100)


def _path_points(obj: pdfium_c.FPDF_PAGEOBJECT) -> Iterator[tuple[int, int, int]]:
    x, y = pdfium_c.FS_FLOAT(), pdfium_c.FS_FLOAT()
    for i in range(pdfium_c.FPDFPath_CountSegments(obj)):
        seg = pdfium_c.FPDFPath_GetPathSegment(obj, i)
        pdfium_c.FPDFPathSegment_GetPoint(seg, x, y)
        yield pdfium_c.FPDFPathSegment_GetType(seg), _round(x.value), _round(y.value)


def _read_pdf_page(file_id: str, pdf, index: int) -> PageRead:  # type: ignore[no-untyped-def]
    page = pdf[index]
    w, h = page.get_size()
    digest = hashlib.sha256()
    digest.update(struct.pack("<3q", page.get_rotation(), _round(w), _round(h)))
    kinds: Counter[int] = Counter()
    glyphs, image_area = 0, 0.0
    matrix = pdfium_c.FS_MATRIX()
    for obj in page.get_objects(max_depth=4):
        kinds[obj.type] += 1
        raw = obj.raw
        pdfium_c.FPDFPageObj_GetMatrix(raw, matrix)
        m = (matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f)
        digest.update(struct.pack("<7q", obj.type, *(_round(v) for v in m)))
        left, bottom, right, top = obj.get_bounds()
        if obj.type == pdfium_c.FPDF_PAGEOBJ_PATH:
            for point in _path_points(raw):
                digest.update(struct.pack("<3q", *point))
            if right - left < GLYPH_PT and top - bottom < GLYPH_PT:
                glyphs += 1
        elif obj.type == pdfium_c.FPDF_PAGEOBJ_IMAGE:
            image_area += max(0.0, right - left) * max(0.0, top - bottom)
            n = pdfium_c.FPDFImageObj_GetImageDataRaw(raw, None, 0)
            buf = (pdfium_c.c_ubyte * n)()
            pdfium_c.FPDFImageObj_GetImageDataRaw(raw, buf, n)
            digest.update(bytes(buf))
    textpage = page.get_textpage()
    text = textpage.get_text_range()
    digest.update(text.encode())
    angles: Counter[int] = Counter()
    for i in range(min(textpage.count_chars(), 2000)):
        if chr(pdfium_c.FPDFText_GetUnicode(textpage.raw, i)).isspace():
            continue
        angle = pdfium_c.FPDFText_GetCharAngle(textpage.raw, i)  # radians, counter-clockwise; -1 on error
        if angle >= 0:
            angles[(round(math.degrees(angle) / 90) % 4) * 90] += 1
    chars = sum(1 for c in text if not c.isspace())
    paths = kinds[pdfium_c.FPDF_PAGEOBJ_PATH]
    return PageRead(
        file_id=file_id,
        fmt="pdf",
        index=index,
        size_pt=(float(w), float(h)),
        rotation=page.get_rotation(),
        sha256=digest.hexdigest(),
        text=text,
        chars=chars,
        vector_ops=paths + kinds[pdfium_c.FPDF_PAGEOBJ_SHADING],
        glyph_paths=glyphs,
        image_cover=min(1.0, image_area / (w * h)) if w and h else 0.0,
        char_angle=angles.most_common(1)[0][0] if angles else None,
    )


# PIL's EXIF orientation values that turn the picture; the mirrored ones turn it too, and count as that turn.
_EXIF_TURN = {3: 180, 4: 180, 5: 270, 6: 270, 7: 90, 8: 90}


def _read_image(file_id: str, fmt: str, data: bytes) -> PageRead:
    original = Image.open(io.BytesIO(data))
    turn = _EXIF_TURN.get(original.getexif().get(0x0112, 1), 0)
    upright = ImageOps.exif_transpose(original).convert("RGB")
    dpi_info = original.info.get("dpi")
    dpi = float(dpi_info[0]) if dpi_info and dpi_info[0] and float(dpi_info[0]) > 1 else DEFAULT_DPI
    w, h = upright.size
    return PageRead(
        file_id=file_id,
        fmt=fmt,
        index=0,
        size_pt=(w * 72.0 / dpi, h * 72.0 / dpi),
        rotation=turn,
        sha256=hashlib.sha256(data).hexdigest(),  # the file is the page
        dpi=dpi,
        image_cover=1.0,
        _image=upright,
    )


def read_pages(file_id: str, fmt: str, data: bytes) -> list[PageRead]:
    """Every page of one file. Spreadsheets have no picture: stage 1 lists their sheets as `bom_table` pages."""
    if fmt == "pdf":
        with document(data) as pdf:
            return [_read_pdf_page(file_id, pdf, i) for i in range(len(pdf))]
    if fmt in ("png", "jpg", "webp", "heic"):
        return [_read_image(file_id, fmt, data)]
    raise ValueError(f"{fmt} has no pages to read")


Crop = tuple[float, float, float, float]  # x0, y0, x1, y1 as fractions of the page, top-left origin


def render(
    page: PageRead, data: bytes, long_side_px: int, crop: Crop | None = None, max_dpi: float = 300
) -> Image.Image:
    """The page, upright, so its longer side (or the crop's) is `long_side_px`, never sharper than `max_dpi`."""
    x0, y0, x1, y1 = crop or (0.0, 0.0, 1.0, 1.0)
    w, h = page.size_pt
    region_long_pt = max((x1 - x0) * w, (y1 - y0) * h)
    scale = min(long_side_px / region_long_pt, max_dpi / 72.0)
    scale = min(scale, (MAX_RENDER_PX / max(1.0, (x1 - x0) * w * (y1 - y0) * h)) ** 0.5)
    return _render(page, data, scale, crop)


def render_at(page: PageRead, data: bytes, dpi: float, crop: Crop | None = None) -> Image.Image:
    """The page (or the crop), upright, at exactly `dpi` (02 §2.1): stage 2 keeps `px_per_pt = dpi / 72`."""
    return _render(page, data, dpi / 72.0, crop)


def _render(page: PageRead, data: bytes, scale: float, crop: Crop | None) -> Image.Image:
    x0, y0, x1, y1 = crop or (0.0, 0.0, 1.0, 1.0)
    w, h = page.size_pt
    if page._image is not None:
        img = page._image
        iw, ih = img.size
        box = (round(x0 * iw), round(y0 * ih), round(x1 * iw), round(y1 * ih))
        part = img.crop(box) if crop else img
        px = scale * 72.0 / page.dpi
        out = part.resize((max(1, round(part.width * px)), max(1, round(part.height * px))), Image.Resampling.LANCZOS)
    else:
        with document(data) as pdf:
            cut = (x0 * w, (1 - y1) * h, (1 - x1) * w, y0 * h)  # PDFium cuts left, bottom, right, top
            out = pdf[page.index].render(scale=scale, crop=cut).to_pil().copy()
    turn = page.extra_rotation
    return out.rotate(-turn, expand=True) if turn else out


def png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.convert("RGB").save(out, "PNG", optimize=True)
    return out.getvalue()
