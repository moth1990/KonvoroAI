"""3.7 (03 §3.7): each symbol's designator, the device tag written next to it (F1, Q0, C3, HT2, SW1, R5, TH1, FNV).

Code links it, from stage 2's spans: a value has evidence only when it is written (00 §5.3). The model's reading of
the tag is a hint, never the value.

1. Candidates are spans shaped like a tag (letters then digits, or a short run of letters) within
   `designator_radius` symbol heights of the box (at least `designator_min_radius_pt`), the box's own text included.
2. A span with the tag the model read wins, also a little farther out (twice the radius); else the nearest.
3. Some words are not tags (03 §3.7 item 2): phases and buses (`L1`–`L3`, `N`, `PE`, `W0`) count only next to a
   symbol they can name (NEVIS-1's lamps are L1–L3); ratings never do (`C16` beside a breaker is its curve and
   current); a run of letters only when the model read it or it is written inside the symbol's box (`ABB`, `MCB`
   beside a breaker are not tags; `NVR` inside a relay's box is).
4. An auxiliary contact takes only the tag the model read beside it: the nearest tag is usually the breaker or
   contactor next to it, and its own device is the one the dashed line leads to (item 4, not read in v1).
5. A list of tags on one symbol ("MS1/MS2/MS3", 26-993's three current transformers drawn once) is the designator
   of all of them, when the model read it beside that symbol and every tag in it would be accepted on its own and
   has a number. Never by nearness alone: a terminal beside 26-993's CTs took the list too. Stage 4 splits it (`tags`):
   one device per tag (BUG-031, S17).
6. On a drawing where most devices have a tag (`no_tag_share`), a billable device without one is flagged `no_tag`
   (03 §3.7 last line).
7. A tag written as two texts, a dotted abbreviation and the tag right after it on one line, is one tag: the
   abbreviation's letters, a hyphen, the tag (BUG-111: "T.C" "G1" beside 26-993's QG1 is its shunt trip TC-G1, as
   page 5 writes it whole). Only a dotted abbreviation of two or three letters joins ("T.C", "K.A."), never a word,
   a brand or a rating. Stage 3 links the tag's own span; stage 4 merges by the whole tag (`joined`), after the
   tile agent, so the agent's request (and its recorded answers) don't change.

Ranges on a front view ("R1-R7", item 5) and the dashed link from an auxiliary contact to its breaker (item 4) are
not read in v1: front views are not `process` pages, and the dashed line needs the wire graph's line styles.
"""

import re

from konboro.contracts.extraction import TextSpan

from .candidates import Candidate, gap
from .config import DetectionConfig

_TAG = re.compile(r"^[A-Z]{1,4}\d{0,3}(?:[.\-][A-Z]{0,2}\d{1,3})*$")
_LETTERS = re.compile(r"^[A-Z]{1,4}$")
_RATING = re.compile(r"^[BCDKZ]\d{2,3}A?$")  # C16, B10: a breaker's curve and current
_PHASE = re.compile(r"^(?:L[1-3]|N|PE|W\d)$")
PHASE_OK = {"indicator_lamp": re.compile(r"^L[1-3]$"), "busbar": re.compile(r"^W\d$")}
BREAKERS = ("circuit_breaker", "rcd", "rcbo")
PROTECTIVE = ("circuit_breaker", "rcd", "rcbo", "switch_disconnector", "fuse")
NOT_DEVICES = ("busbar", "ground", "junction", "motor_load")  # drawn, never billed: they don't own text
LIST_MAX = 6  # tags in one list on one symbol
RANGE_MAX = 12  # tags in one range ("T1-T3", "R1-R7")
_DIGIT = re.compile(r"\d")
COUNT = re.compile(r"^\(?[X×](?P<n>\d{1,2})\)?$")  # "x2", "X11": a count beside a device, or a terminal strip
_RANGE = re.compile(r"^(?P<p>[A-Z]{1,4})(?P<a>\d{1,3})-(?P=p)(?P<b>\d{1,3})$")  # one prefix both ends
_CIRCUITS = re.compile(r"^(?P<a>\d{1,3})[-–'’](?P<b>\d{1,3})$")  # "201-202", OCR'd "207'208"
_ABBREVIATION = re.compile(r"^[A-Z]\.(?:[A-Z]\.?){1,2}$")  # item 7: "T.C" (trip coil), "K.A.", never "T." alone
JOIN_GAP = 1.0  # item 7: the tag starts within this many text heights after the abbreviation ends
JOIN_LEVEL = 0.5  # item 7: and the two share this much of the lower one's height (one line)


def _canon(text: str) -> str:
    return re.sub(r"\s*/\s*", "/", text.strip().upper().replace("–", "-"))


def tags(designator: str | None) -> list[str]:
    """The tags a designator names: one, each of a list (item 5), or each of a range of one prefix (BUG-069:
    25.26.100's three current transformers "T1-T3")."""
    out: list[str] = []
    for part in designator.split("/") if designator else []:
        r = _RANGE.match(part)
        if r and int(r["a"]) < int(r["b"]) <= int(r["a"]) + RANGE_MAX - 1:
            out += [f"{r['p']}{n}" for n in range(int(r["a"]), int(r["b"]) + 1)]
        else:
            out.append(part)
    return out


def _is_range(t: str) -> bool:
    return "/" not in t and len(tags(t)) > 1


def _beside(a: TextSpan, b: TextSpan) -> bool:
    """Two texts written together: no more than a line and a half apart."""
    h = max(a.bbox[3] - a.bbox[1], b.bbox[3] - b.bbox[1], 1.0)
    return gap(a.bbox, b.bbox) <= 1.5 * h


