"""`explain_line`'s code (08 §6.4, S25b): the trace without money, what was filled in, and the citation check."""

from konboro.chat.explain import check, filled_in, scrub, trace
from konboro_llm.stages.line_explanation import Cites, Focus, LineExplanation

DETAILS = {
    "line": "L3",
    "description": 'מא"ז 3P 16A',
    "unit_price": "$T1",
    "line_total": "$T2",
    "values": [
        {"attribute": "current_a", "value": "16", "source": "drawing", "confidence": 0.95},
        {"attribute": "breaking_capacity_ka", "value": "10", "source": "tenant_default", "confidence": None},
        {"attribute": "curve", "value": None, "source": "missing", "confidence": None},
        {"attribute": "poles", "value": "3", "source": "user", "confidence": None},
    ],
    "drawing_content": {"designators": ["F22"], "text_beside_it": ["F22", "3X16A"]},
    "price_trace": {"unit_price": "$T1", "source": {"kind": "markup"}},
    "status_reasons": [{"source": "price", "value": "ok", "status": "green"}],
    "refs": ["$T3", "keep"],
}


def test_the_trace_has_no_money_and_names_the_instances_and_texts():
    out, spans = trace(DETAILS, [("I1", 8, True), ("I2", 9, False)])
    text = str(out)
    assert "$T" not in text and "price_trace" not in out and "unit_price" not in out and "line_total" not in out
    assert out["refs"] == ["keep"]
    assert spans == ["S1", "S2"]
    assert out["drawing_content"]["text_beside_it"] == [{"span": "S1", "text": "F22"}, {"span": "S2", "text": "3X16A"}]
    assert out["instances"] == [
        {"instance": "I1", "page_no": 8, "in_image": True},
        {"instance": "I2", "page_no": 9, "in_image": False},
    ]
    assert out["status_reasons"] == DETAILS["status_reasons"]  # a colour's reason has no amount
    assert scrub("$P1") is None and scrub("$ ok") == "$ ok"


def test_what_was_filled_in_is_listed_and_what_was_read_or_set_is_not():
    assert filled_in(DETAILS) == [{"attribute": "breaking_capacity_ka", "value": "10", "source": "tenant_default"}]


def test_citations_it_was_not_given_are_dropped():
    answer = LineExplanation(
        answer="x",
        cites=Cites(line_ids=["L3", "l3", "L9"], instance_ids=["i1", "I7"], span_ids=["S2", "S9"]),
        focus=Focus(instance_ids=["I7", "I1"]),
        confidence=0.7,
        trace_supported=True,
    )
    got = check(answer, {"L3"}, {"I1", "I2"}, {"S1", "S2"})
    assert got.answer.cites == Cites(line_ids=["L3"], instance_ids=["I1"], span_ids=["S2"])
    assert got.answer.focus.instance_ids == ["I1"]
    assert sorted(got.invalid) == ["I7", "I7", "L9", "S9"]
