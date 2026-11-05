"""25.26.100's main panel from a later live run on the fix-25-26-100-main-panel branch (dev
`drw_01M6N04DXXSXMHY28WX21YKGBV`, real Claude). Stage 3's stored detections are replayed through its code after the
model, and stage 4 runs without the tile agent.
The fixture keeps the main panel's spans and detections, as `fixtures/plan_25_26_100/` does.

The user's points on that run: the five 40A field breakers are one product (5 × 3P), four 10A breakers came out as
disconnectors, "1×10AC" is an MCB 1P 10A curve C, and the x2 10A breakers came out a contactor.
"""

from pathlib import Path

from konboro.contracts.merge import Component

from .test_matching import run
from .test_plan_25_26_100 import replay

DETECTIONS, COMPONENTS = replay(Path(__file__).parent / "fixtures" / "plan_25_26_100_live")


def _value(c: Component, name: str) -> object:
    a = c.attributes.get(name)
    return a.value if a else None


def _breakers(current: float) -> list[Component]:
    return [c for c in COMPONENTS if c.family == "circuit_breaker" and _value(c, "current_a") == current]


def test_the_five_40a_field_breakers_are_one_component() -> None:
    """BUG-088, the user: "they're all the same". Read mcb × 3 and mccb × 2 in one row with no sure symbol, they are
    one class (rule 3c), so one component. Their poles come from the tile agent's pole marks, which this replay does
    not run: `test_association.py::test_a_breaker_takes_the_poles_read_on_its_alike_peers` covers that part."""
    forties = _breakers(40)
    assert [(c.symbol_class, c.quantity) for c in forties] == [("mcb", 5)]


def test_no_10a_breaker_is_a_disconnector() -> None:
    """BUG-090: four 10A breakers in the 10A row were the disambiguation's `switch_disconnector` (0.6, `mcb` 0.7
    among their own candidates) in a row with no sure symbol, so rule 3 had no peer to follow."""
    assert not [c for c in COMPONENTS if c.family == "switch_disconnector"]


def test_1x10ac_is_an_mcb_1p_10a_curve_c() -> None:
    """BUG-091: a curve letter written on the rating says a breaker; the grammar reads "1×10AC"."""
    ac = next(c for c in COMPONENTS if "1×10AC" in c.explicit_texts)
    assert (ac.family, ac.symbol_class) == ("circuit_breaker", "mcb")
    assert (_value(ac, "current_a"), _value(ac, "poles"), _value(ac, "curve")) == (10, 1, "C")
    assert run(ac)[0].chosen_sku == "S201M-C10"


def test_the_x2_10a_breakers_are_breakers() -> None:
    """BUG-087: drawn like the 10A breakers beside them (the model's box starts higher, centred on the row), rated
    10A with "X2" beside it, read as an unsure contactor."""
    assert not [c for c in COMPONENTS if c.family == "contactor" and _value(c, "current_a") == 10]
    x2 = next(c for c in COMPONENTS if "det_001_0033" in c.source_det_ids)
    assert (x2.family, x2.symbol_class, _value(x2, "current_a")) == ("circuit_breaker", "mcb", 10)
    assert x2.quantity >= 2  # X2 is its count
    assert run(x2)[0].chosen_sku == "S201M-C10"  # its 3×1.5 cable gives the pole
