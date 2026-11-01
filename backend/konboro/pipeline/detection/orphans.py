"""3.6 (03 §3.6): electrical text with no symbol near it, the main guard against missed symbols.

A span stage 2 tagged as a device's value (`DEVICE_TAGS`: "C16", "30mA", "3X25A") should have a symbol within
`orphan_radius_pt`. For the ones that have none:
1. Nearby orphans are grouped, and each group gets one more search on a crop around it, with a hint that a symbol
   is expected there (03 §3.6 asks for a lower threshold; the interim model has none, so it is told to report unsure
   ones too). At most `max_orphan_searches` per page.
2. A symbol found within the radius of one of the group's texts, and not already found, joins as `orphan_recovery`.
3. A text still alone becomes an `orphan_text` for stage 4 (S13), with `recovery_attempted`.
"""

from collections.abc import Callable

from PIL import Image

from konboro.contracts.common import Bbox
from konboro.contracts.detection import OrphanText
from konboro.contracts.extraction import TextSpan

from ..extraction.geometry import union
from .candidates import Candidate, gap, same_symbol
from .config import DEVICE_TAGS, DetectionConfig
from .search import SearchImage

HINT = (
    "Electrical text ({texts}) is written near the middle of this image, and a device symbol is probably drawn next "
    "to it. Report every symbol you see here, also the ones you are unsure of."
)


def lonely(spans: list[TextSpan], found: list[Candidate], cfg: DetectionConfig) -> list[TextSpan]:
    tagged = [s for s in spans if any(k in s.tags for k in DEVICE_TAGS)]
    return [s for s in tagged if all(gap(s.bbox, c.bbox) > cfg.orphan_radius_pt for c in found)]


def groups(spans: list[TextSpan], cfg: DetectionConfig) -> list[list[TextSpan]]:
    """Spans within the radius of each other, transitively, in reading order."""
    out: list[list[TextSpan]] = []
    for s in sorted(spans, key=lambda s: (s.bbox[1], s.bbox[0])):
        joined = [g for g in out if any(gap(s.bbox, t.bbox) <= cfg.orphan_radius_pt for t in g)]
        merged = sorted([s] + [t for g in joined for t in g], key=lambda t: (t.bbox[1], t.bbox[0]))
        out = [g for g in out if g not in joined] + [merged]
    return sorted(out, key=lambda g: (min(t.bbox[1] for t in g), min(t.bbox[0] for t in g)))


def crop_box(group: list[TextSpan], size_pt: tuple[float, float], cfg: DetectionConfig) -> Bbox:
    x0, y0, x1, y1 = union([s.bbox for s in group])
    pad = cfg.orphan_crop_pad_pt
    return (max(0.0, x0 - pad), max(0.0, y0 - pad), min(size_pt[0], x1 + pad), min(size_pt[1], y1 + pad))


def recover(
    found: list[Candidate],
    spans: list[TextSpan],
    render: Image.Image,
    px_per_pt: float,
    size_pt: tuple[float, float],
    key: str,
    run: Callable[[list[tuple[SearchImage, str]]], list[list[Candidate]]],
    cfg: DetectionConfig,
) -> tuple[list[Candidate], list[OrphanText], int]:
    """New candidates, the orphan texts left, and how many searches ran. `run` searches (image, hint) pairs."""
    alone = lonely(spans, found, cfg)
    todo = groups(alone, cfg)[: cfg.max_orphan_searches]
    images: list[tuple[SearchImage, str]] = []
    for g in todo:
        box = crop_box(g, size_pt, cfg)
        px = (
            round(box[0] * px_per_pt),
            round(box[1] * px_per_pt),
            round(box[2] * px_per_pt),
            round(box[3] * px_per_pt),
        )
        image = render.crop(px)
        rounded = tuple(round(v, 1) for v in box)
        texts = ", ".join(s.text for s in g)
        images.append(
            (
                SearchImage(image, (px[0], px[1]), (0, 0, 0, 0), render.size, f"{key}:orphan:{rounded}"),
                HINT.format(texts=texts),
            )
        )
    new: list[Candidate] = []
    for g, results in zip(todo, run(images), strict=True):
        for c in results:
            if not any(gap(c.bbox, s.bbox) <= cfg.orphan_radius_pt for s in g):
                continue
            if any(same_symbol(c, k, cfg) for k in found + new):
                continue
            c.method = "orphan_recovery"
            new.append(c)
    searched = {s.span_id for g in todo for s in g}
    left = [
        OrphanText(span_id=s.span_id, text=s.text, bbox=s.bbox, recovery_attempted=s.span_id in searched)
        for s in alone
        if all(gap(s.bbox, c.bbox) > cfg.orphan_radius_pt for c in new)
    ]
    return new, left, len(todo)
