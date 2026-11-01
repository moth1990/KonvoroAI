"""The symbol library (03 §4.3–4.6) as data: families, symbol classes, roles and the global abbreviation dictionary.

This module is the source of the global rows: `seed_global` writes `FAMILIES` / `CLASSES` into `symbol_classes` and
`ABBREVIATIONS` into `abbreviations`, and the curated reference crops (`reference/*.png`, drawn by
`konboro.devtools.draw_symbols`) into `reference_crops`. At run time stage 3 reads the library back from the database
(`load`), so a row the pilot engineer approves joins the next drawing without a deploy, with the tenant's and the
designer's abbreviations on top (03 §4.6: global < tenant < designer).

`symbol_class` carries no poles (03 §14 item 3): stage 4 reads them.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.db import models as m


@dataclass(frozen=True)
class Family:
    family: str
    billable: bool
    looks: str  # what it looks like on a drawing, for the detection prompt (English: the model's language)
    classes: tuple[tuple[str, str], ...]  # (symbol_class, display_name_he); the first is the family's default


# 03 §4.4, §4.5 (the families added there), the families added after 6199-2-50, and `labeled_box` (§4.6) is not a
# family of its own here: a box with text is reported as what its text says, and code checks the text (`classify_box`).
FAMILIES: tuple[Family, ...] = (
    Family(
        "circuit_breaker",
        True,
        "a switch contact with a cross (x) at the fixed contact, often with pole marks, a thermal hook or a magnetic "
        "box on the line (those are drawn on every breaker). The class comes from what is written beside it: mccb "
        "for MCCB, a moulded-case model (XT1, XT2, NZM, NSX, Tmax) or a main breaker of 100A and more; "
        "motor_protection for MS116, PKZM, GV2 or a motor-protection range (4-6.3A); else mcb",
        (
            ("mcb", 'מפסק זרם אוטומטי (מא"ז)'),
            ("mccb", "מפסק בתיבה יצוקה"),
            ("motor_protection", "מגן מנוע"),
        ),
    ),
    Family(
        "rcd",
        True,
        "a switch contact with a ring or oval around the line (the current sensor), often marked ΔI or 30mA; or a box "
        'labelled "מ.פ."',
        (("rcd", "מפסק פחת"),),
    ),
    Family(
        "rcbo",
        True,
        "a breaker (x at the contact) and a residual-current ring on the same device",
        (("rcbo", 'מא"ז משולב פחת'),),
    ),
    Family(
        "switch_disconnector",
        True,
        "a switch contact with a short bar across the fixed contact (disconnector), sometimes also a small circle",
        (("switch_disconnector", "מנתק / מפסק עומס"),),
    ),
    Family(
        "fuse",
        True,
        "a small rectangle with the line running through it lengthwise; a fuse base or fuse switch",
        (("fuse", "נתיך"), ("fuse_base", "בסיס נתיך")),
    ),
    Family(
        "contactor",
        True,
        "power contacts with a half-circle at the fixed contact (single-line or power diagram), or its coil: a "
        "rectangle on the control line, often labelled C1, K1 (role coil)",
        (("contactor", "מגען"),),
    ),
    Family(
        "relay",
        True,
        "an auxiliary relay: a coil rectangle labelled R1, RNV, or its contacts",
        (("relay", "ממסר עזר"),),
    ),
    Family(
        "timer",
        True,
        "a time relay: a coil rectangle with a clock or hatched side, labelled KT, T",
        (("timer", "ממסר זמן"),),
    ),
    Family(
        "overload_relay",
        True,
        "a thermal overload relay: a rectangle with a zigzag or hook (thermal element) on the power lines",
        (("overload_relay", "ממסר תרמי"),),
    ),
    Family(
        "surge_protector",
        True,
        "a surge arrester: a rectangle or arrow between the lines and earth, labelled SPD or with kA",
        (("surge_protector", "מגן ברק (SPD)"),),
    ),
    Family(
        "energy_meter",
        True,
        'a rectangle labelled kWh, a meter model (SATEC …), or "מונה"',
        (("energy_meter", "מונה"),),
    ),
    Family(
        "current_transformer",
        True,
        "a ring or two loops around a line, often with a ratio such as 125/5A",
        (("current_transformer", "משנה זרם"),),
    ),
    Family(
        "ats",
        True,
        "an automatic transfer switch: a box labelled ATS between two supplies",
        (("ats", "מחליף אוטומטי"),),
    ),
    Family(
        "indicator_lamp",
        True,
        "a circle with an X inside (often coloured), labelled L1, H1, HNV",
        (("indicator_lamp", "נורת סימון"),),
    ),
    Family(
        "push_button",
        True,
        "a contact with a push actuator: a T-shaped or dashed line from the side, or a mushroom head for emergency",
        (("push_button", "לחצן"), ("emergency_button", "לחצן חירום")),
    ),
    Family(
        "selector_switch",
        True,
        "a rotary switch: contacts with positions marked 1-0-2 or 0-1, labelled SW",
        (("selector_switch", "בורר"),),
    ),
    Family(
        "measuring_instrument",
        True,
        "a circle with A, V or Hz inside (ammeter, voltmeter), or a multimeter box",
        (("measuring_instrument", "מכשיר מדידה"),),
    ),
    Family(
        "terminal",
        True,
        "a small circle or a slashed circle at a line's end; a terminal block",
        (("terminal", "מהדק"),),
    ),
    Family(
        "aux_contact",
        True,
        "a small auxiliary contact mounted on another device, marked 13/14 or 21/22",
        (("aux_contact", "מגע עזר"),),
    ),
    Family("relay_coil", True, "a relay coil drawn alone: a rectangle with A1/A2", (("relay_coil", "סליל ממסר"),)),
    Family(
        "temperature_controller",
        True,
        "a box labelled TH, °C or with a thermometer; a temperature controller",
        (("temperature_controller", "בקר טמפרטורה"),),
    ),
    Family(
        "voltage_relay", True, "a box labelled NVR, U< or a phase-failure relay", (("voltage_relay", "ממסר חוסר מתח"),)
    ),
    Family("shunt_trip", True, 'a small rectangle labelled "TC" next to a breaker', (("shunt_trip", "סליל הפסקה"),)),
    Family(
        "impulse_relay",
        True,
        "a rectangle with a step sign: an impulse relay (telerupter)",
        (("impulse_relay", "ממסר צעד"),),
    ),
    Family(
        "time_switch",
        True,
        "a rectangle with a clock face: a time switch, Sabbath clock",
        (("time_switch", "שעון שבת / שעון פיקוד"),),
    ),
    Family(
        "socket_outlet",
        True,
        'a socket: a half circle with pins, CEE or ת"י, mounted on the panel',
        (("socket_outlet", "בית תקע"),),
    ),
    Family(
        "changeover_switch",
        True,
        "a manual changeover switch: one moving contact between two fixed contacts (mains / generator)",
        (("changeover_switch", "מחליף ידני"),),
    ),
    Family(
        "busbar", False, "a long thick line that many branches leave from (W0, L1,L2,L3)", (("busbar", "פס צבירה"),)
    ),
    Family("ground", False, "the earth sign: a line with three shrinking bars", (("ground", "הארקה"),)),
    Family("motor_load", False, "a circle with M: a motor or a load outside the panel", (("motor_load", "צרכן"),)),
    Family("junction", False, "a filled dot where lines join", (("junction", "נקודת חיבור"),)),
)

UNKNOWN = "unknown_symbol"  # 03 §4.4: looks like a symbol, not recognised; `none_of_these` (03 §3.4)

ROLES = ("device", "power_contact", "coil", "relay_contact", "aux_contact", "front_view")  # 03 §4.5

# Families a reader confuses (03 §3.4 candidates): the disambiguation call is shown these classes too.
CONFUSABLE: dict[str, tuple[str, ...]] = {
    "circuit_breaker": ("rcbo", "switch_disconnector", "rcd"),
    "rcd": ("rcbo", "circuit_breaker"),
    "rcbo": ("rcd", "circuit_breaker"),
    "switch_disconnector": ("circuit_breaker", "changeover_switch"),
    "overload_relay": ("circuit_breaker",),  # a breaker's thermal release looks like one (6199-2-50)
    "contactor": ("relay", "time_switch", "impulse_relay", "relay_coil"),
    "relay": ("contactor", "relay_coil", "timer", "voltage_relay"),
    "relay_coil": ("relay", "contactor"),
    "timer": ("relay", "time_switch"),
    "time_switch": ("timer", "contactor"),
    "voltage_relay": ("relay",),
    "impulse_relay": ("relay", "contactor"),
    "indicator_lamp": ("push_button", "measuring_instrument"),
    "push_button": ("indicator_lamp", "selector_switch", "contactor"),
    "selector_switch": ("push_button", "changeover_switch"),
    "changeover_switch": ("switch_disconnector", "selector_switch", "contactor", "ats"),
    "fuse": ("switch_disconnector", "circuit_breaker"),
    "terminal": ("current_transformer", "fuse"),  # a block of current transformers with test terminals (26-993)
    "current_transformer": ("terminal", "measuring_instrument"),
    "aux_contact": ("relay",),
}

# 03 §4.6, global level. A text matches an entry when it equals it, or when the entry is letters and the text is
# those letters followed by a number ("C" matches "C1", "C12", "C1.2"): a box labelled with its own designator.
ABBREVIATIONS: tuple[tuple[str, str], ...] = (
    ("מ.פ.", "rcd"),
    ("מפסק פחת", "rcd"),
    ("RCD", "rcd"),
    ("RCBO", "rcbo"),
    ("TC", "shunt_trip"),
    ("C", "contactor"),
    ("K", "contactor"),
    ("KM", "contactor"),
    ("R", "relay"),
    ("KA", "relay"),
    ("RNV", "relay"),
    ("KT", "timer"),
    ("NVR", "voltage_relay"),
    ("U<", "voltage_relay"),
    ("TH", "temperature_controller"),
    ("kWh", "energy_meter"),
    ("ATS", "ats"),
    ("SPD", "surge_protector"),
    ("TR", "impulse_relay"),
)

_DESIGNATOR = re.compile(r"^([A-Z]{1,4})\d{1,3}(?:[.\-]\d{1,3})?$")


def _norm(text: str) -> str:
    """A box's text as the dictionary compares it: no spaces, Hebrew quote marks as plain ones, any case."""
    t = text.strip().replace("״", '"').replace("׳", "'").replace("’", "'")
    return re.sub(r"\s+", "", t).casefold()


