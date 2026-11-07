"""06 §5: the validator's flow for one drawing, and the rules-only re-run for one panel after an edit (06 §6.3).

    6.1 the panel model (`model.py`) → 6.2 the rules (`checks.py`) → 6.3 the BOM cross-check (`crosscheck.py`)
    → 6.4 the agent per panel (`agent.py`) → 6.5 merge, caps on the rows' colour, panel summaries (here)

A rule whose data is not there (`requires`) does not run and is listed in `checks_skipped` with why (06 §7). A rule
that raises is skipped too, with `rule_execution_failed` (06 §8); the others still run. A safety-net rule of category
D that fires (`bug_net`) is a bug in an earlier stage: the finding is shown, and `internal_consistency_violation`
tells the team (06 §6.2, §8).

An issue's id is a digest of what it says (drawing, rule, panel, components, values), so a re-run gives the same
ids, and a finding the user dismissed stays dismissed while it says the same thing.
"""

import hashlib
import json
import logging
import string
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from konboro.contracts.common import StageIssue
from konboro.contracts.validation import (
    BomCrosscheck,
    Issue,
    PanelSummary,
    RowStatusCap,
    SkippedCheck,
    ValidationResult,
)
from konboro.pipeline.association.schemas import Schemas
from konboro_llm import LLMAccountError

from . import agent as agent_mod
from . import crosscheck
from .checks import CHECKS, Ctx, Hit
from .model import DrawingModel, PanelModel, compress
from .pack import Pack, Rule

log = logging.getLogger("konboro.pipeline.validation")

AGENT_CATEGORY = {
    "suspicious_quantity": "C",
    "missing_component": "B",
    "inconsistent_attributes": "D",
    "wrong_family": "D",
    "other": "B",
}
AGENT_TITLES = {
    "suspicious_quantity": "כמות שכדאי לבדוק",
    "missing_component": "רכיב שנראה חסר בהצעה",
    "inconsistent_attributes": "ערך שלא מתאים לשאר הלוח",
    "wrong_family": "ייתכן שסוג הרכיב שגוי",
    "other": "הערה של הבודק",
}
STAGE_ISSUES = {
    "rule_execution_failed": ("warning", "בדיקה {rule_id} נכשלה ודולגה. הצוות קיבל התראה."),
    "agent_unavailable": ("info", "הבודק הנוסף לא היה זמין ללוח {panel}. רצו רק הכללים."),
    "internal_consistency_violation": ("error", "בדיקת עקביות {rule_id} מצאה סתירה בין השלבים. הצוות קיבל התראה."),
    "bom_parse_failed": ("info", "לא הצלחנו לקרוא את כתב הכמויות של המתכנן. ההשוואה אליו דולגה."),
}
CAP = {"error": "red", "warning": "yellow"}
NOT_SHOWN = frozenset({"DATA_NO_COST_PRICE"})  # 06 §12: nothing about prices reaches the model, not even "no price"


@dataclass
class AgentCall:
    """What the stage gives the engine for one panel: the call, and how a box in its picture maps to the page."""

    look: agent_mod.Look
    picture: tuple[int, int] | None = None
    to_points: Callable[[list[float]], tuple[float, float, float, float]] | None = None
    page_id: str | None = None


@dataclass
class Run:
    issues: list[Issue] = field(default_factory=list)
    run: list[str] = field(default_factory=list)
    skipped: list[SkippedCheck] = field(default_factory=list)
    stage_issues: list[StageIssue] = field(default_factory=list)
    agent_calls: int = 0
    bom: BomCrosscheck = field(default_factory=lambda: BomCrosscheck(available=False))


class _Values(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return ""


def _show(v: Any) -> Any:
    if isinstance(v, bool):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return compress(v)
    return v


def fill(template: str, values: dict[str, Any]) -> str:
    return string.Formatter().vformat(template, (), _Values({k: _show(v) for k, v in values.items()})).strip()


def _json(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): _json(x) for k, x in v.items()}
    if isinstance(v, list | tuple | set):
        return [_json(x) for x in v]
    if v is None or isinstance(v, str | int | float | bool):
        return v
    return str(v)


