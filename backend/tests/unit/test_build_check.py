"""The chat builder's code check (13 §4.2, S27 design 3): Hebrew numbers said in words, the model's items and changes
held to what the message says, and the build's rows (a line keeps its first row). No model is called."""

from decimal import Decimal

import pytest

from konboro.pipeline.association import bom, schemas
from konboro.pipeline.bom import chat, numbers, table
from konboro.pipeline.bom.chat import Change, Item

SCH = schemas.default()
SPOKEN = (
    "מפסק ראשי ארבע על שישים ושלוש, שנים עשר מא״ז אחד על שש עשרה, ארבעה מא״ז שלוש על עשרים וחמש, ופחת ארבע על ארבעים"
)


@pytest.mark.parametrize(
    ("said", "value"),
    [
        ("אחד", 1),
        ("אחת", 1),
        ("שתיים", 2),
        ("שניים", 2),
        ("שלושה", 3),
        ("שלושת", 3),
        ("עשר", 10),
        ("עשרה", 10),
        ("אחת עשרה", 11),
        ("שנים עשר", 12),
        ("שתים עשרה", 12),
        ("שש עשרה", 16),
        ("תשעה עשר", 19),
        ("עשרים", 20),
        ("עשרים וחמש", 25),
        ("שלושים ושתיים", 32),
        ("ארבעים", 40),
        ("שישים ושלוש", 63),
        ("מאה", 100),
        ("מאה ועשרים", 120),
        ("מאה עשרים וחמש", 125),
        ("מאה ושישים", 160),
        ("מאתיים חמישים", 250),
        ("ארבע מאות", 400),
        ("שש מאות שלושים", 630),
        ("שמונה מאות", 800),
        ("אלף", 1000),
        ("אלף ושש מאות", 1600),
        ("אלפיים וחמש מאות", 2500),
        ("לשש עשרה", 16),
        ("ושלושה", 3),
    ],
)
def test_a_number_said_in_words(said: str, value: int) -> None:
    assert [f.value for f in numbers.spoken(said)] == [value]


def test_the_prototypes_sentence_in_digits() -> None:
    assert numbers.in_digits(SPOKEN) == "מפסק ראשי 4 על 63, 12 מא״ז 1 על 16, 4 מא״ז 3 על 25, ופחת 4 על 40"


def test_two_numbers_side_by_side_stay_two() -> None:
    assert [f.value for f in numbers.spoken("שלוש שש")] == [3, 6]
    assert [f.value for f in numbers.spoken("שלושים ושתיים עשרה קילו")] == [32, 10]  # not 30 + 12
    assert [f.value for f in numbers.spoken("עשרים שלושים")] == [20, 30]


def test_words_that_only_look_like_numbers() -> None:
    assert numbers.spoken("מונה אנרגיה") == []  # "מונה" is a meter, not "שמונה"
    assert [f.value for f in numbers.spoken("שמונה מונים")] == [8]
    assert numbers.spoken("מפסק ראשי") == []


def test_numbers_counts_digits_and_words() -> None:
    assert numbers.numbers("4X63A ופחת 0,03 שלושים") == {Decimal(4), Decimal(63), Decimal("0.03"), Decimal(30)}


# --- the check ---------------------------------------------------------------------------------------------------

LINES = {"L1": "ln_a", "L2": "ln_b"}


def item(text: str, qty: int = 1, quote: str | None = None, panel: str | None = None) -> Item:
    return Item(text, qty, panel, quote if quote is not None else text)


def test_items_said_in_words_pass() -> None:
    got = chat.check(
        SPOKEN,
        [
            item("מפסק ראשי 4X63A", 1, "מפסק ראשי ארבע על שישים ושלוש"),
            item('מא"ז 1X16A', 12, "שנים עשר מא״ז אחד על שש עשרה"),
            item('מא"ז 3X25A', 4, "ארבעה מא״ז שלוש על עשרים וחמש"),
            item("פחת 4X40A", 1, "פחת ארבע על ארבעים"),
        ],
        [],
        {},
        ["לוח 1"],
    )
    assert [(i.text, i.quantity) for i in got.items] == [
        ("מפסק ראשי 4X63A", 1),
        ('מא"ז 1X16A', 12),
        ('מא"ז 3X25A', 4),
        ("פחת 4X40A", 1),
    ]
    assert got.dropped == []


