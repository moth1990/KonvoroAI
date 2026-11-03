"""06 §6.2: the rule pack is data. `rules.json` holds every rule's id, version, category, families, what it needs, its
severity, its parameters and its Hebrew title and message; `seed_global` writes it into `validator_rules`, and the
stage reads the table back (the file when the table is empty, in unit tests). Each rule's check is code, one function
per `rule_id` (`checks.py`).

A factory may turn a rule off or change its parameters (`tenant_rule_overrides`, 06 §6.5 item 2). The factory's
version (`tenant_rules_version`) names what it changed, so a result says which rules it ran under.

Category A's wording and thresholds wait for the electrical expert (06 §13 item 2, roadmap B2): those rules run, and
carry `approval` = `pending_expert` until the expert signs them off (S21 decision 7).
"""

import hashlib
import json
from dataclasses import dataclass, field, replace
from functools import cache
from importlib import resources
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.db import models as m

Category = Literal["A", "B", "C", "D", "E"]
Requires = Literal["wire_graph", "bom_table", "front_view", "text_layer"]
REQUIRES: tuple[str, ...] = ("wire_graph", "bom_table", "front_view", "text_layer")


@dataclass(frozen=True)
class Rule:
    rule_id: str
    version: int
    category: Category
    applies_to: tuple[str, ...]
    requires: Requires | None
    severity: Literal["error", "warning", "info"]
    params: dict[str, Any]
    title_he: str
    message_he: str
    enabled: bool = True
    approval: str | None = None

    def applies(self, family: str) -> bool:
        return not self.applies_to or family in self.applies_to

    def as_row(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "version": self.version,
            "category": self.category,
            "applies_to": list(self.applies_to),
            "requires": self.requires,
            "severity": self.severity,
            "params": self.params,
            "title_he": self.title_he,
            "message_he": self.message_he,
            "enabled": self.enabled,
            "approval": self.approval,
        }


@dataclass(frozen=True)
class Pack:
    version: str
    rules: dict[str, Rule]
    tenant_version: str | None = None
    turned_off: frozenset[str] = field(default_factory=frozenset)

    def active(self) -> list[Rule]:
        return [r for r in self.rules.values() if r.enabled and r.rule_id not in self.turned_off]


def _rule(row: dict[str, Any]) -> Rule:
    return Rule(
        rule_id=row["rule_id"],
        version=int(row.get("version", 1)),
        category=row["category"],
        applies_to=tuple(row.get("applies_to") or ()),
        requires=row.get("requires"),
        severity=row["severity"],
        params=dict(row.get("params") or {}),
        title_he=row["title_he"],
        message_he=row["message_he"],
        enabled=bool(row.get("enabled", True)),
        approval=row.get("approval"),
    )


@cache
def _file() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(resources.files(__package__).joinpath("rules.json").read_text(encoding="utf-8"))
    return data


def default() -> Pack:
    data = _file()
    rules = [_rule(r) for r in data["rules"]]
    return Pack(version=data["version"], rules={r.rule_id: r for r in rules})


def rows() -> list[dict[str, Any]]:
    """What `seed_global` writes: one row per rule and version."""
    return [r.as_row() for r in default().rules.values()]


def load(session: Session) -> Pack:
    """The global pack from `validator_rules`, the latest version of each rule. The file when the table is empty."""
    found = session.scalars(select(m.ValidatorRule).order_by(m.ValidatorRule.rule_id, m.ValidatorRule.version)).all()
    if not found:
        return default()
    latest: dict[str, Rule] = {}
    for r in found:
        latest[r.rule_id] = _rule(
            {
                "rule_id": r.rule_id,
                "version": r.version,
                "category": r.category,
                "applies_to": r.applies_to,
                "requires": r.requires,
                "severity": r.severity,
                "params": r.params,
                "title_he": r.title_he,
                "message_he": r.message_he,
                "enabled": r.enabled,
                "approval": r.approval,
            }
        )
    return Pack(version=_file()["version"], rules=latest)


def with_overrides(pack: Pack, overrides: list[tuple[str, bool | None, dict[str, Any]]], tenant_id: str) -> Pack:
    """06 §6.5 item 2: the factory's switches and parameters over the global pack. `enabled` None keeps the global
    switch; parameters merge key by key."""
    if not overrides:
        return pack
    rules = dict(pack.rules)
    off: set[str] = set()
    for rule_id, enabled, params in overrides:
        rule = rules.get(rule_id)
        if rule is None:
            continue
        if params:
            rules[rule_id] = replace(rule, params={**rule.params, **params})
        if enabled is False:
            off.add(rule_id)
        elif enabled is True and not rule.enabled:
            rules[rule_id] = replace(rules[rule_id], enabled=True)
    digest = hashlib.sha256(
        json.dumps(sorted((r, e, p) for r, e, p in overrides), sort_keys=True, default=str).encode()
    ).hexdigest()[:8]
    return Pack(version=pack.version, rules=rules, tenant_version=f"{tenant_id}-{digest}", turned_off=frozenset(off))


def for_tenant(session: Session, tenant_id: str) -> Pack:
    """Read under the tenant's session: RLS shows only this factory's overrides."""
    found = session.execute(
        select(m.TenantRuleOverride.rule_id, m.TenantRuleOverride.enabled, m.TenantRuleOverride.params).where(
            m.TenantRuleOverride.tenant_id == tenant_id
        )
    ).all()
    return with_overrides(load(session), [(r, e, dict(p or {})) for r, e, p in found], tenant_id)
