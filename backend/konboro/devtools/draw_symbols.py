"""Draws the curated reference symbols (S12 decision: our own IEC 60617-style drawings, nothing cut from the golden
set, 00 §10.1) into `konboro/pipeline/detection/reference/`. Run it after changing a drawing, and commit the PNGs:

    uv run python -m konboro.devtools.draw_symbols

Each symbol is drawn on a vertical line, top to bottom, the way single-line diagrams draw them, at 128 px. A new
drawing changes what the model is shown, so the eval cassettes of `symbol_detection` are recorded again.
"""

import math
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from konboro.pipeline.detection.reference import DIR, FILES

S = 128  # px
W = 3  # line width
C = S // 2  # the line's x


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def _line(d: ImageDraw.ImageDraw, *pts: tuple[float, float], width: int = W) -> None:
    d.line(list(pts), fill="black", width=width)


def _text(d: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, size: int = 18) -> None:
    d.text(xy, text, fill="black", font=_font(size), anchor="mm")


def _blade(d: ImageDraw.ImageDraw) -> None:
    """The open contact: line in from the top, a slanted blade, line out to the bottom."""
    _line(d, (C, 0), (C, 44))
    _line(d, (C, 84), (C, S))
    _line(d, (C, 84), (C - 22, 46))


def breaker(d: ImageDraw.ImageDraw) -> None:
    _blade(d)
    _line(d, (C - 7, 37), (C + 7, 51))
    _line(d, (C - 7, 51), (C + 7, 37))
    d.arc((C - 6, 92, C + 12, 108), 90, 270, fill="black", width=2)  # the thermal release, on most breakers


def mccb(d: ImageDraw.ImageDraw) -> None:
    breaker(d)
    d.rectangle((C + 10, 56, C + 34, 80), outline="black", width=2)  # the trip unit
    _line(d, (C, 68), (C + 10, 68), width=2)


def motor_protection(d: ImageDraw.ImageDraw) -> None:
    breaker(d)
    _text(d, (C + 34, 66), "PKZM", 14)  # told apart by what is written, not by the drawing


def rcd(d: ImageDraw.ImageDraw) -> None:
    _blade(d)
    _line(d, (C - 4, 42), (C + 4, 42))
    d.ellipse((C - 18, 92, C + 18, 108), outline="black", width=2)
    _text(d, (C + 42, 100), "30mA", 14)


def rcbo(d: ImageDraw.ImageDraw) -> None:
    breaker(d)
    d.ellipse((C - 18, 92, C + 18, 108), outline="black", width=2)


def switch_disconnector(d: ImageDraw.ImageDraw) -> None:
    _blade(d)
    _line(d, (C - 9, 44), (C + 9, 44))
    d.ellipse((C - 4, 40, C + 4, 48), outline="black", width=2)


def fuse(d: ImageDraw.ImageDraw) -> None:
    _line(d, (C, 0), (C, S))
    d.rectangle((C - 12, 36, C + 12, 92), outline="black", width=W)


def fuse_base(d: ImageDraw.ImageDraw) -> None:
    fuse(d)
    _line(d, (C - 20, 30), (C + 20, 30), width=2)
    _line(d, (C - 20, 98), (C + 20, 98), width=2)


def contactor(d: ImageDraw.ImageDraw) -> None:
    _blade(d)
    d.arc((C - 8, 36, C + 8, 52), 180, 360, fill="black", width=W)


def coil(label: str) -> Callable[[ImageDraw.ImageDraw], None]:
    def draw(d: ImageDraw.ImageDraw) -> None:
        _line(d, (C, 0), (C, 40))
        _line(d, (C, 88), (C, S))
        d.rectangle((C - 30, 40, C + 30, 88), outline="black", width=W)
        _text(d, (C, 64), label, 20)

    return draw


def timer(d: ImageDraw.ImageDraw) -> None:
    coil("KT")(d)
    for x in range(C - 30, C - 14, 5):  # the hatched side of a time relay's coil
        _line(d, (x, 40), (x, 88), width=1)


