"""25.26.100's main panel (לוח ראשי, a designer's single-sheet plan; BUG-066 to BUG-072, S24b), from the dev run's
stored outputs (`drw_01M6JTD6P888QR919B5KM52EWX`): stage 1's page and panel, stage 2's spans and wire graph, stage
3's detections as the model left them. No golden file yet: the user checked the main panel only.

The fixture (`fixtures/plan_25_26_100/`) keeps the main panel's spans and detections; the title block, the notes and
the file name are left out. The test runs stage 3's code after the model (`s3_symbols.after_model`, with the end
circles first), stage 4 without the tile agent (geometric association, the wire graph's chains, the merge), and stage
5 on the sample catalog. The agent would add the poles drawn as marks; without it, the poles come from the cables.

What the user counts on the main panel: Q0 3×80A a switch or an MCCB, three current transformers T1–T3 (100/5A), two
RCDs 4×40A 30 mA type A, 23 16A breakers (6 + 3 in the socket fields with their x2 marks, 209–210, 230, 11 marked
X11, 250), the lighting fields' 10A breakers as one line, and no current transformer made of a breaker's end circle.
"""

import gzip
import json
import types
from collections import Counter
from pathlib import Path

from konboro.contracts.detection import ClassCandidate, Detection, DetectionResult
from konboro.contracts.extraction import ExtractionResult
from konboro.contracts.intake import IntakeResult
from konboro.contracts.merge import Component
from konboro.pipeline.association import schemas
from konboro.pipeline.association.merge import components
from konboro.pipeline.detection import evidence, library
from konboro.pipeline.detection.candidates import Candidate
from konboro.pipeline.detection.config import DEFAULT
from konboro.pipeline.stages import s3_symbols, s4_association

from .test_matching import run  # the sample catalog and the eval's factory

FIXTURE = Path(__file__).parent / "fixtures" / "plan_25_26_100"
LIB = library.default()


def _candidate(d: Detection) -> Candidate:
    c = Candidate(
        bbox=d.bbox,
        family=d.family,
        symbol_class=d.symbol_class,
        role=d.role,
        detector_score=d.detector_score or 0.0,
        class_score=d.class_score,
        method=d.method,
        tag=d.designator,  # the worst case: as if the model had read every tag code linked, "X2" included
        orientation=d.orientation,
        candidates=[(k.symbol_class, k.score) for k in d.class_candidates],
    )
    c.tile_id = d.det_id  # carries the detection back
    return c


def replay(fixture: Path = FIXTURE) -> tuple[list[Detection], list[Component]]:
    """Stage 3's code after the model, stage 4 without the tile agent, from a fixture folder's stored outputs."""
    body = json.loads(gzip.decompress((fixture / "stages.json.gz").read_bytes()))
    intake = IntakeResult.model_validate(body["intake"])
    pe = ExtractionResult.model_validate(body["extraction"]).pages[0]
    pd = DetectionResult.model_validate(body["detection"]).pages[0]
    wires = (fixture / "wires.json.gz").read_bytes()
    found, _ = evidence.absorb_end_circles([_candidate(d) for d in pd.detections])
    s3_symbols.after_model(found, pe.text_spans, LIB, DEFAULT)
    by_id = {d.det_id: d for d in pd.detections}
    dets = []
    for c in found:
        conf = round(min(1.0, c.confidence), 4)
        cls = LIB.classes.get(c.symbol_class)
        dets.append(
            by_id[c.tile_id].model_copy(
                update={
                    "family": c.family,
                    "symbol_class": c.symbol_class,
                    "role": c.role,
                    "billable": cls.billable if cls else by_id[c.tile_id].billable,
                    "designator": c.designator,
                    "designator_span_id": c.designator_span_id,
                    "confidence": conf,
                    "status": s3_symbols.status(conf, c.symbol_class, DEFAULT),
                    "class_candidates": [
                        ClassCandidate(symbol_class=s, score=round(v, 4)) for s, v in c.candidates[:3]
                    ],
                }
            )
        )
    ctx = types.SimpleNamespace(storage=types.SimpleNamespace(get=lambda tenant, key: wires), tenant_id="tnt_x")
    sch = schemas.default()
    work = s4_association.associate_page(
        ctx,  # type: ignore[arg-type]
        intake.pages[0],
        pe,  # no render: no tile agent
        pd.model_copy(update={"detections": dets}),
        1,
        sch,
        LIB,
        None,  # type: ignore[arg-type]
        [p.panel_id for p in intake.panels],
    )
    s4_association.chains([work])
    comps, _, _ = components(intake.drawing_id, work.built, sch)
    return dets, comps


DETECTIONS, COMPONENTS = replay()


def _value(c: Component, name: str) -> object:
    a = c.attributes.get(name)
    return a.value if a else None


def _qty(family: str, current: float | None = None) -> int:
    return sum(
        c.quantity for c in COMPONENTS if c.family == family and (current is None or _value(c, "current_a") == current)
    )


