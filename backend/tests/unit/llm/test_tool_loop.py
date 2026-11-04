"""The chat coordinator's tool loop (08 §4): the model asks for tools, code runs them, the answer is validated."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from konboro_llm import LLMClient, LLMError, ToolLoopRequest, ToolSpec, Turn
from konboro_llm.config import StageRoute
from konboro_llm.providers import CassetteMissingError, CassetteProvider, FakeProvider


class Find(BaseModel):
    family: str
    limit: int = 50


class Final(BaseModel):
    text: str


TOOLS = [ToolSpec("query_lines", "Find lines by filter", Find)]
ROUTES = {"chat_command": StageRoute("fake", "m1")}


def request(**kw: Any) -> ToolLoopRequest[Final]:
    return ToolLoopRequest(
        stage="chat_command",
        system="instructions",
        turns=[Turn("user", text='כמה מא"זים יש?')],
        tools=TOOLS,
        output_schema=Final,
        context="brief",
        tenant_id="tnt_1",
        **kw,
    )


def ask(name: str = "query_lines", **args: Any) -> dict[str, Any]:
    return {"tool_calls": [{"name": name, "args": args}]}


def test_tools_run_in_code_and_the_loop_ends_with_a_validated_answer():
    fake = FakeProvider([ask(family="circuit_breaker"), {"answer": {"text": "12 שורות"}}])
    seen: list[Any] = []
    logged: list[str] = []
    llm = LLMClient({"fake": fake}, ROUTES, on_call=lambda req, res: logged.append(req.stage))

    def execute(call: Any, args: BaseModel) -> dict[str, Any]:
        seen.append(args)
        return {"total_count": 12}

    result = llm.run_tools(request(), execute)
    assert result.data == Final(text="12 שורות")
    assert seen == [Find(family="circuit_breaker")]
    assert result.calls == 2 and logged == ["chat_command", "chat_command"]  # every model call goes to llm_calls
    second = fake.turns[1].turns
    assert [t.role for t in second] == ["user", "assistant", "user"]
    assert second[2].tool_results[0].content == {"total_count": 12}
    assert len(result.steps) == 1 and result.steps[0].calls[0].name == "query_lines"


def test_bad_arguments_and_unknown_tools_go_back_to_the_model_as_errors():
    fake = FakeProvider([ask(limit=3), ask("apply_change"), {"answer": {"text": "ok"}}])
    ran: list[Any] = []
    llm = LLMClient({"fake": fake}, ROUTES)
    llm.run_tools(request(), lambda c, a: ran.append(a) or {})
    assert ran == []  # neither call reached code
    first = fake.turns[1].turns[-1].tool_results[0]
    assert first.is_error and first.content["error"] == "invalid_arguments"
    unknown = fake.turns[2].turns[-1].tool_results[0]
    assert unknown.is_error and unknown.content == {"error": "unknown_tool", "tool": "apply_change"}


def test_a_failing_tool_is_answered_as_tool_failed():
    fake = FakeProvider([ask(family="rcd"), {"answer": {"text": "לא הצלחתי"}}])

    def boom(call: Any, args: BaseModel) -> dict[str, Any]:
        raise RuntimeError("db down")

    LLMClient({"fake": fake}, ROUTES).run_tools(request(), boom)
    result = fake.turns[1].turns[-1].tool_results[0]
    assert result.is_error and result.content == {"error": "tool_failed"}


def test_after_max_steps_the_model_must_answer_without_tools():
    fake = FakeProvider([ask(family="rcd"), ask(family="rcd"), {"answer": {"text": "done"}}])
    result = LLMClient({"fake": fake}, ROUTES).run_tools(request(max_steps=2), lambda c, a: {})
    assert [t.allow_tools for t in fake.turns] == [True, True, False]
    assert result.data.text == "done" and len(result.steps) == 2


def test_an_invalid_final_answer_is_retried_with_the_error():
    fake = FakeProvider([{"answer": {"wrong": 1}}, {"answer": {"text": "fixed"}}])
    result = LLMClient({"fake": fake}, ROUTES).run_tools(request(), lambda c, a: {})
    assert result.data.text == "fixed"
    assert fake.turns[0].retry_hint is None and "text" in (fake.turns[1].retry_hint or "")


def test_no_valid_answer_after_the_attempts_is_an_error():
    fake = FakeProvider([{"answer": {"wrong": 1}}, {"answer": {"wrong": 2}}])
    with pytest.raises(LLMError):
        LLMClient({"fake": fake}, ROUTES).run_tools(request(), lambda c, a: {})


def test_a_failed_call_falls_back_without_running_the_tools_again():
    class Broken(FakeProvider):
        def complete_turn(self, *a: Any, **k: Any) -> Any:
            raise LLMError("overloaded")

    good = FakeProvider([{"answer": {"text": "from fallback"}}])
    routes = {"chat_command": StageRoute("broken", "m1", fallback=StageRoute("good", "m2"))}
    llm = LLMClient({"broken": Broken([]), "good": good}, routes)
    result = llm.run_tools(request(), lambda c, a: {})
    assert result.data.text == "from fallback" and result.provider == "fake"


def test_a_stage_without_a_route_is_an_error():
    with pytest.raises(LLMError):
        LLMClient({}, {}).run_tools(request(), lambda c, a: {})


# ---------------------------------------------------------------------------- Anthropic


class _Block(SimpleNamespace):
    pass


class _Messages:
    def __init__(self, contents: list[list[_Block]]) -> None:
        self.contents, self.sent = contents, []

    def create(self, **kwargs: Any) -> Any:
        self.sent.append(json.loads(json.dumps(kwargs, default=str)))
        content = self.contents.pop(0)
        stop = "tool_use" if any(b.type == "tool_use" for b in content) else "end_turn"
        return SimpleNamespace(
            content=content,
            stop_reason=stop,
            model="claude-sonnet-5-5",
            usage=SimpleNamespace(input_tokens=9, output_tokens=3),
        )


def test_anthropic_sends_tools_auto_caches_the_prefix_and_reads_tool_use():
    from konboro_llm.providers.anthropic_provider import AnthropicProvider

    messages = _Messages(
        [
            [
                _Block(type="text", text="בודק"),
                _Block(type="tool_use", id="tu_1", name="query_lines", input={"family": "rcd"}),
            ],
            [_Block(type="text", text=json.dumps({"text": "יש 4"}))],
        ]
    )
    provider = AnthropicProvider(client=SimpleNamespace(messages=messages))
    llm = LLMClient({"anthropic": provider}, {"chat_command": StageRoute("anthropic", "claude-sonnet-5-5")})
    result = llm.run_tools(request(), lambda c, a: {"total_count": 4})
    assert result.data.text == "יש 4"

    first, second = messages.sent
    assert first["tool_choice"] == {"type": "auto"}  # never a forced tool (BUG-013)
    assert first["tools"][0]["name"] == "query_lines"
    assert first["system"][0] == {"type": "text", "text": "instructions", "cache_control": {"type": "ephemeral"}}
    assert first["system"][1] == {"type": "text", "text": "brief"}  # the per-turn context is not cached
    assert first["output_config"]["format"]["type"] == "json_schema"
    assistant, results = second["messages"][1], second["messages"][2]
    assert assistant["content"] == [
        {"type": "text", "text": "בודק"},
        {"type": "tool_use", "id": "tu_1", "name": "query_lines", "input": {"family": "rcd"}},
    ]
    assert results["content"][0]["type"] == "tool_result" and results["content"][0]["tool_use_id"] == "tu_1"
    assert json.loads(results["content"][0]["content"]) == {"total_count": 4}
    assert results["content"][-1]["cache_control"] == {"type": "ephemeral"}  # the loop's steps read each other


def test_anthropic_last_call_has_tool_choice_none():
    from konboro_llm.providers.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider(client=SimpleNamespace(messages=_Messages([])))
    params = provider.turn_params(request(), request().turns, "claude-sonnet-5-5", allow_tools=False, retry_hint="x")
    assert params["tool_choice"] == {"type": "none"}
    assert "x" in params["messages"][-1]["content"][-1]["text"]


def test_anthropic_a_non_json_final_answer_has_no_payload():
    from konboro_llm.providers.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider(client=SimpleNamespace(messages=_Messages([[_Block(type="text", text="שלום")]])))
    raw = provider.complete_turn(request(), request().turns, "claude-sonnet-5-5")
    assert raw.payload is None and raw.tool_calls == []


# ---------------------------------------------------------------------------- cassettes


def test_cassettes_record_and_replay_a_tool_loop(tmp_path: Path):
    live = FakeProvider([ask(family="rcd"), {"answer": {"text": "4"}}])
    recorder = CassetteProvider(tmp_path, "record", wrapped=live)
    LLMClient({"fake": recorder}, ROUTES).run_tools(request(), lambda c, a: {"total_count": 4})
    assert len(list((tmp_path / "chat_command").glob("*.json"))) == 2

    replay = CassetteProvider(tmp_path, "replay")
    result = LLMClient({"fake": replay}, ROUTES).run_tools(request(), lambda c, a: {"total_count": 4})
    assert result.data.text == "4"

    # A different tool result is a different conversation: replay refuses rather than guess
    with pytest.raises(LLMError) as err:
        LLMClient({"fake": replay}, ROUTES).run_tools(request(), lambda c, a: {"total_count": 5})
    assert isinstance(err.value.__cause__, CassetteMissingError) or "cassette" in str(err.value)