def overload_relay(d: ImageDraw.ImageDraw) -> None:
    _line(d, (C, 0), (C, 40))
    _line(d, (C, 88), (C, S))
    d.rectangle((C - 26, 40, C + 26, 88), outline="black", width=W)
    _line(d, (C, 40), (C, 52), (C - 10, 52), (C - 10, 76), (C, 76), (C, 88), width=2)


def surge_protector(d: ImageDraw.ImageDraw) -> None:
    _line(d, (C, 0), (C, 36))
    d.rectangle((C - 14, 36, C + 14, 84), outline="black", width=W)
    _line(d, (C, 44), (C, 72), width=2)
    d.polygon([(C - 5, 64), (C + 5, 64), (C, 74)], fill="black")
    _line(d, (C, 84), (C, 104))
    for i, half in enumerate((18, 12, 6)):
        _line(d, (C - half, 104 + 6 * i), (C + half, 104 + 6 * i), width=2)


def box(label: str, size: int = 18) -> Callable[[ImageDraw.ImageDraw], None]:
    def draw(d: ImageDraw.ImageDraw) -> None:
        _line(d, (C, 0), (C, 38))
        _line(d, (C, 90), (C, S))
        d.rectangle((C - 40, 38, C + 40, 90), outline="black", width=W)
        _text(d, (C, 64), label, size)

    return draw


def current_transformer(d: ImageDraw.ImageDraw) -> None:
    _line(d, (C, 0), (C, S))
    d.ellipse((C - 16, 48, C + 16, 80), outline="black", width=W)
    _text(d, (C + 38, 64), "/5A", 14)


def indicator_lamp(d: ImageDraw.ImageDraw) -> None:
    _line(d, (C, 0), (C, 44))
    _line(d, (C, 84), (C, S))
    d.ellipse((C - 20, 44, C + 20, 84), outline="black", width=W)
    k = 20 / math.sqrt(2)
    _line(d, (C - k, 64 - k), (C + k, 64 + k), width=2)
    _line(d, (C - k, 64 + k), (C + k, 64 - k), width=2)


def push_button(d: ImageDraw.ImageDraw) -> None:
    _line(d, (C, 0), (C, 44))
    _line(d, (C, 84), (C, S))
    _line(d, (C, 84), (C - 20, 48))
    for y in range(52, 70, 6):  # the dashed actuator
        _line(d, (C - 14 - (y - 52), 66), (C - 18 - (y - 52), 66), width=2)
    _line(d, (C - 40, 56), (C - 40, 76))
    _line(d, (C - 40, 66), (C - 12, 66), width=1)


def emergency_button(d: ImageDraw.ImageDraw) -> None:
    push_button(d)
    d.arc((C - 52, 52, C - 32, 80), 90, 270, fill="black", width=W)


def selector_switch(d: ImageDraw.ImageDraw) -> None:
    _line(d, (C, 0), (C, 40))
    for x, label in ((C - 28, "1"), (C, "0"), (C + 28, "2")):
        d.ellipse((x - 4, 92, x + 4, 100), outline="black", width=2)
        _text(d, (x, 112), label, 14)
    _line(d, (C, 40), (C - 28, 92))


def measuring_instrument(d: ImageDraw.ImageDraw) -> None:
    _line(d, (C, 0), (C, 40))
    _line(d, (C, 88), (C, S))
    d.ellipse((C - 24, 40, C + 24, 88), outline="black", width=W)
    _text(d, (C, 64), "A", 22)


def terminal(d: ImageDraw.ImageDraw) -> None:
    _line(d, (C, 0), (C, 56))
    d.ellipse((C - 8, 56, C + 8, 72), outline="black", width=W)
    _line(d, (C - 10, 74), (C + 10, 54), width=2)


def aux_contact(d: ImageDraw.ImageDraw) -> None:
    _line(d, (C, 0), (C, 44))
    _line(d, (C, 84), (C, S))
    _line(d, (C, 84), (C - 20, 50))
    _text(d, (C + 22, 40), "13", 14)
    _text(d, (C + 22, 90), "14", 14)
    for x in range(C - 60, C - 14, 8):
        _line(d, (x, 66), (x + 4, 66), width=2)


