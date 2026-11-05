"""25.26.100's main panel from a third live run on the fix-25-26-100-main-panel branch (dev
`drw_01M6NFV83V6MQMWTVVMSFW6ZMD`, real Claude). Stage 3's stored detections are replayed through its code after the
model, and stage 4 runs without the tile agent, as `test_plan_25_26_100_live.py` does.

On that run the "1×10AC" breaker was read as a contactor's power contact (0.504) and, with no value of its own, made
one component with the real contactor C130,131's coil: a contactor × 2 and no 1P 10A breaker.
"""

from pathlib import Path

from konboro.contracts.merge import Component

from .test_matching import run
from .test_plan_25_26_100 import replay

DETECTIONS, COMPONENTS = replay(Path(__file__).parent / "fixtures" / "plan_25_26_100_live2")


def _value(c: Component, name: str) -> object:
    a = c.attributes.get(name)
    return a.value if a else None


def test_1x10ac_read_as_a_contactor_is_an_mcb_1p_10a_curve_c() -> None:
    """Rule 2b on an unsure contactor (the parent session's point 2): a curve written on a rating says a breaker
    unless the class reading is sure. It is then a device of its own, not the contactor's drawing."""
    det = next(d for d in DETECTIONS if d.det_id == "det_001_0032")
    assert (det.family, det.symbol_class, det.role) == ("circuit_breaker", "mcb", "device")
    ac = next(c for c in COMPONENTS if "det_001_0032" in c.source_det_ids)
    assert "1×10AC" in ac.explicit_texts
    assert (ac.family, ac.quantity) == ("circuit_breaker", 1)
    assert (_value(ac, "current_a"), _value(ac, "poles"), _value(ac, "curve")) == (10, 1, "C")
    assert run(ac)[0].chosen_sku == "S201M-C10"


def test_the_contactor_is_one() -> None:
    """Two untagged contactor drawings with nothing read on either have one signature, so they joined (04 §5.8): the
    breaker misread as a power contact and the real contactor's coil. With the breaker a breaker, one is left."""
    contactors = [c for c in COMPONENTS if c.family == "contactor"]
    assert [(c.quantity, c.source_det_ids) for c in contactors] == [(1, ["det_001_0062"])]
