from konboro_llm import ImageInput, LLMClient
from konboro_llm.config import StageRoute
from konboro_llm.providers import FakeProvider
from konboro_llm.stages.text_association import associate_text

GOOD = {
    "symbols": [
        {
            "symbol_id": "s1",
            "family": "mcb",
            "current_a": 16,
            "poles": 3,
            "curve": "C",
            "breaking_capacity_ka": 10,
            "raw_text": "C16 3P 10kA",
            "confidence": 0.94,
        }
    ]
}
BAD = {"symbols": [{"symbol_id": "s1", "family": "mcb"}]}  # missing raw_text and confidence

TILE = ImageInput(b"png-bytes")
DETECTIONS = [{"id": "s1", "family": "mcb", "box": [10, 20, 40, 60]}]


def test_valid_answer_on_first_attempt():
    fake = FakeProvider([GOOD])
    llm = LLMClient({"fake": fake}, {"text_association": StageRoute("fake", "m1")})
    result = associate_text(llm, TILE, DETECTIONS, [], tenant_id="factory-1")
    assert result.symbols[0].current_a == 16
    assert len(fake.calls) == 1


def test_schema_mismatch_retries_with_hint():
    fake = FakeProvider([BAD, GOOD])
    llm = LLMClient({"fake": fake}, {"text_association": StageRoute("fake", "m1")})
    result = associate_text(llm, TILE, DETECTIONS, [], tenant_id="factory-1")
    assert result.symbols[0].poles == 3
    assert fake.calls[1][2] is not None  # second call carried the validation error


def test_falls_back_to_second_model():
    fake = FakeProvider([BAD, BAD, GOOD])
    route = StageRoute("fake", "small", max_attempts=2, fallback=StageRoute("fake", "big"))
    llm = LLMClient({"fake": fake}, {"text_association": route})
    associate_text(llm, TILE, DETECTIONS, [], tenant_id="factory-1")
    assert [c[1] for c in fake.calls] == ["small", "small", "big"]


def test_bedrock_model_ids_are_prefixed():
    from konboro_llm.providers.anthropic_provider import AnthropicProvider

    class _Client:  # stands in for the Bedrock SDK client; only messages.create is used
        pass

    p = AnthropicProvider(client=_Client(), model_prefix="anthropic.")
    assert p.model_id("claude-sonnet-5-5") == "anthropic.claude-sonnet-5-5"
    assert p.model_id("anthropic.claude-haiku-5-5") == "anthropic.claude-haiku-5-5"
    assert AnthropicProvider(client=_Client()).model_id("claude-sonnet-5-5") == "claude-sonnet-5-5"


class _Answer:
    """Stands in for an SDK message: only the fields the provider reads."""

    def __init__(self, text: str | None, stop_reason: str = "end_turn") -> None:
        from types import SimpleNamespace

        self.stop_reason, self.model = stop_reason, "claude-sonnet-5-5"
        self.content = [SimpleNamespace(type="text", text=text)] if text is not None else []
        self.usage = SimpleNamespace(input_tokens=10, output_tokens=5)


class _Messages:
    def __init__(self, answer: _Answer) -> None:
        self.answer, self.kwargs = answer, {}

    def create(self, **kwargs):  # type: ignore[no-untyped-def]
        self.kwargs = kwargs
        return self.answer


def _provider(answer: _Answer):  # type: ignore[no-untyped-def]
    from types import SimpleNamespace

    from konboro_llm.providers.anthropic_provider import AnthropicProvider

    messages = _Messages(answer)
    return AnthropicProvider(client=SimpleNamespace(messages=messages)), messages


def test_the_answer_comes_back_as_json_output_not_a_forced_tool():
    """Sonnet 5.5 and Opus 5.5 reject a forced tool_choice with a 400 (BUG-013): ask for JSON output instead."""
    import json

    provider, messages = _provider(_Answer(json.dumps(GOOD)))
    llm = LLMClient({"anthropic": provider}, {"text_association": StageRoute("anthropic", "claude-sonnet-5-5")})
    result = associate_text(llm, TILE, DETECTIONS, [], tenant_id="factory-1")
    assert result.symbols[0].current_a == 16
    assert "tool_choice" not in messages.kwargs and "tools" not in messages.kwargs
    fmt = messages.kwargs["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False


def test_a_refusal_a_cut_answer_or_non_json_is_an_error():
    import pytest

    from konboro_llm import LLMError, LLMRequest
    from konboro_llm.stages.text_association import TextAssociationResult

    request = LLMRequest(
        stage="text_association", system="s", user_text="u", output_schema=TextAssociationResult, tenant_id="t"
    )
    for answer, message in [
        (_Answer("{}", "refusal"), "refusal"),
        (_Answer('{"symbols": [', "max_tokens"), "max_tokens"),
        (_Answer(None), "no text"),
        (_Answer("not json"), "not JSON"),
    ]:
        with pytest.raises(LLMError, match=message):
            _provider(answer)[0].complete_structured(request, "claude-sonnet-5-5")
