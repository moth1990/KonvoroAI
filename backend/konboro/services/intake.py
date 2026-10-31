"""Upload checks for stage 1 (01 §4.2–4.3, §8), before anything is stored.

The order is the spec's, cheapest first: size, then format by content (magic bytes, never the extension), then
pages and page area, which PDF gives without rendering. The quota comes before all of these, in the route.
One failing file rejects the whole upload: a partial drawing would leave a panel out of the quote unnoticed
(01 §4.3). A ZIP is unpacked one level deep and every file in it gets the same checks.
"""

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Literal

import pypdfium2 as pdfium

from konboro.contracts.intake import DetectedFormat

MB = 1024 * 1024


@dataclass(frozen=True)
class Limits:
    """System limits are the same for every tenant; `max_pages_per_file` comes from the plan (01 §4.3)."""

    max_pages_per_file: int = 30
    max_file_size_mb: int = 20
    max_files_per_upload: int = 20
    max_zip_uncompressed_mb: int = 200
    max_pages_per_drawing: int = 200
    max_page_area_m2: float = 2.0


ErrorCode = Literal[
    "unsupported_format",
    "cad_not_supported",
    "file_corrupt",
    "password_protected",
    "too_large",
    "too_many_pages",
    "drawing_too_many_pages",
    "page_too_large",
    "too_many_files",
    "zip_too_large",
    "zip_nested",
]

# 01 §8. The last three are not in the spec's table yet; S05 adds them there.
MESSAGES: dict[ErrorCode, str] = {
    "unsupported_format": "סוג הקובץ לא נתמך. אפשר להעלות PDF, תמונה, אקסל או CSV.",
    "cad_not_supported": "קבצי DWG ו-DXF עדיין לא נתמכים. ייצאו PDF מתוכנת השרטוט (Plot ל-PDF) והעלו אותו.",
    "file_corrupt": "הקובץ פגום ולא ניתן לפתוח אותו.",
    "password_protected": "הקובץ מוגן בסיסמה. העלו גרסה ללא הגנה.",
    "too_large": "הקובץ {name} גדול מ-{max}MB. אפשר לייצא אותו מחדש בלי תמונות ברזולוציה גבוהה, או לפצל אותו.",
    "too_many_pages": (
        "בקובץ {name} יש {n} עמודים, והמקסימום בחבילה שלכם הוא {max}. אפשר להעלות רק את עמודי הלוחות, או לפצל את הקובץ."
    ),
    "drawing_too_many_pages": "בשרטוט יש יותר מ-{max} עמודים. העלו רק את עמודי הלוחות.",
    "page_too_large": "עמוד {page} בקובץ {name} גדול מהמקסימום. ייצאו אותו מחדש מחולק לכמה גיליונות.",
    "too_many_files": "אפשר להעלות עד {max} קבצים בבת אחת.",
    "zip_too_large": "הקובץ {name} נפתח ליותר מ-{max}MB. העלו את הקבצים שבתוכו בנפרד.",
    "zip_nested": "בקובץ {name} יש קובץ ZIP בתוך ZIP. פתחו אותו והעלו את הקבצים עצמם.",
}


def message(code: ErrorCode, **values: object) -> str:
    return MESSAGES[code].format(**values)


Format = DetectedFormat | Literal["dwg", "dxf"]

_HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}
_DXF = re.compile(rb"^\s*0\s*\r?\n\s*SECTION", re.IGNORECASE)


def detect_format(data: bytes) -> Format | None:
    """By content only (01 §4.2). None when it is none of the formats we know."""
    head = data[:1024]
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[4:8] == b"ftyp" and data[8:12] in _HEIC_BRANDS:
        return "heic"
    if data.startswith(b"PK\x03\x04"):
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            return "zip"  # opening it later reports file_corrupt
        if "[Content_Types].xml" in names and any(n.startswith("xl/") for n in names):
            return "xlsx"
        return "zip"
    if b"%PDF-" in head:  # after ZIP: an archive that stores a PDF uncompressed has this in its first kilobyte
        return "pdf"
    if data.startswith(b"AC10"):
        return "dwg"
    if data.startswith(b"AutoCAD Binary DXF") or _DXF.match(head):
        return "dxf"
    if _looks_like_csv(head):
        return "csv"
    return None


def _looks_like_csv(head: bytes) -> bool:
    """Text (UTF-8, or the cp1255 of Hebrew Excel exports), no NUL bytes, and a delimiter in the first line."""
    if not head or b"\x00" in head:
        return False
    for encoding in ("utf-8-sig", "cp1255"):
        try:
            first_line = head.decode(encoding).splitlines()[0]
        except (UnicodeDecodeError, IndexError):
            continue
        return any(d in first_line for d in ",;\t")
    return False


@dataclass(frozen=True)
class PageCount:
    pages: int
    sizes_pt: list[tuple[float, float]] = field(default_factory=list)  # PDFs only


class PasswordProtectedError(Exception):
    pass


class CorruptFileError(Exception):
    pass


