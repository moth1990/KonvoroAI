"""The chat home's routing rules in code (13 §4.3, S27) and the recording's checks (13 §4.2). No database, no model."""

import pytest

from konboro.services import home_route as hr
from konboro.services import transcribe


@pytest.mark.parametrize(
    "text",
    [
        "בדוק את הצעה 10271 מול השרטוט",
        "תבדוק את ההצעה ששלחתי",
        "בדיקת הצעה של הקבלן",
        "לבדוק הצעה קיימת",
        "תבדוק לי את ההצעה ששלחתי ללקוח מול השרטוט שלו",
        "יש לי הצעה ישנה, אפשר לבדוק אם חסר בה משהו לפי השרטוט?",
    ],
)
def test_audit_words(text: str) -> None:
    assert hr.CHECK.search(text) and hr.OFFER.search(text)


def test_without_a_drawing_is_not_a_drawing() -> None:
    assert not hr.DRAWING.search("רוצה לבנות הצעה ללוח חדש בלי שרטוט")
    assert hr.DRAWING.search("יש לי שרטוט חדש")


@pytest.mark.parametrize("text", ["אילו מחירים חסרים במחירון?", "פתח את המחירון"])
def test_price_list_words(text: str) -> None:
    assert hr.PRICES.search(text)


@pytest.mark.parametrize(
    ("text", "panel"),
    [
        ('בנה הצעה ללוח 3 פאזות 63A עם 12 מא"ז 1X16', True),
        ("שנים עשר מא״ז אחד על שש עשרה", True),
        ("מה חסר בהצעה של NURSERY?", False),
        ("תוסיף פחת להצעה של הגן", False),  # a product word with no value: a change to a quote, not a build
    ],
)
def test_a_panel_description_has_a_product_word_and_a_number(text: str, panel: bool) -> None:
    assert hr._describes_a_panel(text) is panel


def test_a_quotes_words_leave_out_what_every_quote_has() -> None:
    words = hr._distinct(hr._words("NURSERY-1_merged.pdf גן ילדים, לוח ראשי"))
    assert words == {"nursery", "ילדים"}
    assert hr._distinct(hr._words("מה חסר בהצעה של הילדים?")) == {"ילדים", "הילדים"}


def test_a_name_is_read_whole() -> None:
    assert hr._phrase("לוח חשמל, קומה 3") == "לוח חשמל קומה 3"


def test_questions() -> None:
    assert hr.QUESTION.search("מה חסר?")
    assert hr.QUESTION.search('תשנה את המא"זים לשניידר')
    assert not hr.QUESTION.search('12 מא"ז 1X16')


@pytest.mark.parametrize(
    ("body", "kind", "ok"),
    [
        (b"\x1aE\xdf\xa3", "audio/webm;codecs=opus", True),
        (b"\x00", "audio/mp4", True),
        (b"\x00", "text/plain", False),
        (b"", "audio/webm", False),
        (b"\x00" * (transcribe.MAX_BYTES + 1), "audio/webm", False),
    ],
)
def test_a_recording_is_checked_before_it_is_heard(body: bytes, kind: str, ok: bool) -> None:
    if ok:
        assert transcribe.check(body, kind) == kind.split(";")[0]
    else:
        with pytest.raises(transcribe.RecordingError):
            transcribe.check(body, kind)


def test_the_stand_in_hears_the_prototypes_sentence() -> None:
    t = transcribe.transcriber()
    assert t.stand_in and t.transcribe(b"x", "audio/webm") == transcribe.STAND_IN_HEARD