@dataclass(frozen=True)
class SymbolClass:
    symbol_class: str
    family: str
    display_name_he: str
    billable: bool


CLASSES: tuple[SymbolClass, ...] = tuple(
    SymbolClass(c, f.family, name, f.billable) for f in FAMILIES for c, name in f.classes
)


@dataclass(frozen=True)
class ReferenceImage:
    symbol_class: str
    image_key: str  # `reference/<file>.png` in this package for curated crops; an S3 key for a tenant's own
    scope: str  # global, tenant, designer, drawing (03 §4.3)


@dataclass
class Library:
    """What stage 3 knows for one drawing: the classes, the abbreviations at the three levels, the examples."""

    classes: dict[str, SymbolClass]
    abbreviations: dict[str, str] = field(default_factory=dict)  # normalized text → symbol_class, levels applied
    written: dict[str, str] = field(default_factory=dict)  # normalized text → as the dictionary writes it
    references: list[ReferenceImage] = field(default_factory=list)
    version: str = ""

    @property
    def families(self) -> dict[str, list[SymbolClass]]:
        out: dict[str, list[SymbolClass]] = {}
        for c in self.classes.values():
            out.setdefault(c.family, []).append(c)
        return out

    def classify_text(self, text: str) -> SymbolClass | None:
        """03 §4.6: the class a box's text names, by the dictionary (exact, then letters of a designator)."""
        key = _norm(text)
        if not key:
            return None
        found = self.abbreviations.get(key)
        if found is None:
            letters = _DESIGNATOR.match(text.strip().upper())
            if letters:
                found = self.abbreviations.get(_norm(letters[1]))
        return self.classes.get(found) if found else None


