"""08 §8.2: the answer check, in code."""

from decimal import Decimal

import pytest

from konboro.chat.check import amounts_in, check, for_model, strip_amounts, valid_lines
from konboro.chat.state import ChatState


def state() -> ChatState:
    s = ChatState()
    s.name("line", "ln_A")  # L1
    s.name("line", "ln_B")  # L2
    s.ref(Decimal("1250.50"))  # $T1
    return s


def test_line_names_become_ids_and_unknown_ones_are_removed():
    out = check("ראה {{line:L1}} ו-{{line:L9}} ו-{{line:L2}}", state(), {"ln_A"})
    assert out.text == "ראה {{line:ln_A}} ו- ו-"
    assert out.line_ids == ["ln_A"]
    assert out.invalid_refs == ["{{line:L9}}", "{{line:L2}}"]  # L2 is no longer in the quote


def test_money_refs_stay_and_unknown_ones_become_a_dash():
    out = check("סך הלוח: {{$T1}}, ההפרש {{$T7}}", state(), set())
    assert out.text == "סך הלוח: {{$T1}}, ההפרש —"
    assert out.money_refs == {"$T1"} and out.invalid_refs == ["{{$T7}}"]


@pytest.mark.parametrize(
    "text",
    [
        "סך הכול ₪1,250.50",
        'המחיר 1250 ש"ח',
        "עולה 480 שקל",
        "זה 3 אלף שקל",
        "הסכום 1,250.00",
        "מחיר ליחידה 12.40",
        "אלף ומאתיים שקל",
        "NIS 300",
    ],
)
def test_amounts_written_as_numbers_are_found(text: str):
    assert amounts_in(text), text
    assert not amounts_in(strip_amounts(text)), strip_amounts(text)


@pytest.mark.parametrize(
    "text",
    [
        'יש 12 שורות מא"ז בלוח B1',
        'מא"ז 3X16A עקומה C',
        "כושר ניתוק 6kA, 10kA",
        "4 מפסקי פחת 30mA",
        "סך הלוח: {{$T1}}",
        "הנחה של 5% כפי שביקשת",
        "גרסה 2 מול גרסה 1",
        'פס 1.5 מ"מ',
    ],
)
def test_quantities_currents_and_refs_are_not_amounts(text: str):
    assert amounts_in(text) == [], text


def test_ui_lines_that_do_not_exist_are_dropped():
    s = state()
    assert valid_lines(["L1", "L2", "L5", "x"], s, {"ln_A"}) == ["ln_A"]


def test_names_of_another_kind_do_not_resolve():
    s = state()
    s.name("panel", "pnl_1")  # B1
    assert s.real("B1", "line") is None and s.real("B1", "panel") == "pnl_1"
    assert s.real("l1", "line") == "ln_A"  # the model's case doesn't matter


def test_the_same_amount_keeps_its_reference_and_state_round_trips():
    s = state()
    assert s.ref(Decimal("1250.5")) == "$T1"
    assert s.ref(Decimal("18.5"), "pct") == "$P1"
    assert s.ref(None) is None
    again = ChatState.load(s.dump())
    assert again.ref(Decimal("1250.50")) == "$T1" and again.name("line", "ln_B") == "L2"
    assert again.resolve({"$T1", "$X9"}) == {"$T1": {"kind": "ils", "value": "1250.5"}}


def test_quote_and_instance_names_become_ids_for_the_screen():
    state = ChatState()
    q = state.name("quote", "quo_01ABC")
    i = state.name("instance", "ins_01XYZ")
    assert (q, i) == ("QT1", "I1")
    out = check("מול {{quote:QT1}} ו-{{quote:QT4}}, ברכיב {{instance:I1}} {{instance:I2}}", state, set())
    assert out.text == "מול {{quote:quo_01ABC}} ו-, ברכיב {{instance:ins_01XYZ}}"
    assert out.quote_ids == ["quo_01ABC"] and out.instance_ids == ["ins_01XYZ"]
    assert sorted(out.invalid_refs) == ["{{instance:I2}}", "{{quote:QT4}}"]


def test_an_instance_the_turn_did_not_locate_is_removed():
    state = ChatState()
    state.name("instance", "ins_01OLD")
    out = check("{{instance:I1}}", state, set(), live_instances={"ins_01NEW"})
    assert out.text == "" and out.invalid_refs == ["{{instance:I1}}"]


def test_a_reference_the_screen_sent_back_is_named_again_for_the_model():
    state = ChatState()
    state.name("quote", "quo_01ABC")
    state.name("line", "ln_01DEF")
    text = "תשווה ל-{{quote:quo_01ABC}} ול-{{line:ln_01DEF}} ול-{{quote:quo_01ZZZ}}"
    assert for_model(text, state) == "תשווה ל-{{quote:QT1}} ול-{{line:L1}} ול-"
    assert state.alias_of("quo_01ZZZ") is None  # never named by the model's side, never given a name here