def test_no_breaker_end_circle_is_a_current_transformer() -> None:
    """BUG-068: 8 current transformers and about 70 terminals were circles at breakers' ends."""
    cts = [d for d in DETECTIONS if d.family == "current_transformer"]
    assert [d.designator for d in cts] == ["T1-T3"]
    assert Counter(d.family for d in DETECTIONS)["terminal"] <= 35  # the outlets at the lines' ends, and a few


def test_three_current_transformers_from_one_range() -> None:
    """BUG-069."""
    ct = next(c for c in COMPONENTS if c.family == "current_transformer")
    assert ct.designators == ["T1", "T2", "T3"] and ct.quantity == 3
    assert (_value(ct, "ratio_primary_a"), _value(ct, "ratio_secondary_a")) == (100, 5)
    assert run(ct)[0].chosen_sku == "CT4 100/5"  # a real product the sample catalog lacked (the user's approval)


def test_both_rcds() -> None:
    """BUG-066, BUG-068: the socket fields' "4×40A 0.03A A", lost into a terminal × 76."""
    rcds = [c for c in COMPONENTS if c.family == "rcd"]
    assert sum(c.quantity for c in rcds) == 2
    assert all((_value(c, "current_a"), _value(c, "poles"), _value(c, "residual_ma")) == (40, 4, 30) for c in rcds)


def test_twenty_three_16a_breakers_counted_by_their_marks() -> None:
    """BUG-066, BUG-067, BUG-070: x2 and X11 are counts; two breakers read as push buttons are breakers."""
    assert _qty("circuit_breaker", 16) == 23
    assert not any(t in ("X2", "X11") for c in COMPONENTS if c.family != "terminal" for t in c.designators)


def test_q0_is_a_moulded_case_breaker() -> None:
    """BUG-070: Q is a switching device or an MCCB; stage 5 matches it to one."""
    q0 = next(c for c in COMPONENTS if "Q0" in c.designators)
    assert (q0.family, q0.symbol_class, _value(q0, "current_a"), _value(q0, "poles")) == (
        "circuit_breaker",
        "mccb",
        80,
        3,
    )
    m = run(q0)[0]
    assert m.chosen_sku is not None and m.chosen_sku.startswith("XT1")


def test_the_10a_lighting_breakers_are_one_1p_line() -> None:
    """BUG-070, BUG-072: switch-disconnectors beside mcbs became mcbs; the 3×1.5 cable gives them one pole. The
    "1×10AC" breaker, read as a contactor here, is a breaker of its own by rule 2b (1P 10A curve C, its own line)."""
    ten = [
        c for c in COMPONENTS if c.family in ("circuit_breaker", "switch_disconnector") and _value(c, "current_a") == 10
    ]
    ac = [c for c in ten if "1×10AC" in c.explicit_texts]
    assert [(c.quantity, _value(c, "poles"), _value(c, "curve")) for c in ac] == [(1, 1, "C")]
    tens = [c for c in ten if c not in ac]
    assert len(tens) == 1 and tens[0].family == "circuit_breaker" and tens[0].quantity >= 11
    assert tens[0].circuit_context is not None and tens[0].circuit_context.cable is not None
    assert tens[0].circuit_context.cable.cores == 3
    m = run(tens[0])[0]
    assert m.chosen_sku == "S201M-C10" and m.attributes_used["poles"].source == "inferred"


def test_the_16a_breakers_take_their_poles_from_their_cables() -> None:
    """BUG-072: 3×2.5 to a socket is one pole; the kitchen's 5×2.5—ø20 is three."""
    sixteens = [c for c in COMPONENTS if c.family == "circuit_breaker" and _value(c, "current_a") == 16]
    skus: Counter[str | None] = Counter()
    for c in sixteens:
        skus[run(c)[0].chosen_sku] += c.quantity
    assert skus == {"S201M-C16": 22, "S203M-C16": 1}


def test_the_five_40a_field_breakers_are_mcbs() -> None:
    """BUG-077: one sure MCCB in the row spread to its peers, and the row came out MCCBs. MCBs and MCCBs are drawn
    alike, so the row stays one class (one line) and stage 5 types it by its current: no 40A MCCB here (S24b
    decision 14)."""
    forties = [c for c in COMPONENTS if c.family == "circuit_breaker" and _value(c, "current_a") == 40]
    assert len(forties) == 1 and forties[0].quantity == 5
    m = run(forties[0])[0]
    assert m.signature is not None and m.signature.startswith("circuit_breaker|mcb|")


def test_t1_is_the_clock_and_the_selector_stands_alone() -> None:
    """BUG-081: "T1" written beside the clock's box was linked to the selector and to C130,131's coil too, and the
    selector became T1's device ("בורר" × 2 tagged T1, no clock). A tag written beside symbols of different families
    names the nearest. The clock's class (timer, not time_switch) and the selector's two decks (× 2) are follow-ups."""
    t1 = [c for c in COMPONENTS if "T1" in c.designators and c.family != "current_transformer"]  # not "T1-T3"
    assert [(c.family, c.quantity) for c in t1] == [("timer", 1)]
    selectors = [c for c in COMPONENTS if c.family == "selector_switch"]
    assert selectors and not any(c.designators for c in selectors)
