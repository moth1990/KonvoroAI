"""04 §5.1: the spelling grammar. The patterns are data (`grammar.json`); this module reads a span's text through them.

`parse(text)` returns every reading of every word: one text may mean several things ("6000" beside a breaker is its
breaking capacity, beside a meter it is something else), and the symbol's family picks (`Reading.fits`). A full match
of a pattern reads at its confidence (1.0 unless the file says lower).

Keys a reading fills:
- attributes, by the family's schema (`schemas.py`): `current_a`, `poles`, `neutral`, `curve`, … ;
- `load_current_a` (`INC=`, `Ib=`): the circuit's load, never `current_a` (04 §5.1, NEVIS-1 and 26-993);
- `multiplicity` (04 §5.1.1), `cable_cores` / `cable_cross_section_mm2` / `cable_raw`, `circuit_range`;
- `model_token` and `brand` for stage 5 (05 §5.2), `symbol_class` / `family` as hints, `spare`, `lockable`;
- `unknown_prefixed`: a value behind a prefix we don't know, kept as text for the grammar's work list.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

# Keys that are not one of a family's attributes: what they mean is decided elsewhere (04 §5.1.1, §5.8, 05 §5.2)
CONTEXT_KEYS = frozenset(
    {
        "load_current_a",
        "multiplicity",
        "cable_cores",
        "cable_cross_section_mm2",
        "cable_raw",
        "circuit_range",
        "model_token",
        "brand",
        "symbol_class",
        "family",
        "spare",
        "lockable",
        "unknown_prefixed",
        "ik_ka",
        "ip_rating",
        "rcd_type_si",
    }
)

_INT_KEYS = {"poles", "residual_ma", "ratio_secondary_a", "multiplicity"}
COLOURS = {
    **dict.fromkeys(("ירוק", "ירוקה", "green"), "green"),
    **dict.fromkeys(("אדום", "אדומה", "red"), "red"),
    **dict.fromkeys(("צהוב", "צהובה", "yellow"), "yellow"),
    **dict.fromkeys(("כחול", "כחולה", "blue"), "blue"),
    **dict.fromkeys(("לבן", "לבנה", "white"), "white"),
}


@dataclass(frozen=True)
class Reading:
    key: str
    value: Any
    confidence: float
    pattern: str
    token: str  # the words it was read from
    families: frozenset[str] | None = None  # only these families read it
    not_families: frozenset[str] = frozenset()

    def fits(self, family: str) -> bool:
        if family in self.not_families:
            return False
        return self.families is None or family in self.families


@dataclass(frozen=True)
class Pattern:
    id: str
    regex: re.Pattern[str]
    scope: str
    confidence: float
    set: dict[str, Any]
    build: str | None
    families: frozenset[str] | None
    not_families: frozenset[str]
    fallback: bool  # only when no other pattern read the word


@dataclass(frozen=True)
class Grammar:
    version: str
    patterns: tuple[Pattern, ...]
    scope_phrases: dict[str, tuple[str, ...]]


def _number(text: str) -> float | int:
    value = float(text.replace(",", "."))
    return int(value) if value.is_integer() else value


def _plain(groups: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, raw in groups.items():
        if raw is None:
            continue
        if key == "residual_a":  # 0.03A, 0,03 → 30 mA
            out["residual_ma"] = round(float(raw.replace(",", ".")) * 1000)
        elif key == "breaking_a":  # "6000" in a frame beside a breaker (04 §5.1)
            out["breaking_capacity_ka"] = _number(raw) / 1000
        elif key == "count":
            out["multiplicity"] = int(raw)
        elif key == "poles_socket":  # CEE 5×16A: 5 pins, 3P+N
            out["poles"] = {1: 1, 3: 1, 4: 3, 5: 3}.get(int(raw), int(raw))
            if int(raw) in (3, 5):
                out["neutral"] = True
        elif key == "color":
            out[key] = COLOURS[raw.strip().casefold()]
        elif key in ("contacts", "positions"):
            out[key] = raw.strip().replace("-", "/") if key == "contacts" else raw.strip()
        elif key in ("curve", "rcd_type", "spd_class", "trip_unit", "ip_rating", "model_token", "brand"):
            out[key] = raw.strip().upper() if key in ("curve", "rcd_type", "trip_unit", "brand") else raw.strip()
        elif key == "unknown_prefixed":
            out[key] = raw
        else:
            n = _number(raw)
            out[key] = int(n) if key in _INT_KEYS else n
    return out


def _rating_pair(groups: dict[str, str]) -> dict[str, Any]:
    """`500A/630A` beside a moulded-case breaker: the rated current is the larger, the setting the smaller."""
    a, b = _number(groups["a"]), _number(groups["b"])
    return {"current_a": max(a, b), "setting_a": min(a, b)}


def _cable(groups: dict[str, str]) -> dict[str, Any]:
    return {
        "cable_cores": int(groups["cores"]),
        "cable_cross_section_mm2": _number(groups["cross_section_mm2"]),
    }


def _circuit_range(groups: dict[str, str]) -> dict[str, Any]:
    a, b = int(groups["range_from"]), int(groups["range_to"])
    return {"circuit_range": (a, b)} if 0 < a < b <= a + 60 else {}


def _coil_voltage(groups: dict[str, str]) -> dict[str, Any]:
    return {"coil_voltage_v": _number(groups["voltage_v"])}


BUILDERS: dict[str, Callable[[dict[str, str]], dict[str, Any]]] = {
    "rating_pair": _rating_pair,
    "cable": _cable,
    "circuit_range": _circuit_range,
    "coil_voltage": _coil_voltage,
}


def from_json(data: dict[str, Any]) -> Grammar:
    patterns = []
    for p in data["patterns"]:
        build = p.get("build")
        if build is not None and build not in BUILDERS:
            raise ValueError(f"grammar pattern {p['id']}: unknown builder {build!r}")
        patterns.append(
            Pattern(
                id=p["id"],
                regex=re.compile(p["re"]),
                scope=p.get("scope", "token"),
                confidence=float(p.get("confidence", 1.0)),
                set=dict(p.get("set", {})),
                build=build,
                families=frozenset(p["families"]) if "families" in p else None,
                not_families=frozenset(p.get("not_families", ())),
                fallback=bool(p.get("fallback", False)),
            )
        )
    ids = [p.id for p in patterns]
    if len(ids) != len(set(ids)):
        raise ValueError("grammar pattern ids must be unique")
    phrases = {k: tuple(v) for k, v in data["scope_phrases"].items() if k != "about"}
    return Grammar(version=data["version"], patterns=tuple(patterns), scope_phrases=phrases)


@cache
def load() -> Grammar:
    text = resources.files(__package__).joinpath("grammar.json").read_text(encoding="utf-8")
    return from_json(json.loads(text))


def _values(p: Pattern, match: re.Match[str]) -> dict[str, Any]:
    groups = {k: v for k, v in match.groupdict().items() if v is not None}
    values = BUILDERS[p.build](groups) if p.build else _plain(groups)
    return {**values, **p.set}


def _readings(p: Pattern, match: re.Match[str], token: str) -> list[Reading]:
    return [
        Reading(key, value, p.confidence, p.id, token, p.families, p.not_families)
        for key, value in _values(p, match).items()
    ]


def parse(text: str, grammar: Grammar | None = None) -> list[Reading]:
    """Every reading of the text, in pattern order: word patterns on each word, text patterns on the whole."""
    g = grammar or load()
    out: list[Reading] = []
    words = text.split()
    for word in words:
        found = False
        for p in g.patterns:
            if p.scope != "token" or (p.fallback and found):
                continue
            match = p.regex.match(word)
            if match:
                read = _readings(p, match, word)
                out += read
                found = found or bool(read)
    for p in g.patterns:
        if p.scope == "text":
            for match in p.regex.finditer(text):
                out += _readings(p, match, match.group(0).strip())
    if out and any(r.key == "cable_cores" for r in out):
        out.append(Reading("cable_raw", text, 1.0, "cable", text))
    return out


def values(text: str, family: str, grammar: Grammar | None = None) -> dict[str, list[Any]]:
    """What the text says, as this family reads it: key → every value read (the citation check, 04 §5.5)."""
    out: dict[str, list[Any]] = {}
    for r in parse(text, grammar):
        if r.fits(family) and not any(same(v, r.value) for v in out.get(r.key, [])):
            out.setdefault(r.key, []).append(r.value)
    return out


def contains(text: str, family: str, key: str, value: Any, grammar: Grammar | None = None) -> bool:
    """04 §5.5: the value is really written in the text, as the grammar reads it for this family."""
    return any(same(v, value) for v in values(text, family, grammar).get(key, []))


def same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return abs(float(a) - float(b)) < 1e-6
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().casefold() == b.strip().casefold()
    return bool(a == b)
