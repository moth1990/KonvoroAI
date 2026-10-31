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
