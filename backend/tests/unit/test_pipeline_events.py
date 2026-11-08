"""What a stage reports while it runs (01 §4.6, S28c): sentences from templates in code, at most one write a second,
the latest of each kind kept in between and sent when the stage ends, and a failed write never fails a stage."""

from typing import Any

from konboro.contracts.merge import MergeResult, MergeStats
from konboro.pipeline import events as ev
from konboro.pipeline.events import Events, kind_text, message_text


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def recorder() -> tuple[Events, list[tuple[str, dict[str, Any]]], Clock]:
    written: list[tuple[str, dict[str, Any]]] = []
    clock = Clock()
    return Events(lambda kind, payload: written.append((kind, payload)), now=clock), written, clock


def test_sentences_come_from_templates() -> None:
    assert message_text("components_on_page", page=5, count=18) == "עמוד 5: 18 רכיבים"
    assert message_text("page_kind", page=1, kind=kind_text("technical_data")) == "עמוד 1: נתונים טכניים"
    assert kind_text("something_new") == "עמוד"
    assert "OCR" not in " ".join(ev.TEMPLATES.values())  # 01 §4.6: plain Hebrew


def test_at_most_one_write_a_second_and_the_latest_waits() -> None:
    events, written, clock = recorder()
    events.message("page_kind", page=1, kind="שער", page_id="pg_1")
    events.message("page_kind", page=2, kind="חד-קווי", page_id="pg_2")  # within the second: waits
    events.message("page_kind", page=3, kind="פיקוד", page_id="pg_3")  # replaces it
    assert [p["text"] for _, p in written] == ["עמוד 1: שער"]
    clock.t = 1.0
    events.counters(pages=9, pages_read=3)
    assert [k for k, _ in written] == ["message", "message", "counters"]
    assert written[1][1] == {"key": "page_kind", "text": "עמוד 3: פיקוד", "page_id": "pg_3"}


def test_the_stage_end_sends_what_waits() -> None:
    events, written, _ = recorder()
    events.counters(tiles=4)
    events.counters(tiles=9)
    events.flush()
    assert written == [("counters", {"tiles": 4}), ("counters", {"tiles": 9})]
    events.flush()  # nothing waits: nothing more
    assert len(written) == 2


def test_boxes_are_rounded_and_capped() -> None:
    events, written, _ = recorder()
    events.boxes("pg_1", 5, (841.889, 1190.551), [[1.234, 2.0, 3.0, 4.0]] * (ev.MAX_BOXES + 10))
    payload = written[0][1]
    assert payload["size"] == [841.9, 1190.6]
    assert payload["boxes"][0] == [1.2, 2.0, 3.0, 4.0]
    assert len(payload["boxes"]) == ev.MAX_BOXES


def test_a_failed_write_never_fails_the_stage() -> None:
    def broken(kind: str, payload: dict[str, Any]) -> None:
        raise RuntimeError("database gone")

    Events(broken).message("reading_file")  # no exception


def test_the_silent_reporter_writes_nothing() -> None:
    ev.SILENT.message("reading_file")
    ev.SILENT.flush()


def test_stages_4_to_8_report_at_their_ends_from_their_output() -> None:
    events, written, clock = recorder()
    ev.started(events, 4)
    clock.t = 2.0
    out = MergeResult.model_construct(stats=MergeStats(instance_count=44, component_count=13))
    ev.finished(events, 4, out)
    events.flush()
    texts = [p["text"] for k, p in written if k == "message"]
    assert texts == ["מחבר תוויות לרכיבים", "44 מכשירים ← 13 מוצרים"]
    assert ("counters", {"products": 13}) in written
    ev.started(events, 1)  # stages 1–3 report inside: nothing here
    assert len([k for k, _ in written if k == "message"]) == 2
