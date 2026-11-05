"""Product names as a BOM writes them → family and, when the name says it, the class (01 §5.8, 03 §4.6).

A BOM names products in words ("מא"ז", "פחת", "מגן מתח יתר", "שעון שבת") where a drawing has symbols. These are kept
apart from the drawing's abbreviation dictionary (`detection/library.py`): that one is shown to stage 3's model, and
a BOM's words would change its prompt on every drawing (S14 decision 6). A tenant's own BOM words are a later step
(roadmap backlog).

"מפסק" alone names the family only: its class (moulded case, MCB, disconnector) is decided by its current in stage 5
(05 §5.5.1), so the class stays unknown here.
"""

import re

UNTYPED = "unknown_symbol"  # the class is not written (library.UNKNOWN); stage 5 decides it

# (as written, family, class or None)
TERMS: tuple[tuple[str, str, str | None], ...] = (
    ('מא"ז משולב פחת', "rcbo", "rcbo"),
    ('מא"ז פחת', "rcbo", "rcbo"),
    ('מא"ז', "circuit_breaker", "mcb"),
    ("מאז", "circuit_breaker", "mcb"),
    ("מפסק זרם אוטומטי", "circuit_breaker", "mcb"),
    ("מפסק בתיבה יצוקה", "circuit_breaker", "mccb"),
    ("מפסק פחת", "rcd", "rcd"),
    ("מפסק עומס", "switch_disconnector", "switch_disconnector"),
    ("מפסק מגן מנוע", "circuit_breaker", "motor_protection"),  # the quote's own name for it (the user, 25.26.100)
    ("מפסק", "circuit_breaker", None),
    ("מנתק", "switch_disconnector", "switch_disconnector"),
    ("מגן מנוע", "circuit_breaker", "motor_protection"),
    ("הגנת מנוע", "circuit_breaker", "motor_protection"),
    ("פחת", "rcd", "rcd"),
    ("מ.פ.", "rcd", "rcd"),
    ("מגען", "contactor", "contactor"),
    ("ממסר פחת", "rcd", "rcd"),  # a residual-current relay: what factories call an RCD (BUG-056)
    ("ממסר פיקוד", "relay", "relay"),
    ("ממסר צעד", "impulse_relay", "impulse_relay"),
    ("ממסר זמן", "timer", "timer"),
    ("ממסר חוסר מתח", "voltage_relay", "voltage_relay"),
    ("ממסר תרמי", "overload_relay", "overload_relay"),
    ("ממסר", "relay", "relay"),
    ("מגן מתח יתר", "surge_protector", "surge_protector"),
    ("מגן ברק", "surge_protector", "surge_protector"),
    ("מגן נחשולים", "surge_protector", "surge_protector"),
    ("סליל הפסקה", "shunt_trip", "shunt_trip"),
    ("סליל ממסר", "relay_coil", "relay_coil"),
    ("משנה זרם", "current_transformer", "current_transformer"),
    ("רב מודד", "energy_meter", "energy_meter"),
    ("מונה", "energy_meter", "energy_meter"),
    ("מכשיר מדידה", "measuring_instrument", "measuring_instrument"),
    ("רב מד", "measuring_instrument", "measuring_instrument"),
    ("שעון שבת", "time_switch", "time_switch"),
    ("שעון פיקוד", "time_switch", "time_switch"),
    ("שעון אסטרונומי", "time_switch", "time_switch"),  # 25.26.100's quote 10298
    ("לחצן חירום", "push_button", "emergency_button"),
    ("לחצן", "push_button", "push_button"),
    ("נורית", "indicator_lamp", "indicator_lamp"),
    ("נורת סימון", "indicator_lamp", "indicator_lamp"),
    ("מנורה", "indicator_lamp", "indicator_lamp"),
    ("מנורת", "indicator_lamp", "indicator_lamp"),
    ("מגע עזר", "aux_contact", "aux_contact"),
    ("בקר טמפרטורה", "temperature_controller", "temperature_controller"),
    ("פסי צבירה", "busbar", "busbar"),
    ("פס צבירה", "busbar", "busbar"),
    ("בורר", "selector_switch", "selector_switch"),
    ("מנתק נתיך", "fuse", "fuse_base"),
    ("בסיס נתיך", "fuse", "fuse_base"),
    ("נתיך", "fuse", "fuse"),
    ("נתיכים", "fuse", "fuse"),
    ("שקע", "socket_outlet", "socket_outlet"),
    ("מהדק", "terminal", "terminal"),
    ("מהדקים", "terminal", "terminal"),
    ("מחליף", "changeover_switch", "changeover_switch"),
    ("טרמוסטט", "temperature_controller", "temperature_controller"),
    ("MCCB", "circuit_breaker", "mccb"),
    ("MCB", "circuit_breaker", "mcb"),
    ("RCBO", "rcbo", "rcbo"),
    ("RCD", "rcd", "rcd"),
    ("RCCB", "rcd", "rcd"),
    ("SPD", "surge_protector", "surge_protector"),
    ("ATS", "ats", "ats"),
    ("contactor", "contactor", "contactor"),
    ("breaker", "circuit_breaker", None),
    ("energy meter", "energy_meter", "energy_meter"),
    ("current transformer", "current_transformer", "current_transformer"),
    ("time switch", "time_switch", "time_switch"),
    ("push button", "push_button", "push_button"),
)


def norm(text: str) -> str:
    t = text.replace("״", '"').replace("׳", "'").replace("''", '"').replace("’", "'")
    return " ".join(t.split()).casefold()


_EDGE = r"[^\W\d_]|[\"']"  # a letter or a quote mark beside the term means it is part of another word; a digit doesn't
_COMPILED = [
    (re.compile(rf"(?<!{_EDGE}){re.escape(norm(w))}(?!{_EDGE})"), len(norm(w)), family, cls) for w, family, cls in TERMS
]


def families_in(text: str) -> list[tuple[str, str, int]]:
    """Every term in the text, left to right, the longest at each place and none inside another: (family, class,
    where it starts). For what a quote line includes ("כולל פסי צבירה", "+נתיכים", 11 §5.2 item 6)."""
    t = norm(text)
    found: list[tuple[int, int, str, str]] = []
    for pattern, length, family, cls in _COMPILED:
        for m in pattern.finditer(t):
            found.append((m.start(), m.start() + length, family, cls or UNTYPED))
    found.sort(key=lambda f: (f[0], -(f[1] - f[0])))
    out: list[tuple[str, str, int]] = []
    end = -1
    for start, stop, family, cls in found:
        if start >= end:
            out.append((family, cls, start))
            end = stop
    return out


def family_of(text: str) -> tuple[str, str] | None:
    """The family and class the row's text names: the term that comes first in the text, the longest at that
    place. None when no term is in it."""
    t = norm(text)
    best: tuple[int, int, str, str] | None = None
    for pattern, length, family, cls in _COMPILED:
        m = pattern.search(t)
        if m is None:
            continue
        key = (m.start(), -length)
        if best is None or key < (best[0], best[1]):
            best = (m.start(), -length, family, cls or UNTYPED)
    return (best[2], best[3]) if best else None