def count_pages(fmt: DetectedFormat, data: bytes) -> PageCount:
    """Without rendering (01 §4.3, check 4). An image is one page; a workbook has one page per worksheet."""
    if fmt == "pdf":
        try:
            pdf = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as e:
            if "password" in str(e).lower():
                raise PasswordProtectedError from e
            raise CorruptFileError from e
        try:
            sizes = [pdf[i].get_size() for i in range(len(pdf))]
            return PageCount(len(pdf), [(float(w), float(h)) for w, h in sizes])
        finally:
            pdf.close()
    if fmt == "xlsx":
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile as e:
            raise CorruptFileError from e
        return PageCount(sum(1 for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)))
    return PageCount(1)


def page_area_m2(size_pt: tuple[float, float]) -> float:
    w, h = size_pt
    return (w / 72 * 0.0254) * (h / 72 * 0.0254)


@dataclass
class CheckedFile:
    """One file of the upload, after the checks. `error` set means the whole upload is rejected."""

    name: str
    data: bytes = field(repr=False)
    size_bytes: int
    detected_format: DetectedFormat | None = None
    page_count: int | None = None
    page_sizes_pt: list[tuple[float, float]] = field(default_factory=list, repr=False)
    error: ErrorCode | None = None
    message: str | None = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def reject(self, code: ErrorCode, **values: object) -> "CheckedFile":
        self.error, self.message = code, message(code, name=self.name, **values)
        return self


def check_file(name: str, data: bytes, limits: Limits) -> CheckedFile:
    """One file, outside a ZIP. The first failing check wins."""
    f = CheckedFile(name=name, data=data, size_bytes=len(data))
    if f.size_bytes > limits.max_file_size_mb * MB:
        return f.reject("too_large", max=limits.max_file_size_mb)
    fmt = detect_format(data)
    if fmt == "dwg" or fmt == "dxf":  # `==`, so mypy narrows the type below
        return f.reject("cad_not_supported")
    if fmt is None:
        return f.reject("unsupported_format")
    f.detected_format = fmt
    if fmt == "zip":
        return f  # unpacked by check_upload
    try:
        counted = count_pages(fmt, data)
    except PasswordProtectedError:
        return f.reject("password_protected")
    except CorruptFileError:
        return f.reject("file_corrupt")
    f.page_count, f.page_sizes_pt = counted.pages, counted.sizes_pt
    if counted.pages == 0:
        return f.reject("file_corrupt")
    if counted.pages > limits.max_pages_per_file:
        return f.reject("too_many_pages", n=counted.pages, max=limits.max_pages_per_file)
    for page_no, size in enumerate(counted.sizes_pt, start=1):
        if page_area_m2(size) > limits.max_page_area_m2:
            return f.reject("page_too_large", page=page_no)
    return f


def _unzip(archive: CheckedFile, limits: Limits) -> list[CheckedFile]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(archive.data))
        infos = [i for i in zf.infolist() if not i.is_dir() and not i.filename.startswith("__MACOSX/")]
    except zipfile.BadZipFile:
        return [archive.reject("file_corrupt")]
    if sum(i.file_size for i in infos) > limits.max_zip_uncompressed_mb * MB:
        return [archive.reject("zip_too_large", max=limits.max_zip_uncompressed_mb)]
    inner = []
    for info in infos:
        name = f"{archive.name}/{info.filename}"
        if info.file_size > limits.max_file_size_mb * MB:  # before reading it: the size is in the directory
            inner.append(CheckedFile(name, b"", info.file_size).reject("too_large", max=limits.max_file_size_mb))
            continue
        try:
            data = zf.read(info)
        except (zipfile.BadZipFile, RuntimeError):  # RuntimeError: an encrypted entry
            inner.append(CheckedFile(name, b"", info.file_size).reject("file_corrupt"))
            continue
        checked = check_file(name, data, limits)
        if checked.detected_format == "zip":
            checked.reject("zip_nested")
        inner.append(checked)
    return inner or [archive.reject("file_corrupt")]


@dataclass
class UploadCheck:
    files: list[CheckedFile]
    error: ErrorCode | None = None  # an upload-wide problem: too many files, too many pages in all
    message: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and all(f.error is None for f in self.files)

    @property
    def total_pages(self) -> int:
        return sum(f.page_count or 0 for f in self.files)


def check_upload(files: list[tuple[str, bytes]], limits: Limits) -> UploadCheck:
    """Every file is checked, so the user sees every problem at once, not one per try."""
    if not files:
        return UploadCheck([], "unsupported_format", message("unsupported_format"))
    if len(files) > limits.max_files_per_upload:
        return UploadCheck([], "too_many_files", message("too_many_files", max=limits.max_files_per_upload))
    checked: list[CheckedFile] = []
    for name, data in files:
        f = check_file(name, data, limits)
        checked.extend(_unzip(f, limits) if f.detected_format == "zip" and f.error is None else [f])
    result = UploadCheck(checked)
    if result.total_pages > limits.max_pages_per_drawing:
        result.error = "drawing_too_many_pages"
        result.message = message("drawing_too_many_pages", max=limits.max_pages_per_drawing)
    return result