def build(
    classes: list[SymbolClass],
    global_abbr: list[tuple[str, str]],
    tenant_abbr: list[tuple[str, str]] = (),  # type: ignore[assignment]
    designer_abbr: list[tuple[str, str]] = (),  # type: ignore[assignment]
    references: list[ReferenceImage] = (),  # type: ignore[assignment]
) -> Library:
    """The library from its parts; later levels win (03 §4.6). The version names what the model is shown.

    Classes and examples come out in this module's order whatever order the database returned them in (rows it
    doesn't know go last, by name): the prompt lists them, and its cassette key must not change between runs."""
    rank = {c.symbol_class: i for i, c in enumerate(CLASSES)}
    classes = sorted(classes, key=lambda c: (rank.get(c.symbol_class, len(rank)), c.symbol_class))
    references = sorted(references, key=lambda r: (rank.get(r.symbol_class, len(rank)), r.image_key))
    by_id = {c.symbol_class: c for c in classes}
    abbreviations: dict[str, str] = {}
    written: dict[str, str] = {}
    for level in (global_abbr, tenant_abbr, designer_abbr):
        for text, symbol_class in level:
            if symbol_class in by_id:
                abbreviations[_norm(text)] = symbol_class
                written[_norm(text)] = text.strip()
    material = {
        "classes": sorted((c.symbol_class, c.family, c.billable) for c in classes),
        "abbreviations": sorted(abbreviations.items()),
        "references": sorted((r.symbol_class, r.image_key, r.scope) for r in references),
    }
    digest = hashlib.sha256(json.dumps(material, ensure_ascii=False).encode()).hexdigest()[:10]
    return Library(by_id, abbreviations, written, list(references), f"lib-{digest}")


