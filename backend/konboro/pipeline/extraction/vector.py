"""2.2 vector extraction (02 §2.2) with pdfplumber (12 §5): the PDF's own words, its lines and shapes, its layers.

pdfplumber gives every character and path with the page's /Rotate applied, origin top left. Its own word grouping
splits sideways words, so words are grouped here, in each character's reading direction. Hebrew comes out of a PDF
in visual order and is put back in reading order (02 §2.4).

`rotation` of a span is the direction its text reads, counter-clockwise from left-to-right: 90 reads bottom to top.
Everything returned is on the upright page (stage 1's extra turn applied).
"""

import gzip
import io
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

import pdfplumber

from konboro.contracts.common import Bbox

from .geometry import Size, turn_box, turn_point, turned_size

GAP_SHARE = 0.3  # a gap wider than this share of the text height ends a word
LINE_SHARE = 0.5  # characters on one line overlap by at least this share of the smaller height
GLYPH_MAX_PT = 12.0  # a path smaller than this both ways may be a letter drawn as lines (01 §5.2)
GLYPH_MIN_PT = 2.0
GLYPH_PERCENTILE = 0.9  # the tall strokes of drawn letters give their height
HEBREW = range(0x0590, 0x0600)
LTR_RUN = re.compile(r"[A-Za-z0-9.,:/%+×\-]+")


@dataclass
class Word:
    text: str
    bbox: Bbox
    rotation: int
    font_size_pt: float
    color: str | None


@dataclass
class Path:
    kind: str  # line, curve, rect
    points: list[tuple[float, float]]
    width: float
    color: str | None

    def bbox(self) -> Bbox:
        xs, ys = [p[0] for p in self.points], [p[1] for p in self.points]
        return (min(xs), min(ys), max(xs), max(ys))


@dataclass
class VectorPage:
    words: list[Word] = field(default_factory=list)
    paths: list[Path] = field(default_factory=list)
    layers: list[tuple[str, bool]] = field(default_factory=list)  # name, shown by default
    text_height_pt: float | None = None  # a typical text height, for the DPI (02 §2.1)


def hex_color(value: Any) -> str | None:
    """pdfplumber's colour (grey, RGB or CMYK, 0–1) as #rrggbb; None for black, white or unknown."""
    if not isinstance(value, list | tuple) or not all(isinstance(v, int | float) for v in value):
        return None
    if len(value) == 1:
        r = g = b = float(value[0])
    elif len(value) == 3:
        r, g, b = (float(v) for v in value)
    elif len(value) == 4:
        c, m, y, k = (float(v) for v in value)
        r, g, b = (1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)
    else:
        return None
    rgb = tuple(max(0, min(255, round(v * 255))) for v in (r, g, b))
    if max(rgb) < 40 or min(rgb) > 235:  # black or white carry no meaning
        return None
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def visual_to_logical(text: str) -> str:
    """A line in visual order (left to right on the page) with Hebrew in it, in reading order. Numbers and Latin
    runs keep their own order: "16A" stays "16A" inside a Hebrew line."""
    if not any(ord(ch) in HEBREW for ch in text):
        return text
    return LTR_RUN.sub(lambda m: m.group()[::-1], text[::-1])


def _char_rotation(char: dict[str, Any]) -> int:
    """pdfplumber's matrix already includes the page's /Rotate, with y pointing up."""
    a, b = char["matrix"][0], char["matrix"][1]
    return int(round(math.degrees(math.atan2(b, a)) / 90) * 90 % 360)


def _words(chars: list[dict[str, Any]], size: Size) -> list[Word]:
    by_rotation: dict[int, list[tuple[Bbox, dict[str, Any]]]] = {}
    for ch in chars:  # spaces stay in: a space ends a word
        rot = _char_rotation(ch)
        box = (float(ch["x0"]), float(ch["top"]), float(ch["x1"]), float(ch["bottom"]))
        # turned clockwise by its rotation, the character reads left to right
        by_rotation.setdefault(rot, []).append((turn_box(box, size, rot), ch))
    words: list[Word] = []
    for rot, items in by_rotation.items():
        frame = turned_size(size, rot)
        items.sort(key=lambda it: ((it[0][1] + it[0][3]) / 2, it[0][0]))
        lines: list[list[tuple[Bbox, dict[str, Any]]]] = []
        for it in items:
            for line in lines:
                ref = line[-1][0]
                overlap = min(ref[3], it[0][3]) - max(ref[1], it[0][1])
                if overlap >= LINE_SHARE * min(ref[3] - ref[1], it[0][3] - it[0][1]):
                    line.append(it)
                    break
            else:
                lines.append([it])
        for line in lines:
            line.sort(key=lambda it: it[0][0])
            current: list[tuple[Bbox, dict[str, Any]]] = []
            for it in line:
                if not it[1]["text"].strip():
                    if current:
                        words.append(_word(current, rot, frame))
                    current = []
                    continue
                if current:
                    height = max(c[0][3] - c[0][1] for c in current)
                    if it[0][0] - current[-1][0][2] > GAP_SHARE * height:
                        words.append(_word(current, rot, frame))
                        current = []
                current.append(it)
            if current:
                words.append(_word(current, rot, frame))
    return words


