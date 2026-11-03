"""The Hebrew stage 5 writes for the review screen (05 §6.2 `reason`, §5.9 the alternatives' difference, §8 messages):
item descriptions, attribute names and values, and what differs between two items. Text only; nothing here decides.
"""

from typing import Any

from ..detection import library

# 05 §8's attribute names, as the line shows them ("עקומה C: ברירת מחדל")
NAMES = {
    "current_a": "זרם",
    "poles": "קטבים",
    "curve": "עקומה",
    "breaking_capacity_ka": "כושר ניתוק",
    "neutral": "אפס",
    "residual_ma": "זרם זליגה",
    "rcd_type": "סוג פחת",
    "trip_unit": "יחידת הגנה",
    "range_min_a": "תחום כיול",
    "range_max_a": "תחום כיול",
    "setting_a": "כיול",
    "contacts": "מגעים",
    "coil_voltage_v": "מתח סליל",
    "color": "צבע",
    "positions": "מצבים",
    "ratio_primary_a": "יחס השנאה",
    "ratio_secondary_a": "יחס השנאה",
    "imax_ka": "זרם פריקה",
    "spd_class": "דרגה",
    "socket_standard": "תקן",
    "cross_section_mm2": "חתך",
}
UNITS = {
    "current_a": "A",
    "breaking_capacity_ka": "kA",
    "residual_ma": "mA",
    "range_min_a": "A",
    "range_max_a": "A",
    "setting_a": "A",
    "coil_voltage_v": "V",
    "ratio_primary_a": "A",
    "ratio_secondary_a": "A",
    "imax_ka": "kA",
    "cross_section_mm2": "mm²",
}
COLOURS = {"green": "ירוקה", "red": "אדומה", "yellow": "צהובה", "blue": "כחולה", "white": "לבנה"}
SOURCES = {
    "notes": "ההערות בשרטוט",
    "tenant_default": "ברירת המחדל של המפעל",
    "system_default": "ברירת המחדל של המערכת",
    "series": "הדגם",
    "inferred": "המעגל",
}


def number(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def value(name: str, v: Any) -> str:
    """ "16A", "6kA", "C", "3P", "ירוקה" """
    if v is None:
        return "—"
    if name == "poles":
        return f"{number(v)}P"
    if name == "neutral":
        return "+N" if v else "בלי N"
    if name == "color":
        return COLOURS.get(str(v), str(v))
    return f"{number(v)}{UNITS.get(name, '')}"


def class_name(family: str, symbol_class: str | None) -> str:
    """The Hebrew name of the class, or of the family's first class (the library's display names, 03 §4.3)."""
    for f in library.FAMILIES:
        if f.family == family:
            names = dict(f.classes)
            return names.get(symbol_class or "", f.classes[0][1])
    return family


def describe(family: str, symbol_class: str | None, brand: str, model: str | None, attrs: dict[str, Any]) -> str:
    """'מא"ז ABB S203M 3P 16A עקומה C 10kA', the shape of the demo price list's names (S18)."""
    parts = [class_name(family, symbol_class), brand]
    if model:
        parts.append(model)
    poles = attrs.get("poles")
    if poles is not None:
        parts.append(f"{number(poles)}P" + ("+N" if attrs.get("neutral") else ""))
    for name in ("current_a", "residual_ma", "imax_ka", "coil_voltage_v"):
        if attrs.get(name) is not None:
            parts.append(value(name, attrs[name]))
    if attrs.get("range_min_a") is not None and attrs.get("range_max_a") is not None:
        parts.append(f"{number(attrs['range_min_a'])}–{number(attrs['range_max_a'])}A")
    if attrs.get("ratio_primary_a") is not None:
        parts.append(f"{number(attrs['ratio_primary_a'])}/{number(attrs.get('ratio_secondary_a', 5))}A")
    if attrs.get("curve"):
        parts.append(f"עקומה {attrs['curve']}")
    if attrs.get("rcd_type"):
        parts.append(f"סוג {attrs['rcd_type']}")
    if attrs.get("breaking_capacity_ka") is not None:
        parts.append(value("breaking_capacity_ka", attrs["breaking_capacity_ka"]))
    for name in ("trip_unit", "spd_class", "socket_standard", "contacts", "positions"):
        if attrs.get(name):
            parts.append(str(attrs[name]))
    if attrs.get("color"):
        parts.append(value("color", attrs["color"]))
    return " ".join(parts)


def difference(chosen: Any, other: Any, names: tuple[str, ...]) -> str:
    """05 §5.9: what the alternative changes, e.g. "Schneider במקום ABB", "10kA במקום 6kA"; "אותן תכונות"."""
    out: list[str] = []
    if other.brand != chosen.brand:
        out.append(f"{other.brand} במקום {chosen.brand}")
    elif other.series != chosen.series and other.series and chosen.series:
        out.append(f"סדרה {other.series} במקום {chosen.series}")
    for name in names:
        a, b = chosen.attributes.get(name), other.attributes.get(name)
        if a != b and b is not None:
            out.append(
                f"{value(name, b)} במקום {value(name, a)}"
                if a is not None
                else f"{NAMES.get(name, name)} {value(name, b)}"
            )
    if not out:
        return "אותן תכונות"
    if len(out) == 1 and other.brand != chosen.brand:
        return f"{out[0]}, אותן תכונות"
    return ", ".join(out)