def default() -> Library:
    """The library straight from this module (tests, and a stand-in when the global rows aren't seeded)."""
    return build(list(CLASSES), list(ABBREVIATIONS), references=curated_references())


def curated_references() -> list[ReferenceImage]:
    from .reference import FILES  # the drawn examples (03 §12 cold start, S12 decision)

    return [ReferenceImage(symbol_class, f"reference/{name}", "global") for symbol_class, name in FILES]


def load(session: Session, designer: str | None) -> Library:
    """The library for one drawing, inside the tenant's session: global rows, then the tenant's abbreviations,
    then the designer's (RLS keeps other tenants' rows out)."""
    rows = session.execute(
        select(m.SymbolClass.id, m.SymbolClass.family, m.SymbolClass.display_name_he, m.SymbolClass.billable)
    ).all()
    if not rows:
        return default()
    classes = [SymbolClass(*r) for r in rows]
    global_abbr = [
        (t, c) for t, c in session.execute(select(m.Abbreviation.text, m.Abbreviation.symbol_class)) if c is not None
    ]
    tenant_rows = session.execute(
        select(
            m.TenantAbbreviation.scope,
            m.TenantAbbreviation.designer,
            m.TenantAbbreviation.text,
            m.TenantAbbreviation.symbol_class,
        )
    ).all()
    tenant_abbr = [(t, c) for scope, _, t, c in tenant_rows if scope == "tenant" and c]
    designer_abbr = [(t, c) for scope, d, t, c in tenant_rows if scope == "designer" and d and d == designer and c]
    refs = [
        ReferenceImage(c, key, "global")
        for c, key in session.execute(select(m.ReferenceCrop.symbol_class, m.ReferenceCrop.image_key))
    ]
    return build(classes, global_abbr, tenant_abbr, designer_abbr, refs)