def counts(found: list[Candidate], spans: list[TextSpan], cfg: DetectionConfig) -> set[str]:
    """BUG-067: the spans that are a count, not a tag. "x2" or "X11" is a count when the nearest device is a
    protective one, or when it is written beside a rating ("16A") or beside a range of that many circuits
    ("X2" over "201-202", 04 §5.1.1 rule 4). Stage 4 reads it as the device's multiplicity."""
    ratings = [s for s in spans if "current_a" in s.tags]
    ranges = []
    for s in spans:
        r = _CIRCUITS.match(s.text.strip())
        if r and int(r["a"]) < int(r["b"]):
            ranges.append((s, int(r["b"]) - int(r["a"]) + 1))
    out: set[str] = set()
    for s in spans:
        m = COUNT.match(_canon(s.text))
        if not m:
            continue
        near = [
            (gap(c.bbox, s.bbox), c)
            for c in found
            if c.family not in NOT_DEVICES and gap(c.bbox, s.bbox) <= _radius(c, cfg)
        ]
        nearest = min(near, key=lambda it: it[0])[1] if near else None
        if (
            (nearest is not None and nearest.family in PROTECTIVE)
            or any(_beside(s, r) for r in ratings)
            or any(size == int(m["n"]) and _beside(s, r) for r, size in ranges)
        ):
            out.add(s.span_id)
    return out


def _radius(c: Candidate, cfg: DetectionConfig) -> float:
    return max(cfg.designator_min_radius_pt, cfg.designator_radius * c.height)


def _one_tag(t: str) -> bool:
    return bool(_TAG.match(t)) and len(t) <= 8


def tag_shaped(span: TextSpan) -> bool:
    if _is_range(_canon(span.text)):
        return True
    parts = tags(_canon(span.text))
    if len(parts) == 1:
        return _one_tag(parts[0])
    return 2 <= len(parts) <= LIST_MAX and all(_one_tag(p) and _DIGIT.search(p) for p in parts)


def acceptable(text: str, c: Candidate, model_read: bool, inside: bool = False) -> bool:
    """`inside`: the span lies in the symbol's own box (a coil labelled with its tag)."""
    t = _canon(text)
    if _is_range(t):  # a range by nearness too, but never a terminal's (they stand beside every device)
        return (model_read or c.family not in ("terminal", *NOT_DEVICES)) and acceptable(
            t.split("-")[0], c, model_read, inside
        )
    parts = tags(t)
    if len(parts) > 1:
        return model_read and all(_DIGIT.search(p) and acceptable(p, c, model_read, inside) for p in parts)
    if COUNT.match(t):
        return c.family == "terminal"  # BUG-067: a terminal strip's tag; beside any other device, a count
    if _PHASE.match(t):
        rule = PHASE_OK.get(c.family)
        return bool(rule and rule.match(t))
    if c.family in BREAKERS and _RATING.match(t) and not model_read:
        return False
    return model_read or inside or not _LETTERS.match(t)


def joined(spans: list[TextSpan]) -> dict[str, str]:
    """Item 7: span id → the whole tag, for each tag written right after a dotted abbreviation on one line."""
    out: dict[str, str] = {}
    for a in spans:
        if not _ABBREVIATION.match(_canon(a.text)):
            continue
        letters = _canon(a.text).replace(".", "")
        for s in spans:
            t = _canon(s.text)
            if s is a or len(tags(t)) != 1 or not _one_tag(t) or not t[0].isalpha() or COUNT.match(t):
                continue
            h = max(min(a.bbox[3] - a.bbox[1], s.bbox[3] - s.bbox[1]), 1.0)
            level = min(a.bbox[3], s.bbox[3]) - max(a.bbox[1], s.bbox[1])
            if level >= JOIN_LEVEL * h and 0 <= s.bbox[0] - a.bbox[2] <= JOIN_GAP * h and _one_tag(f"{letters}-{t}"):
                out[s.span_id] = f"{letters}-{t}"
    return out


def link(c: Candidate, spans: list[TextSpan], cfg: DetectionConfig, counts: set[str] = frozenset()) -> None:  # type: ignore[assignment]
    """`counts`: the spans that are counts on this page (`counts`), never a tag."""
    radius = _radius(c, cfg)
    wanted = _canon(c.tag) if c.tag else None
    near = [(gap(c.bbox, s.bbox), s) for s in spans if tag_shaped(s) and s.span_id not in counts]
    if wanted:
        read = [(d, s) for d, s in near if d <= 2 * radius and _canon(s.text) == wanted]
        if read and acceptable(wanted, c, model_read=True):
            _, span = min(read, key=lambda it: it[0])
            c.designator, c.designator_span_id = _canon(span.text), span.span_id
            return
    if c.role == "aux_contact":
        return  # its device is the one it is mounted on: the dashed link (item 4), not the nearest tag
    pool = [(d, s) for d, s in near if d <= radius and acceptable(s.text, c, model_read=False, inside=d == 0)]
    if pool:
        _, span = min(pool, key=lambda it: it[0])
        c.designator, c.designator_span_id = _canon(span.text), span.span_id


def flag_untagged(found: list[Candidate], billable: dict[str, bool], cfg: DetectionConfig) -> None:
    devices = [c for c in found if c.role == "device" and billable.get(c.symbol_class, False)]
    if not devices:
        return
    tagged = sum(1 for c in devices if c.designator)
    if tagged / len(devices) >= cfg.no_tag_share:
        for c in devices:
            if not c.designator and "no_tag" not in c.flags:
                c.flags.append("no_tag")
