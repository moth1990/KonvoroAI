"""The curated reference symbols (03 §4.3 `source` = `curated`, scope `global`), drawn by us
(`konboro.devtools.draw_symbols`, S12 decision). One or two per class: (symbol_class, file in this folder)."""

from pathlib import Path

DIR = Path(__file__).resolve().parent

FILES: tuple[tuple[str, str], ...] = (
    ("mcb", "mcb.png"),
    ("mccb", "mccb.png"),
    ("motor_protection", "motor_protection.png"),
    ("rcd", "rcd.png"),
    ("rcbo", "rcbo.png"),
    ("switch_disconnector", "switch_disconnector.png"),
    ("fuse", "fuse.png"),
    ("fuse_base", "fuse_base.png"),
    ("contactor", "contactor.png"),
    ("contactor", "contactor_coil.png"),
    ("relay", "relay.png"),
    ("timer", "timer.png"),
    ("overload_relay", "overload_relay.png"),
    ("surge_protector", "surge_protector.png"),
    ("energy_meter", "energy_meter.png"),
    ("current_transformer", "current_transformer.png"),
    ("ats", "ats.png"),
    ("indicator_lamp", "indicator_lamp.png"),
    ("push_button", "push_button.png"),
    ("emergency_button", "emergency_button.png"),
    ("selector_switch", "selector_switch.png"),
    ("measuring_instrument", "measuring_instrument.png"),
    ("terminal", "terminal.png"),
    ("aux_contact", "aux_contact.png"),
    ("relay_coil", "relay_coil.png"),
    ("temperature_controller", "temperature_controller.png"),
    ("voltage_relay", "voltage_relay.png"),
    ("shunt_trip", "shunt_trip.png"),
    ("impulse_relay", "impulse_relay.png"),
    ("time_switch", "time_switch.png"),
    ("socket_outlet", "socket_outlet.png"),
    ("changeover_switch", "changeover_switch.png"),
    ("busbar", "busbar.png"),
    ("ground", "ground.png"),
    ("motor_load", "motor_load.png"),
    ("junction", "junction.png"),
)


def path(image_key: str) -> Path:
    """`reference/<file>` → the file here."""
    return DIR / image_key.removeprefix("reference/")
