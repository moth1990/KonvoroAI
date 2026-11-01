"""CassetteProvider: record then replay gives the same result, a missing cassette is an error, and the key changes
with anything that can change the answer."""

from pathlib import Path

import pytest
from pydantic import BaseModel

from konboro_llm import Example, ImageInput, LLMClient, LLMRequest, LLMResult
from konboro_llm.config import StageRoute
from konboro_llm.providers import CassetteMissingError, CassetteProvider, FakeProvider
from konboro_llm.providers.cassette_provider import cassette_key


class Kind(BaseModel):
    page_kind: str
    confidence: float


ANSWER = {"page_kind": "single_line_diagram", "confidence": 0.93}
ROUTES = {"page_classification": StageRoute("anthropic", "claude-haiku-5-5")}


def request(**changes: object) -> LLMRequest[Kind]:
    fields: dict[str, object] = {
        "stage": "page_classification",
        "system": "Classify the page.",
        "user_text": "Page 5 of 9",
        "output_schema": Kind,
        "images": [ImageInput(b"thumb")],
        "tenant_id": "tnt_x",
    }
    fields.update(changes)
    return LLMRequest(**fields)  # type: ignore[arg-type]


def test_record_then_replay_is_identical(tmp_path: Path) -> None:
    live = FakeProvider([ANSWER])
    recorded = LLMClient({"anthropic": CassetteProvider(tmp_path, "record", wrapped=live)}, ROUTES).run(request())
    replayed = LLMClient({"anthropic": CassetteProvider(tmp_path, "replay")}, ROUTES).run(request())

    assert len(live.calls) == 1  # replay never reaches a provider
    assert replayed.data == recorded.data == Kind(**ANSWER)
    assert (replayed.model, replayed.usage, replayed.attempts) == (recorded.model, recorded.usage, 1)
    (file,) = (tmp_path / "page_classification").iterdir()
    assert file.name == f"{cassette_key(request(), 'claude-haiku-5-5', None)}.json"


def test_recording_the_same_request_twice_writes_the_same_bytes(tmp_path: Path) -> None:
    provider = CassetteProvider(tmp_path, "record", wrapped=FakeProvider([ANSWER, ANSWER]))
    provider.complete_structured(request(), "m")
    first = provider.path(request(), "m").read_bytes()
    provider.complete_structured(request(), "m")
    assert provider.path(request(), "m").read_bytes() == first


def test_a_missing_cassette_raises(tmp_path: Path) -> None:
    with pytest.raises(CassetteMissingError, match="EVAL_RECORD=1"):
        CassetteProvider(tmp_path, "replay").complete_structured(request(), "m")


def test_the_client_does_not_fall_back_past_a_missing_cassette(tmp_path: Path) -> None:
    client = LLMClient({"anthropic": CassetteProvider(tmp_path, "replay")}, ROUTES)
    with pytest.raises(Exception, match="no cassette"):
        client.run(request())


def test_record_needs_a_provider(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="record mode needs"):
        CassetteProvider(tmp_path, "record")


@pytest.mark.parametrize(
    "change",
    [
        {"system": "Classify the page, carefully."},
        {"user_text": "Page 6 of 9"},
        {"images": [ImageInput(b"another thumb")]},
        {"images": [ImageInput(b"thumb", "image/jpeg")]},
        {"examples": [Example(image=None, text="a legend", expected_json="{}")]},
        {"stage": "context_extraction"},
    ],
)
def test_the_key_changes_with_the_input(change: dict[str, object]) -> None:
    assert cassette_key(request(**change), "m", None) != cassette_key(request(), "m", None)


def test_the_key_changes_with_model_schema_and_retry_hint() -> None:
    class Other(BaseModel):
        page_kind: str

    base = cassette_key(request(), "m", None)
    assert cassette_key(request(), "m2", None) != base
    assert cassette_key(request(output_schema=Other), "m", None) != base
    assert cassette_key(request(), "m", "confidence: field required") != base
    assert cassette_key(request(tenant_id="tnt_other"), "m", None) == base  # never sent to the model


def test_on_call_sees_every_answered_call() -> None:
    seen: list[tuple[str, LLMResult[Kind]]] = []
    client = LLMClient(
        {"anthropic": FakeProvider([{"page_kind": "x"}, ANSWER])},
        ROUTES,
        on_call=lambda req, res: seen.append((req.stage, res)),
    )
    client.run(request())
    assert [(stage, r.attempts) for stage, r in seen] == [("page_classification", 2)]


def test_a_stable_image_key_replaces_the_pixels() -> None:
    """A page rendered by another platform's PDFium gives other bytes; the content key keeps the cassette valid."""
    keyed = cassette_key(request(images=[ImageInput(b"mac pixels", key="pg-sha:1024")]), "m", None)
    assert cassette_key(request(images=[ImageInput(b"linux pixels", key="pg-sha:1024")]), "m", None) == keyed
    assert cassette_key(request(images=[ImageInput(b"mac pixels", key="pg-sha:1568")]), "m", None) != keyed
