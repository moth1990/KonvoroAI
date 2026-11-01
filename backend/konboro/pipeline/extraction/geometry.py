"""Boxes on a page (00 §6.2): PDF points, origin top left of the upright page, `[x0, y0, x1, y1]`.

Two spaces meet here. What PDFium and pdfplumber read is the page with its /Rotate applied; stage 1 may turn it
further, clockwise, so its text reads upright (`PageRead.extra_rotation`). Everything stage 2 writes is upright.
"""

from konboro.contracts.common import Bbox

Size = tuple[float, float]


def turned_size(size: Size, turn: int) -> Size:
    w, h = size
    return (h, w) if turn % 180 else (w, h)


def turn_box(box: Bbox, size: Size, turn: int) -> Bbox:
    """A box on a page of `size`, after the page is turned `turn` degrees clockwise (a multiple of 90)."""
    x0, y0, x1, y1 = box
    w, h = size
    for _ in range((turn % 360) // 90):
        x0, y0, x1, y1 = h - y1, x0, h - y0, x1
        w, h = h, w
    return (x0, y0, x1, y1)


def turn_point(point: tuple[float, float], size: Size, turn: int) -> tuple[float, float]:
    x, y = point
    w, h = size
    for _ in range((turn % 360) // 90):
        x, y = h - y, x
        w, h = h, w
    return (x, y)


def unturn_fraction(box: Bbox, upright_size: Size, turn: int) -> tuple[float, float, float, float]:
    """An upright box as fractions of the page before the turn: how the renderer crops (it turns after cutting)."""
    w, h = upright_size
    x0, y0, x1, y1 = box[0] / w, box[1] / h, box[2] / w, box[3] / h
    for _ in range((turn % 360) // 90):  # undo one clockwise quarter turn at a time
        x0, y0, x1, y1 = y0, 1 - x1, y1, 1 - x0
    return (max(0.0, x0), max(0.0, y0), min(1.0, x1), min(1.0, y1))


def area(b: Bbox) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def intersection(a: Bbox, b: Bbox) -> float:
    return area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def iou(a: Bbox, b: Bbox) -> float:
    inter = intersection(a, b)
    union = area(a) + area(b) - inter
    return inter / union if union else 0.0


def overlap_of_smaller(a: Bbox, b: Bbox) -> float:
    """The share of the smaller box that the other covers: 02 §2.4's "bbox overlap above 50%"."""
    small = min(area(a), area(b))
    return intersection(a, b) / small if small else 0.0


def union(boxes: list[Bbox]) -> Bbox:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def grow(box: Bbox, share: float, size: Size) -> Bbox:
    """The box with `share` of the page's size added on every side, inside the page."""
    dx, dy = share * size[0], share * size[1]
    return (max(0.0, box[0] - dx), max(0.0, box[1] - dy), min(size[0], box[2] + dx), min(size[1], box[3] + dy))


def contains(outer: Bbox, inner: Bbox) -> bool:
    return outer[0] <= inner[0] and outer[1] <= inner[1] and inner[2] <= outer[2] and inner[3] <= outer[3]