def issue_id(drawing_id: str, rule_id: str, panel_id: str | None, hit: Hit) -> str:
    key = json.dumps(
        [drawing_id, rule_id, panel_id, sorted(hit.component_ids), sorted(hit.instance_ids), _json(hit.values)],
        sort_keys=True,
        ensure_ascii=False,
    )
    return "iss_" + hashlib.sha256(key.encode()).hexdigest()[:24]


def _where(panel: PanelModel, hit: Hit) -> tuple[list[str], str | None, tuple[float, float, float, float] | None]:
    """The instances to mark, the page and the box: the hit's own, else its components' first drawn instance."""
    ids = set(hit.component_ids)
    instances = [i for i in panel.instances if i.instance_id in set(hit.instance_ids)] or [
        i for i in panel.instances if i.component_id in ids
    ]
    instances += [m for m in panel.missing if m.instance_id in set(hit.instance_ids)]  # type: ignore[misc]
    drawn = next((i for i in instances if i.bbox is not None), None)
    bbox = hit.values.get("bbox")
    page = hit.page_id or (drawn.page_id if drawn else None)
    box = tuple(bbox) if isinstance(bbox, list) else (drawn.bbox if drawn else None)
    return [i.instance_id for i in instances], page, box


def _issue(drawing: DrawingModel, panel: PanelModel, rule: Rule, hit: Hit, source: str) -> Issue:
    instances, page, box = _where(panel, hit)
    values = {k: _json(v) for k, v in hit.values.items() if k != "bbox"}
    return Issue(
        issue_id=issue_id(drawing.drawing_id, rule.rule_id, panel.panel_id, hit),
        source=source,  # type: ignore[arg-type]
        rule_id=rule.rule_id,
        rule_version=rule.version,
        category=rule.category,
        severity=(hit.severity or rule.severity),  # type: ignore[arg-type]
        panel_id=panel.panel_id,
        component_ids=list(dict.fromkeys(hit.component_ids)),
        instance_ids=instances,
        bbox=box,
        page_id=page,
        title=fill(rule.title_he, hit.values),
        message=fill(rule.message_he, hit.values),
        values=values,
        confidence=1.0,
    )


def _available(rule: Rule, panel: PanelModel, drawing: DrawingModel) -> str | None:
    """Why the rule cannot run on this panel, or None."""
    if rule.category == "E" and drawing.bom_is_source:
        return "bom_is_the_source"
    if rule.requires == "wire_graph" and not panel.hierarchy:
        return "wire_graph_unavailable"
    if rule.requires == "bom_table" and not drawing.bom_available:
        return "bom_table_unavailable"
    if rule.requires == "front_view" and panel.front is None:
        return "front_view_unavailable"
    if rule.requires == "text_layer" and (panel.spans is None or drawing.bom_is_source):
        return "text_layer_unavailable"
    return None


def _stage_issue(code: str, **values: Any) -> StageIssue:
    severity, message = STAGE_ISSUES[code]
    return StageIssue(code=code, severity=severity, message=message.format(**values))  # type: ignore[arg-type]


def rules_on_panel(
    drawing: DrawingModel, panel: PanelModel, pack: Pack, schemas: Schemas, out: Run
) -> list[tuple[Rule, Hit]]:
    ctx = Ctx(drawing, schemas)
    found: list[tuple[Rule, Hit]] = []
    for rule in pack.active():
        if rule.category == "E":
            continue  # the cross-check below
        reason = _available(rule, panel, drawing)
        if reason is not None:
            out.skipped.append(SkippedCheck(rule_id=rule.rule_id, panel_id=panel.panel_id, reason=reason))
            continue
        fn = CHECKS.get(rule.rule_id)
        if fn is None:
            out.skipped.append(SkippedCheck(rule_id=rule.rule_id, panel_id=panel.panel_id, reason="no_check"))
            continue
        try:
            hits = fn(panel, rule, ctx)
        except Exception:
            log.exception("rule %s failed on %s", rule.rule_id, panel.panel_id)
            out.skipped.append(
                SkippedCheck(rule_id=rule.rule_id, panel_id=panel.panel_id, reason="rule_execution_failed")
            )
            out.stage_issues.append(_stage_issue("rule_execution_failed", rule_id=rule.rule_id))
            continue
        if rule.rule_id not in out.run:
            out.run.append(rule.rule_id)
        found += [(rule, h) for h in hits]
        if hits and rule.params.get("bug_net"):
            log.error("internal consistency: %s fired on %s (%d)", rule.rule_id, panel.panel_id, len(hits))
            out.stage_issues.append(_stage_issue("internal_consistency_violation", rule_id=rule.rule_id))
    return found


