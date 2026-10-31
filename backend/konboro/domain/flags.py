"""Feature-flag evaluation (13 §2–3). Pure: the DB reads live in konboro.services.flags.

Order: tenant override, then plan, then global (`feature_flags.default_on`), then the default, which is
off. A flag whose `depends_on` is not fully on is off too (e.g. `voice_input` needs `chat_quote_builder`).
An unknown key is off, so a typo can only hide a feature, never expose one.
"""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class FlagDef:
    key: str
    default_on: bool = False
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class FlagInputs:
    """Everything evaluation needs for one tenant."""

    defs: Mapping[str, FlagDef]
    plan: Mapping[str, bool] = field(default_factory=dict)
    tenant: Mapping[str, bool] = field(default_factory=dict)


def raw_value(inputs: FlagInputs, key: str) -> bool:
    """The flag's own setting, before dependencies."""
    if key in inputs.tenant:
        return inputs.tenant[key]
    if key in inputs.plan:
        return inputs.plan[key]
    flag = inputs.defs.get(key)
    return flag.default_on if flag is not None else False


def evaluate(inputs: FlagInputs) -> dict[str, bool]:
    """Every known flag's effective value for the tenant."""
    resolved: dict[str, bool] = {}

    def effective(key: str, path: frozenset[str]) -> bool:
        if key in resolved:
            return resolved[key]
        flag = inputs.defs.get(key)
        if flag is None or key in path:  # unknown, or a dependency cycle: off
            return False
        value = raw_value(inputs, key) and all(effective(dep, path | {key}) for dep in flag.depends_on)
        resolved[key] = value
        return value

    for key in inputs.defs:
        effective(key, frozenset())
    return resolved


def is_enabled(evaluated: Mapping[str, bool], key: str) -> bool:
    return evaluated.get(key, False)


class TTLCache[K, V]:
    """A small in-process cache (13 §2: "a short cache on the server"). Not shared across processes."""

    def __init__(self, ttl_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl = ttl_seconds
        self._clock = clock
        self._items: dict[K, tuple[float, V]] = {}

    def get(self, key: K) -> V | None:
        item = self._items.get(key)
        if item is None:
            return None
        stored_at, value = item
        if self._clock() - stored_at >= self.ttl:
            del self._items[key]
            return None
        return value

    def put(self, key: K, value: V) -> None:
        if self.ttl > 0:
            self._items[key] = (self._clock(), value)

    def clear(self) -> None:
        self._items.clear()
