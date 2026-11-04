"""What a conversation has shown the model, kept on the server (08 §5.4, `chat_conversations.state`).

- **Names.** The model sees lines as `L1`, `L2`…, panels as `B1`…, findings as `F1`…, proposals as `CH1`…. A name is
  given the first time a tool shows the thing, and keeps meaning it for the whole conversation. Short names cost few
  tokens, cannot be guessed into another tenant's ids, and make a recorded conversation replay on a fresh seed.
- **Money.** Every amount a tool would show becomes a reference: `$T1` for shekels, `$P1` for a percentage that comes
  from money (a margin). The model writes `{{$T1}}`; the screen gets the amount (`resolve`). The same amount of the
  same kind gets the same reference.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

PREFIX = {"line": "L", "panel": "B", "finding": "F", "proposal": "CH"}
MoneyKind = Literal["ils", "pct"]
MONEY_PREFIX: dict[str, str] = {"ils": "$T", "pct": "$P"}


@dataclass
class ChatState:
    names: dict[str, str] = field(default_factory=dict)  # "L3" -> "ln_…"
    money: dict[str, dict[str, str]] = field(default_factory=dict)  # "$T1" -> {"kind": "ils", "value": "120.50"}
    counters: dict[str, int] = field(default_factory=dict)
    _by_id: dict[str, str] = field(default_factory=dict, repr=False)
    _by_amount: dict[tuple[str, str], str] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, data: dict[str, Any] | None) -> "ChatState":
        data = data or {}
        state = cls(dict(data.get("names", {})), dict(data.get("money", {})), dict(data.get("counters", {})))
        state._by_id = {v: k for k, v in state.names.items()}
        state._by_amount = {(m["kind"], m["value"]): ref for ref, m in state.money.items()}
        return state

    def dump(self) -> dict[str, Any]:
        return {"names": self.names, "money": self.money, "counters": self.counters}

    def _next(self, prefix: str) -> int:
        n = self.counters.get(prefix, 0) + 1
        self.counters[prefix] = n
        return n

    def name(self, kind: str, real_id: str | None) -> str | None:
        if real_id is None:
            return None
        found = self._by_id.get(real_id)
        if found is not None:
            return found
        prefix = PREFIX[kind]
        alias = f"{prefix}{self._next(prefix)}"
        self.names[alias] = real_id
        self._by_id[real_id] = alias
        return alias

    def real(self, alias: str | None, kind: str | None = None) -> str | None:
        """The id behind a name, or None for a name this conversation never gave (or of another kind)."""
        if not alias:
            return None
        alias = alias.strip().upper()
        if kind is not None:
            prefix = PREFIX[kind]
            if not alias.startswith(prefix) or not alias[len(prefix) :].isdigit():
                return None
        return self.names.get(alias)

    def ref(self, value: Decimal | None, kind: MoneyKind = "ils") -> str | None:
        """A reference for an amount (None stays None: "אין מחיר")."""
        if value is None:
            return None
        text = format(Decimal(value).normalize(), "f")
        found = self._by_amount.get((kind, text))
        if found is not None:
            return found
        prefix = MONEY_PREFIX[kind]
        ref = f"{prefix}{self._next(prefix)}"
        self.money[ref] = {"kind": kind, "value": text}
        self._by_amount[(kind, text)] = ref
        return ref

    def resolve(self, refs: set[str]) -> dict[str, dict[str, str]]:
        return {r: self.money[r] for r in sorted(refs) if r in self.money}