def _crosscheck(drawing: DrawingModel, pack: Pack, out: Run) -> list[tuple[PanelModel, Rule, Hit]]:
    rules = {r.rule_id: r for r in pack.active() if r.category == "E"}
    if not rules:
        return []
    first = next(iter(drawing.panels.values()), None)
    if not drawing.bom_available or drawing.bom_is_source or first is None:
        reason = "bom_is_the_source" if drawing.bom_is_source else "bom_table_unavailable"
        out.skipped += [SkippedCheck(rule_id=r, panel_id=None, reason=reason) for r in rules]
        return []
    found: list[tuple[PanelModel, Rule, Hit]] = []
    summaries: list[BomCrosscheck] = []
    groups = [(p, p.bom or [], p.devices) for p in drawing.panels.values() if p.bom]
    if drawing.bom_drawing:
        groups.append((first, drawing.bom_drawing, drawing.devices()))
    for panel, rows, devices in groups:
        outcome = crosscheck.compare(rows, devices)
        summaries.append(outcome.summary)
        for rule_id, hits in outcome.hits.items():
            if rule_id in rules:
                found += [(panel, rules[rule_id], h) for h in hits]
    out.run += [r for r in rules if r not in out.run]
    out.bom = BomCrosscheck(
        available=True,
        matched_signatures=sum(s.matched_signatures for s in summaries),
        missing_in_quote=[x for s in summaries for x in s.missing_in_quote],
        extra_in_quote=[x for s in summaries for x in s.extra_in_quote],
        qty_diffs=[x for s in summaries for x in s.qty_diffs],
    )
    return found


def _agent(
    drawing: DrawingModel, panel: PanelModel, call: AgentCall, rule_hits: list[tuple[Rule, Hit]], out: Run
) -> list[Issue]:
    sh = agent_mod.shown(panel)
    shown_hits = [(r, h) for r, h in rule_hits if r.rule_id not in NOT_SHOWN][:40]
    titles = "\n".join(f"- {_issue(drawing, panel, r, h, 'rule').title}" for r, h in shown_hits)
    try:
        answer = call.look(panel.name, sh.components, sh.tree, sh.bom, titles)
    except LLMAccountError:
        raise  # the stage fails rather than reporting the agent away on every panel (BUG-061)
    except Exception:
        log.exception("validator_review failed on %s", panel.panel_id)
        out.stage_issues.append(_stage_issue("agent_unavailable", panel=panel.name))
        return []
    finally:
        out.agent_calls += 1
    issues = []
    for k in agent_mod.check_answer(answer, sh, rule_hits, call.picture, call.to_points, call.page_id):
        rule = Rule(
            rule_id=f"AGENT_{k.type}",
            version=1,
            category=AGENT_CATEGORY[k.type],  # type: ignore[arg-type]
            applies_to=(),
            requires=None,
            severity=k.hit.severity,  # type: ignore[arg-type]
            params={},
            title_he="",
            message_he="",
        )
        devices = [d for d in panel.devices if d.id in set(k.hit.component_ids)]
        tagged = compress([t for d in devices for t in d.component.designators])
        base = _issue(drawing, panel, rule, k.hit, "agent")
        title = f"{tagged}: {AGENT_TITLES[k.type]}" if tagged else AGENT_TITLES[k.type]
        issues.append(
            base.model_copy(update={"title": title, "message": k.message, "confidence": round(k.confidence, 3)})
        )
    return issues


def caps(issues: list[Issue]) -> list[RowStatusCap]:
    """06 §6.5 item 3: error → red, warning → yellow, info → a tag only. Open findings only."""
    worst: dict[str, tuple[str, list[str]]] = {}
    for i in issues:
        cap = CAP.get(i.severity)
        if cap is None or i.status != "open":
            continue
        for c in i.component_ids:
            have, ids = worst.get(c, ("yellow", []))
            worst[c] = ("red" if "red" in (have, cap) else "yellow", [*ids, i.issue_id])
    return [RowStatusCap(component_id=c, max_status=s, issue_ids=ids) for c, (s, ids) in worst.items()]  # type: ignore[arg-type]


