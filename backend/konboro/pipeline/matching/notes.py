"""What the drawing's notes ask for (05 §4.2, §5.4 priority 2, §5.5 item 1), read in code from stage 1's artifacts:

- `general_notes` pages, as Markdown: each line that names a family ("כל המא"זים", or none: every family) and a
  brand ("תוצרת שניידר"), "או ש"ע" (the factory's own brand may stand in, 05 §5.4), or values the stage-4 grammar
  reads ("10kA", "30mA", "עקומה C").
- `technical_data` (the whole drawing) and `notes_block` (one panel, 01 §5.5.1): the minimum breaking capacity, and
  the control voltage that coils take (05 §5.5.1).

A panel's note comes before the drawing's (05 §5.5 item 1). No model reads them: a line code can't read says nothing.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from konboro.contracts.intake import ContextArtifact

from ..association.grammar import parse
from ..bom import terms

BRANDS = {
    "ABB": "ABB",
    "אי.בי.בי": "ABB",
    "איי בי בי": "ABB",
    "SCHNEIDER": "Schneider",
    "שניידר": "Schneider",
    "HAGER": "Hager",
    "האגר": "Hager",
    "SIEMENS": "Siemens",
    "סימנס": "Siemens",
    "EATON": "Eaton",
    "איטון": "Eaton",
    "LEGRAND": "Legrand",
    "לגרנד": "Legrand",
}
_BRAND = re.compile(r"(?<![\w.])(" + "|".join(re.escape(b) for b in sorted(BRANDS, key=len, reverse=True)) + r")(?!\w)")
_EQUIVALENT = re.compile(r'או\s+ש["״]ע|או\s+שווה\s+ערך|or\s+equal|or\s+equivalent|or\s+approved\s+equal', re.I)
_CURVE = re.compile(r"(?:עקומה|curve)\s*([BCDK])\b", re.I)
# The plural a note writes; the singular forms are the BOM's words (`bom.terms`)
PLURALS = {
    'מא"זים': "circuit_breaker",
    "מא״זים": "circuit_breaker",
    "מאזים": "circuit_breaker",
    "מפסקי פחת": "rcd",
    "פחתים": "rcd",
    "מגענים": "contactor",
    "ממסרים": "relay",
    "נורות": "indicator_lamp",
    "לחצנים": "push_button",
    "בוררים": "selector_switch",
    "breakers": "circuit_breaker",
    "mcbs": "circuit_breaker",
    "contactors": "contactor",
}
_VALUE_KEYS = ("breaking_capacity_ka", "residual_ma", "rcd_type", "curve", "coil_voltage_v")
_VOLTS = re.compile(r"(\d{2,3})\s*V", re.I)
_PUNCT = re.compile(r"[,;:()]|\.(?=\s|$)")


@dataclass(frozen=True)
class NoteRule:
    family: str | None  # None: every family
    brand: str | None
    equivalent: bool
    attributes: dict[str, Any]
    text: str
    panel_id: str | None  # None: the whole drawing


@dataclass
class Notes:
    rules: list[NoteRule] = field(default_factory=list)
    control_voltage_v: dict[str | None, float] = field(default_factory=dict)  # panel id (None: drawing) → volts

    def applying(self, family: str, panel_id: str | None) -> list[NoteRule]:
        """The panel's notes first, then the drawing's (05 §5.5 item 1)."""
        fits = [r for r in self.rules if r.family in (None, family)]
        return [r for r in fits if r.panel_id == panel_id and panel_id] + [r for r in fits if r.panel_id is None]

    def voltage(self, panel_id: str | None) -> float | None:
        return self.control_voltage_v.get(panel_id) or self.control_voltage_v.get(None)


def _family(line: str) -> str | None:
    low = line.casefold()
    for word, family in PLURALS.items():
        if word.casefold() in low:
            return family
    found = terms.family_of(line)
    return found[0] if found else None


def line_rule(line: str, panel_id: str | None = None) -> NoteRule | None:
    line = line.strip().lstrip("-*•· ").strip()
    if not line:
        return None
    family = _family(line)
    brand_match = _BRAND.search(line.upper()) or _BRAND.search(line)
    brand = BRANDS.get(brand_match.group(1).upper(), BRANDS.get(brand_match.group(1))) if brand_match else None
    values: dict[str, Any] = {}
    if family is not None:
        for r in parse(_PUNCT.sub(" ", line)):
            if r.key in _VALUE_KEYS and r.fits(family) and r.key not in values:
                values[r.key] = r.value
        curve = _CURVE.search(line)
        if curve and "curve" not in values:
            values["curve"] = curve.group(1).upper()
    if brand is None and not values:
        return None
    return NoteRule(family, brand, bool(_EQUIVALENT.search(line)), values, line, panel_id)


def _requirements(content: dict[str, Any], panel_id: str | None, notes: Notes, label: str) -> None:
    bc = content.get("min_breaking_capacity_ka")
    if isinstance(bc, int | float) and bc > 0:
        text = f"{label}: כושר ניתוק {bc:g}kA לפחות"
        for family in ("circuit_breaker", "rcbo"):
            notes.rules.append(NoteRule(family, None, False, {"breaking_capacity_ka": bc}, text, panel_id))
    volts = _VOLTS.search(str(content.get("control_voltage") or ""))
    if volts:
        notes.control_voltage_v[panel_id] = float(volts.group(1))


def read(artifacts: list[ContextArtifact]) -> Notes:
    notes = Notes()
    for a in artifacts:
        if a.kind == "general_notes":
            for line in a.content.splitlines():
                rule = line_rule(line)
                if rule is not None:
                    notes.rules.append(rule)
        elif a.kind in ("technical_data", "notes_block") and a.format == "json":
            try:
                content = json.loads(a.content)
            except ValueError:
                continue
            panel_id = content.get("panel_id") if a.kind == "notes_block" else None
            label = "הערות הלוח" if a.kind == "notes_block" else "הנתונים הטכניים"
            _requirements(content, panel_id, notes, label)
    return notes
