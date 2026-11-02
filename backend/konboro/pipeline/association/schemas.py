"""05 §4.4: per family, the attributes that define a product, as data. Stage 4 reads these attributes from the drawing,
stage 5 matches on them, with the same definition (04 §4.2).

This module is the source of the global rows: `seed_global` writes `SCHEMAS` into `attribute_schemas`, and stage 4
reads them back (`load`). A starter set, until the electrical expert reviews them (05 §13 item 3, roadmap B2).

`current_a` and `poles` never allow a default (05 §4.4, CLAUDE.md non-negotiable 4).
"""

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.db import models as m

MatchMode = Literal["exact", "gte", "lte", "prefer"]
NEVER_DEFAULT = frozenset({"current_a", "poles"})


@dataclass(frozen=True)
class Attribute:
    name: str
    required: bool
    match_mode: MatchMode
    default_allowed: bool

    def as_row(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "required": self.required,
            "match_mode": self.match_mode,
            "default_allowed": self.default_allowed,
        }


def _a(name: str, required: bool = False, mode: MatchMode = "exact", default: bool = False) -> Attribute:
    return Attribute(name, required, mode, default and name not in NEVER_DEFAULT)


_CURRENT = _a("current_a", True)
_POLES = _a("poles", True)
_NEUTRAL = _a("neutral")
_COIL = _a("coil_voltage_v", mode="exact", default=True)

SCHEMAS: dict[str, tuple[Attribute, ...]] = {
    "circuit_breaker": (
        _CURRENT,
        _POLES,
        _a("curve", True, default=True),
        _a("breaking_capacity_ka", True, "gte", default=True),
        _NEUTRAL,
        _a("setting_a", mode="prefer"),
        _a("trip_unit"),
        _a("range_min_a"),
        _a("range_max_a"),
    ),
    "rcd": (
        _CURRENT,
        _POLES,
        _a("residual_ma", True, default=True),
        _a("rcd_type", True, "gte", default=True),
        _NEUTRAL,
    ),
    "rcbo": (
        _CURRENT,
        _POLES,
        _a("curve", True, default=True),
        _a("residual_ma", True, default=True),
        _a("breaking_capacity_ka", True, "gte", default=True),
        _a("rcd_type", True, "gte", default=True),
        _NEUTRAL,
    ),
    "switch_disconnector": (_CURRENT, _POLES, _NEUTRAL),
    "changeover_switch": (_CURRENT, _POLES),
    "ats": (_CURRENT, _POLES),
    "fuse": (_CURRENT, _a("poles")),
    "contactor": (_CURRENT, _POLES, _COIL),
    "overload_relay": (_a("range_min_a", True), _a("range_max_a", True)),
    "relay": (_COIL,),
    "relay_coil": (_COIL,),
    "timer": (_COIL,),
    "voltage_relay": (_COIL,),
    "impulse_relay": (_COIL,),
    "time_switch": (_COIL,),
    "shunt_trip": (_COIL,),
    "temperature_controller": (),
    "surge_protector": (_POLES, _a("imax_ka", True, "gte"), _a("spd_class", mode="exact", default=True)),
    "energy_meter": (),
    "measuring_instrument": (),
    "current_transformer": (_a("ratio_primary_a", True), _a("ratio_secondary_a", True, default=True)),
    "indicator_lamp": (_a("color", mode="prefer"), _a("coil_voltage_v", mode="exact", default=True)),
    "push_button": (_a("color", mode="prefer"),),
    "selector_switch": (_a("positions", mode="prefer"),),
    "terminal": (_a("cross_section_mm2", mode="gte"),),
    "aux_contact": (_a("contacts", mode="prefer"),),
    "socket_outlet": (_CURRENT, _POLES, _NEUTRAL, _a("socket_standard", True, default=True)),
}


@dataclass(frozen=True)
class Schemas:
    by_family: dict[str, tuple[Attribute, ...]]

    def attributes(self, family: str) -> tuple[Attribute, ...]:
        return self.by_family.get(family, ())

    def names(self, family: str) -> tuple[str, ...]:
        return tuple(a.name for a in self.attributes(family))

    def must_read(self, family: str) -> tuple[str, ...]:
        """Required and never filled in later: what makes a symbol "resolved" (04 §5.2 item 4, S13 decision)."""
        return tuple(a.name for a in self.attributes(family) if a.required and not a.default_allowed)

    def required(self, family: str) -> tuple[str, ...]:
        return tuple(a.name for a in self.attributes(family) if a.required)


def default() -> Schemas:
    return Schemas(dict(SCHEMAS))


def _from_row(row: dict[str, Any]) -> Attribute:
    return _a(row["name"], bool(row.get("required")), row.get("match_mode", "exact"), bool(row.get("default_allowed")))


def load(session: Session) -> Schemas:
    """The global schemas, from the database, in this module's order of families; a family with no row there keeps
    this module's."""
    rows: dict[str, list[Any]] = dict(
        session.execute(select(m.AttributeSchema.family, m.AttributeSchema.attributes)).all()
    )
    by_family = {
        family: tuple(_from_row(r) for r in rows[family]) if family in rows else attrs
        for family, attrs in SCHEMAS.items()
    }
    by_family.update({f: tuple(_from_row(r) for r in v) for f, v in sorted(rows.items()) if f not in by_family})
    return Schemas(by_family)