def summaries(drawing: DrawingModel, issues: list[Issue]) -> list[PanelSummary]:
    out = []
    for p in drawing.panels.values():
        counts = {"error": 0, "warning": 0, "info": 0}
        for i in issues:
            if i.panel_id == p.panel_id and i.status == "open":
                counts[i.severity] += 1
        out.append(
            PanelSummary(
                panel_id=p.panel_id,
                hierarchy_available=p.hierarchy,
                main_device_component_id=p.main.id if p.main else None,
                issue_counts=counts,
            )
        )
    return out


def _sorted(issues: list[Issue], panels: list[str]) -> list[Issue]:
    """Errors first, then by panel in the drawing's order, rule and what the finding says: never by an id, so two
    runs list the same findings in the same order."""
    order = {"error": 0, "warning": 1, "info": 2}
    place = {p: n for n, p in enumerate(panels)}
    seen: dict[str, Issue] = {}
    for i in issues:
        seen.setdefault(i.issue_id, i)
    return sorted(
        seen.values(),
        key=lambda i: (order[i.severity], place.get(i.panel_id or "", len(place)), i.rule_id, i.title or "", i.message),
    )


def validate(
    drawing: DrawingModel,
    pack: Pack,
    schemas: Schemas,
    agent_for: Callable[[PanelModel], AgentCall | None] | None = None,
    trace_id: str = "trc_local",
) -> ValidationResult:
    out = Run()
    rule_hits: dict[str, list[tuple[Rule, Hit]]] = {}
    for panel in drawing.panels.values():
        rule_hits[panel.panel_id] = rules_on_panel(drawing, panel, pack, schemas, out)
    for panel, rule, hit in _crosscheck(drawing, pack, out):
        rule_hits[panel.panel_id].append((rule, hit))
    issues: list[Issue] = []
    for panel in drawing.panels.values():
        found = rule_hits[panel.panel_id]
        source = {r.rule_id: ("bom_crosscheck" if r.category == "E" else "rule") for r, _ in found}
        issues += [_issue(drawing, panel, r, h, source[r.rule_id]) for r, h in found]
        if agent_for is not None and agent_mod.eligible(panel):
            call = agent_for(panel)
            if call is not None:
                issues += _agent(drawing, panel, call, found, out)
    issues = _sorted(issues, list(drawing.panels))
    return ValidationResult(
        drawing_id=drawing.drawing_id,
        rules_version=pack.version,
        tenant_rules_version=pack.tenant_version,
        issues=issues,
        row_status_caps=caps(issues),
        panel_summaries=summaries(drawing, issues),
        bom_crosscheck=out.bom,
        checks_run=out.run,
        checks_skipped=out.skipped,
        agent_calls=out.agent_calls,
        stage_issues=out.stage_issues,
        trace_id=trace_id,
    )


def revalidate(
    previous: ValidationResult, drawing: DrawingModel, panel_id: str, pack: Pack, schemas: Schemas
) -> ValidationResult:
    """06 §6.3 "after a user action": the rules alone on one panel, under a second. A finding of the panel that no
    longer holds becomes `resolved`; one the user dismissed stays dismissed; the agent's findings and the other panels'
    are kept as they were."""
    panel = drawing.panels[panel_id]
    out = Run(bom=previous.bom_crosscheck)
    hits = rules_on_panel(drawing, panel, pack, schemas, out)
    fresh = {i.issue_id: i for r, h in hits for i in [_issue(drawing, panel, r, h, "rule")]}
    kept: list[Issue] = []
    for i in previous.issues:
        if i.panel_id != panel_id or i.source != "rule":
            kept.append(i)
        elif i.issue_id in fresh:
            kept.append(fresh.pop(i.issue_id).model_copy(update={"status": i.status}))
        elif i.status == "open":
            kept.append(i.model_copy(update={"status": "resolved"}))
        else:
            kept.append(i)
    issues = _sorted(kept + list(fresh.values()), list(drawing.panels))
    skipped = [s for s in previous.checks_skipped if s.panel_id != panel_id] + out.skipped
    return previous.model_copy(
        update={
            "issues": issues,
            "row_status_caps": caps(issues),
            "panel_summaries": summaries(drawing, issues),
            "checks_skipped": skipped,
            "stage_issues": [*previous.stage_issues, *out.stage_issues],
        }
    )