def test_a_quote_the_message_does_not_have_is_dropped() -> None:
    got = chat.check('12 מא"ז 1X16', [item('מא"ז 1X16A', 12, "שנים עשר מאז")], [], {}, [])
    assert got.items == [] and got.dropped[0].reason == "not_in_message"


def test_a_glued_value_is_spaced_for_the_grammar() -> None:
    got = chat.check("שמונה מא״זים חד פאזיים שש עשרה אמפר", [item('מא"ז 1P16A', 8, "שמונה מא״זים")], [], {}, [])
    assert [i.text for i in got.items] == ['מא"ז 1P 16A']


def test_quote_marks_and_spaces_do_not_matter() -> None:
    got = chat.check("12 מא״ז  1X16", [item('מא"ז 1X16A', 12, '12 מא"ז 1X16')], [], {}, [])
    assert len(got.items) == 1


def test_a_number_nobody_said_drops_the_item() -> None:
    """The RCD's 30mA is stage 5's default (05 §5.5), never the model's."""
    got = chat.check("פחת 4X40", [item("פחת 4X40A 30mA", 1, "פחת 4X40")], [], {}, [])
    assert got.items == [] and got.dropped[0].reason == "number_not_said"


def test_a_quantity_must_be_said_unless_it_is_one() -> None:
    assert chat.check("פחת 4X40", [item("פחת 4X40A", 1, "פחת 4X40")], [], {}, []).items
    got = chat.check("פחת 4X40", [item("פחת 4X40A", 2, "פחת 4X40")], [], {}, [])
    assert got.items == [] and got.dropped[0].reason == "number_not_said"


def test_a_panel_must_be_known_or_said() -> None:
    got = chat.check(
        'בלוח 2: 6 מא"ז 1X16',
        [item('מא"ז 1X16A', 6, '6 מא"ז 1X16', panel="לוח 2"), item('מא"ז 1X16A', 6, '6 מא"ז 1X16', panel="לוח 9")],
        [],
        {},
        ["לוח 1"],
    )
    assert [i.panel for i in got.items] == ["לוח 2", None]


def test_changes_are_held_to_the_draft_and_the_message() -> None:
    got = chat.check(
        "לא 12, 10. ותוריד את הפחת. ועוד שניים מהמגענים",
        [],
        [
            Change("L1", "set_qty", 10, "לא 12, 10"),
            Change("L2", "remove", None, "תוריד את הפחת"),
            Change("L9", "remove", None, "תוריד את הפחת"),  # not a line of this draft
            Change("L1", "add_qty", 2, "עוד שניים מהמגענים"),
            Change("L1", "set_qty", 14, "לא 12, 10"),  # 14 was never said
        ],
        LINES,
        [],
    )
    assert [(c.line, c.action, c.quantity) for c in got.changes] == [
        ("L1", "set_qty", 10),
        ("L2", "remove", None),
        ("L1", "add_qty", 2),
    ]
    assert [d.reason for d in got.dropped] == ["unknown_line", "number_not_said"]


def test_a_quantity_set_to_zero_removes_the_line() -> None:
    got = chat.check("תעשה את L1 אפס, כלומר 0", [], [Change("L1", "set_qty", 0, "כלומר 0")], LINES, [])
    assert [(c.action, c.quantity) for c in got.changes] == [("remove", None)]


# --- the rows ----------------------------------------------------------------------------------------------------


def built(*items_: Item) -> table.BomTable:
    return chat.add_items(chat.empty_table("לוח 1"), items_, "לוח 1")


