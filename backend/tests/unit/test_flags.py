"""Flag evaluation (13 §2): tenant, then plan, then global, then default; dependencies; unknown keys."""

import itertools

import pytest

from konboro.domain.flags import FlagDef, FlagInputs, TTLCache, evaluate, is_enabled, raw_value

CHAT, VOICE = "chat_quote_builder", "voice_input"
DEFS = {CHAT: FlagDef(CHAT), VOICE: FlagDef(VOICE, depends_on=(CHAT,))}

# None = that layer says nothing about the flag.
LAYER = (None, False, True)


@pytest.mark.parametrize(("tenant", "plan", "global_on"), list(itertools.product(LAYER, LAYER, (False, True))))
def test_precedence_every_combination(tenant: bool | None, plan: bool | None, global_on: bool) -> None:
    inputs = FlagInputs(
        defs={"f": FlagDef("f", default_on=global_on)},
        plan={} if plan is None else {"f": plan},
        tenant={} if tenant is None else {"f": tenant},
    )
    expected = tenant if tenant is not None else plan if plan is not None else global_on
    assert evaluate(inputs) == {"f": expected}


def test_a_new_flag_is_off_by_default() -> None:
    assert evaluate(FlagInputs(defs={"f": FlagDef("f")})) == {"f": False}


def test_tenant_can_turn_off_what_the_plan_turns_on() -> None:
    inputs = FlagInputs(defs={"f": FlagDef("f", default_on=True)}, plan={"f": True}, tenant={"f": False})
    assert evaluate(inputs)["f"] is False


@pytest.mark.parametrize(
    ("chat", "voice", "voice_expected"),
    [(True, True, True), (False, True, False), (True, False, False), (False, False, False)],
)
def test_voice_needs_chat_builder(chat: bool, voice: bool, voice_expected: bool) -> None:
    result = evaluate(FlagInputs(defs=DEFS, tenant={CHAT: chat, VOICE: voice}))
    assert result == {CHAT: chat, VOICE: voice_expected}


def test_dependency_from_another_layer_counts() -> None:
    result = evaluate(FlagInputs(defs=DEFS, plan={CHAT: True}, tenant={VOICE: True}))
    assert result[VOICE] is True


def test_dependencies_chain() -> None:
    defs = {"a": FlagDef("a"), "b": FlagDef("b", depends_on=("a",)), "c": FlagDef("c", depends_on=("b",))}
    assert evaluate(FlagInputs(defs=defs, tenant={"b": True, "c": True}))["c"] is False
    assert evaluate(FlagInputs(defs=defs, tenant={"a": True, "b": True, "c": True}))["c"] is True


def test_unknown_dependency_turns_the_flag_off() -> None:
    defs = {"f": FlagDef("f", default_on=True, depends_on=("missing",))}
    assert evaluate(FlagInputs(defs=defs)) == {"f": False}


def test_dependency_cycle_is_off_not_infinite() -> None:
    defs = {"a": FlagDef("a", True, ("b",)), "b": FlagDef("b", True, ("a",))}
    assert evaluate(FlagInputs(defs=defs)) == {"a": False, "b": False}


def test_unknown_key_is_off() -> None:
    evaluated = evaluate(FlagInputs(defs=DEFS, tenant={CHAT: True}))
    assert is_enabled(evaluated, "no_such_flag") is False
    assert raw_value(FlagInputs(defs=DEFS, tenant={}), "no_such_flag") is False


def test_override_for_unknown_key_is_ignored() -> None:
    # A stale override row must not invent a flag.
    assert evaluate(FlagInputs(defs=DEFS, tenant={"retired_flag": True})) == {CHAT: False, VOICE: False}


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_cache_expires_after_ttl() -> None:
    clock = FakeClock()
    cache: TTLCache[str, int] = TTLCache(30, clock)
    cache.put("t", 1)
    clock.now = 29.9
    assert cache.get("t") == 1
    clock.now = 30
    assert cache.get("t") is None


def test_cache_clear_and_zero_ttl() -> None:
    cache: TTLCache[str, int] = TTLCache(30)
    cache.put("t", 1)
    cache.clear()
    assert cache.get("t") is None
    off: TTLCache[str, int] = TTLCache(0)
    off.put("t", 1)
    assert off.get("t") is None