def impulse_relay(d: ImageDraw.ImageDraw) -> None:
    _line(d, (C, 0), (C, 40))
    _line(d, (C, 88), (C, S))
    d.rectangle((C - 30, 40, C + 30, 88), outline="black", width=W)
    _line(d, (C - 16, 76), (C - 4, 76), (C - 4, 54), (C + 16, 54), width=2)


def time_switch(d: ImageDraw.ImageDraw) -> None:
    _line(d, (C, 0), (C, 38))
    _line(d, (C, 90), (C, S))
    d.rectangle((C - 34, 38, C + 34, 90), outline="black", width=W)
    d.ellipse((C - 18, 46, C + 18, 82), outline="black", width=2)
    _line(d, (C, 64), (C, 52), width=2)
    _line(d, (C, 64), (C + 10, 64), width=2)


def socket_outlet(d: ImageDraw.ImageDraw) -> None:
    _line(d, (C, 0), (C, 60))
    d.arc((C - 26, 60, C + 26, 112), 180, 360, fill="black", width=W)
    _line(d, (C - 26, 86), (C + 26, 86))
    _text(d, (C, 104), "CEE", 14)


def changeover_switch(d: ImageDraw.ImageDraw) -> None:
    _line(d, (C - 24, 0), (C - 24, 44))
    _line(d, (C + 24, 0), (C + 24, 44))
    _line(d, (C, 84), (C, S))
    _line(d, (C, 84), (C - 24, 44))
    _text(d, (C - 24, 54), "I", 12)
    _text(d, (C + 24, 54), "II", 12)


def busbar(d: ImageDraw.ImageDraw) -> None:
    _line(d, (4, 40), (S - 4, 40), width=6)
    for x in (24, 64, 104):
        _line(d, (x, 40), (x, 110))


def ground(d: ImageDraw.ImageDraw) -> None:
    _line(d, (C, 0), (C, 64))
    for i, half in enumerate((30, 20, 10)):
        _line(d, (C - half, 64 + 12 * i), (C + half, 64 + 12 * i))


def motor_load(d: ImageDraw.ImageDraw) -> None:
    _line(d, (C, 0), (C, 40))
    d.ellipse((C - 26, 40, C + 26, 92), outline="black", width=W)
    _text(d, (C, 66), "M", 26)


def junction(d: ImageDraw.ImageDraw) -> None:
    _line(d, (C, 0), (C, S))
    _line(d, (C, C), (S, C))
    d.ellipse((C - 7, C - 7, C + 7, C + 7), fill="black")


DRAW: dict[str, Callable[[ImageDraw.ImageDraw], None]] = {
    "mcb": breaker,
    "mccb": mccb,
    "motor_protection": motor_protection,
    "rcd": rcd,
    "rcbo": rcbo,
    "switch_disconnector": switch_disconnector,
    "fuse": fuse,
    "fuse_base": fuse_base,
    "contactor": contactor,
    "contactor_coil": coil("C1"),
    "relay": coil("R1"),
    "timer": timer,
    "overload_relay": overload_relay,
    "surge_protector": surge_protector,
    "energy_meter": box("kWh"),
    "current_transformer": current_transformer,
    "ats": box("ATS"),
    "indicator_lamp": indicator_lamp,
    "push_button": push_button,
    "emergency_button": emergency_button,
    "selector_switch": selector_switch,
    "measuring_instrument": measuring_instrument,
    "terminal": terminal,
    "aux_contact": aux_contact,
    "relay_coil": coil("A1"),
    "temperature_controller": box("TH1"),
    "voltage_relay": box("NVR"),
    "shunt_trip": box("TC"),
    "impulse_relay": impulse_relay,
    "time_switch": time_switch,
    "socket_outlet": socket_outlet,
    "changeover_switch": changeover_switch,
    "busbar": busbar,
    "ground": ground,
    "motor_load": motor_load,
    "junction": junction,
}


def draw(name: str) -> Image.Image:
    image = Image.new("RGB", (S, S), "white")
    DRAW[name.removesuffix(".png")](ImageDraw.Draw(image))
    return image


def main() -> None:
    out = Path(DIR)
    for _, name in FILES:
        draw(name).save(out / name, "PNG", optimize=True)
    print(f"{len(FILES)} symbols in {out}")


if __name__ == "__main__":
    main()