def components(t: table.BomTable) -> list[tuple[str, int]]:
    rows = bom.rows([("pg_01JB8Z3K7Q9T2M5X0R4W6Y8C1D", t)], {"לוח 1": "pnl_01JB8Z3K7Q9T2M5X0R4W6Y8C1D"}, None, SCH)
    return [(c.component_id, int(c.quantity)) for c in bom.components("drw_X", rows, by_row=True)]


def test_the_same_product_in_two_messages_is_one_line() -> None:
    t = built(item('מא"ז 1X16A', 12))
    t = chat.add_items(t, [item("פחת 4X40A"), item('מא"ז 1X16A', 4)], "לוח 1")
    assert components(t) == [("cmp_X_0001", 16), ("cmp_X_0002", 1)]


def test_a_line_keeps_its_name_when_rows_before_it_go() -> None:
    t = built(item('מא"ז 1X16A', 12), item("פחת 4X40A"), item("מגען 3X25A", 2))
    t = chat.remove(t, [1])
    assert components(t) == [("cmp_X_0002", 1), ("cmp_X_0003", 2)]
    t = chat.add_items(t, [item('מא"ז 1X16A', 3)], "לוח 1")  # back again: a new line, not the removed one
    assert components(t)[-1] == ("cmp_X_0004", 3)
    assert chat.next_row(t) == 5


def test_setting_and_adding_a_quantity_keep_the_first_row() -> None:
    t = chat.add_items(built(item('מא"ז 1X16A', 12)), [item('מא"ז 1X16A', 4)], "לוח 1")
    t = chat.set_quantity(t, [1, 2], 10)
    assert components(t) == [("cmp_X_0001", 10)]
    t = chat.add_quantity(t, [1, 2], 2)
    assert components(t) == [("cmp_X_0001", 12)]


def test_panel_names_in_order() -> None:
    t = built(item('מא"ז 1X16A', 12), item('מא"ז 1X16A', 6, panel="לוח 2"), item("פחת 4X40A", panel="לוח 1"))
    assert chat.panel_names(t, "לוח 1") == ["לוח 1", "לוח 2"]


# --- the stage and its stand-in ------------------------------------------------------------------------------------


def test_the_stand_in_answers_the_prototypes_sentences_and_they_pass_the_check() -> None:
    from konboro.devtools.fake_llm import fake_providers
    from konboro_llm import LLMClient
    from konboro_llm.stages import chat_bom_extraction as ext

    client = LLMClient(fake_providers())
    for message, want in (
        ('מפסק ראשי 4X63, 12 מא"ז 1X16, פחת 4X40', [("מפסק ראשי 4X63", 1), ('מא"ז 1X16', 12), ("פחת 4X40", 1)]),
        (SPOKEN, [("מפסק ראשי 4X63", 1), ('מא"ז 1X16', 12), ('מא"ז 3X25', 4), ("פחת 4X40", 1)]),
    ):
        answer = ext.extract(client, message, "", "לוח 1", 'מא"ז, פחת, מפסק').data
        items = [Item(i.text, i.quantity, i.panel, i.quote) for i in answer.items]
        got = chat.check(message, items, [], {}, ["לוח 1"])
        assert [(i.text, i.quantity) for i in got.items] == want
        assert got.dropped == []


def test_the_prompt_shows_the_lines_and_the_message() -> None:
    from konboro_llm import LLMClient
    from konboro_llm.providers import FakeProvider
    from konboro_llm.stages import chat_bom_extraction as ext

    seen = []

    def answer(request: object) -> dict[str, object]:
        seen.append(request)
        return {"items": [], "changes": [], "question": None}

    ext.extract(LLMClient({"anthropic": FakeProvider(answer)}), "תוריד את הפחת", "L1: מפסק פחת × 1", "לוח 1", "פחת")
    text = seen[0].user_text  # type: ignore[attr-defined]
    assert "L1: מפסק פחת × 1" in text and text.endswith("Message:\nתוריד את הפחת")