def _word(items: list[tuple[Bbox, dict[str, Any]]], rot: int, frame: Size) -> Word:
    box = (
        min(b[0] for b, _ in items),
        min(b[1] for b, _ in items),
        max(b[2] for b, _ in items),
        max(b[3] for b, _ in items),
    )
    text = visual_to_logical("".join(ch["text"] for _, ch in items))
    colors = [hex_color(ch.get("non_stroking_color")) for _, ch in items]
    return Word(
        text=text,
        bbox=turn_box(box, frame, (360 - rot) % 360),
        rotation=rot,
        font_size_pt=round(box[3] - box[1], 2),
        color=max(set(colors), key=colors.count),
    )


def _paths(page: Any) -> list[Path]:
    out: list[Path] = []
    for kind in ("line", "curve", "rect"):
        for obj in page.objects.get(kind, []):
            if kind == "rect":
                x0, top, x1, bottom = obj["x0"], obj["top"], obj["x1"], obj["bottom"]
                points = [(x0, top), (x1, top), (x1, bottom), (x0, bottom), (x0, top)]
            else:
                points = [(float(x), float(y)) for x, y in obj["pts"]]
            out.append(Path(kind, points, float(obj.get("linewidth") or 0), hex_color(obj.get("stroking_color"))))
    return out


def text_height(words: list[Word], paths: list[Path]) -> float | None:
    """A typical text height (02 §2.1): the median word height from a text layer, or else the tall strokes of
    letters drawn as lines."""
    if words:
        heights = sorted(w.font_size_pt for w in words)
        return heights[len(heights) // 2]
    strokes = sorted(
        h
        for p in paths
        for x0, y0, x1, y1 in [p.bbox()]
        if (h := y1 - y0) >= GLYPH_MIN_PT and h < GLYPH_MAX_PT and x1 - x0 < GLYPH_MAX_PT
    )
    return strokes[int(GLYPH_PERCENTILE * (len(strokes) - 1))] if strokes else None


def read(data: bytes, index: int, extra_turn: int, with_text: bool) -> VectorPage:
    """One PDF page, upright. `with_text` is false when stage 1 found no reliable text layer (02 §7)."""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        page = pdf.pages[index]
        size = (float(page.width), float(page.height))
        words = _words(page.chars, size) if with_text else []
        paths = _paths(page)
        layers = _layers(pdf)
    height = text_height(words, paths)
    if extra_turn:
        for w in words:
            w.bbox = turn_box(w.bbox, size, extra_turn)
            w.rotation = (w.rotation - extra_turn) % 360
        for p in paths:
            p.points = [turn_point(pt, size, extra_turn) for pt in p.points]
    return VectorPage(words, paths, layers, height)


def _layers(pdf: Any) -> list[tuple[str, bool]]:
    """The PDF's optional content groups (02 §2.2 "שכבות"), with whether each is shown by default."""
    from pdfminer.pdftypes import resolve1  # pdfminer keeps references unresolved

    try:
        props = resolve1(pdf.doc.catalog.get("OCProperties"))
        if not props:
            return []
        off = {id(resolve1(g)) for g in resolve1(resolve1(props.get("D", {})).get("OFF", []))}
        layers: dict[str, bool] = {}
        for g in resolve1(props.get("OCGs", [])):
            group = resolve1(g)
            name = group.get("Name")
            text = name.decode("utf-8", "replace") if isinstance(name, bytes) else str(name)
            if name and text not in layers:
                layers[text] = id(group) not in off
        return list(layers.items())
    except Exception:  # a damaged /OCProperties costs only the layer names
        return []


def paths_json(paths: list[Path]) -> bytes:
    """`paths.json.gz` (02 §6.1 `vector.paths_uri`): every line and shape, with width and colour (02 §12 item 5)."""
    rows = [
        {"k": p.kind, "pts": [[round(x, 2), round(y, 2)] for x, y in p.points], "w": p.width, "c": p.color}
        for p in paths
    ]
    return gzip.compress(json.dumps(rows, separators=(",", ":")).encode())
