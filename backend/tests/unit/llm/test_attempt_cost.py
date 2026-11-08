"""Every attempt is billed, so every attempt is recorded (01 §4.6 "עלות", S28c): a schema mismatch's tokens join the
call that finally answers, a call that never answers is a row with `ok` false, and an answer the provider could not
use (a refusal, cut short, not JSON) keeps the tokens it cost."""

from typing import Any

import pytest
from pydantic import BaseModel

from konboro_llm import LLMClient, LLMError, LLMRequest, LLMResult
from konboro_llm.base import RawAnswer
from konboro_llm.config import StageRoute
from konboro_llm.types import Usage


class Kind(BaseModel):
    page_kind: str


def request() -> LLMRequest[Kind]:
    return LLMRequest(stage="page_classification", system="s", user_text="u", output_schema=Kind, tenant_id="t")


class Billed:
    """Answers in order; each answer costs 100 in, 10 out, 50 read from the cache."""

    name = "billed"

    def __init__(self, answers: list[dict[str, Any] | LLMError]) -> None:
        self.answers = list(answers)

    def complete_structured(self, req: object, model: str, retry_hint: str | None = None) -> RawAnswer:
        answer = self.answers.pop(0)
        if isinstance(answer, LLMError):
            raise answer
        return RawAnswer(
            payload=answer, model=model, input_tokens=100, output_tokens=10, cache_read_tokens=50, cache_write_tokens=0
        )


def client(provider: Billed, route: StageRoute) -> tuple[LLMClient, list[LLMResult[Any]]]:
    seen: list[LLMResult[Any]] = []
    llm = LLMClient({"billed": provider}, {"page_classification": route}, on_call=lambda _, r: seen.append(r))
    return llm, seen


def test_a_schema_mismatch_is_billed_with_the_answer_that_follows() -> None:
    llm, seen = client(Billed([{"nope": 1}, {"page_kind": "cover"}]), StageRoute("billed", "m"))
    assert llm.run(request()).data.page_kind == "cover"
    assert len(seen) == 1
    assert seen[0].ok and seen[0].attempts == 2
    assert seen[0].usage == Usage(200, 20, 100, 0)


def test_a_call_that_never_answers_is_recorded_as_failed() -> None:
    llm, seen = client(Billed([{"nope": 1}, {"nope": 2}]), StageRoute("billed", "m", max_attempts=2))
    with pytest.raises(LLMError, match="did not match schema"):
        llm.run(request())
    assert [(r.ok, r.attempts, r.usage) for r in seen] == [(False, 2, Usage(200, 20, 100, 0))]


def test_an_unusable_answer_keeps_its_tokens_and_the_fallback_is_recorded_too() -> None:
    refused = LLMError("model stopped before answering: refusal", usage=Usage(300, 5), model="m-small")
    route = StageRoute("billed", "small", fallback=StageRoute("billed", "big"))
    llm, seen = client(Billed([refused, {"page_kind": "cover"}]), route)
    assert llm.run(request()).data.page_kind == "cover"
    assert [(r.ok, r.model, r.usage.input_tokens) for r in seen] == [(False, "m-small", 300), (True, "big", 100)]


def test_a_provider_error_with_no_answer_is_a_row_with_no_tokens() -> None:
    llm, seen = client(Billed([LLMError("overloaded")]), StageRoute("billed", "m"))
    with pytest.raises(LLMError):
        llm.run(request())
    assert [(r.ok, r.usage) for r in seen] == [(False, Usage(0, 0))]


def test_usage_adds_up_every_kind_of_token() -> None:
    assert Usage(1, 2, 3, 4) + Usage(10, 20, 30, 40) == Usage(11, 22, 33, 44)
