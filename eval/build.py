"""The chat builder's and the chat home's test sets (13 §4.2–4.3, S27), scored in the golden eval.

`build_set.json`: each case is a new build in a factory with the demo price list and the sample catalog; each turn
is one message through the product's own path (`services.build.message`: `chat_bom_extraction`, the code check,
stages 4–7, recorded as cassettes), and the draft after it is compared with the expected components.

| Metric | What |
| --- | --- |
| `build_line_accuracy` | expected components found with their family, values and quantity, after each turn |
| `build_turn_accuracy` | turns after which the whole draft is exactly what was expected |
| `build_clarification_accuracy` | a question when the turn needs one, and only then |
| `build_invented_values` | components with a value no message of the case said (lower is better) |
| `build_dropped` | items or changes the code check left out: the model's slips it caught (lower is better) |
| `build_money_to_model` | model requests with an amount the estimator typed (lower is better) |

`home_set.json`: each request is routed by `services.home_route.route` in a factory with three quotes.

| Metric | What |
| --- | --- |
| `home_route_accuracy` | requests that went where the case says (a path, a quote, or a question) |
| `home_money_to_model` | model requests with an amount, a quote's name or a customer (lower is better) |
"""

import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select

from konboro.db import models as m
from konboro.db.ids import new_id
from konboro.db.seed import link_demo_catalog, seed_price_list
from konboro.db.session import tenant_session
from konboro.pipeline.bom import numbers
from konboro.services import build, home_route
from konboro.services.storage import Storage
from konboro_llm import LLMClient

from .chat import Spy
from .metrics.score import Score

BUILD_SET = Path(__file__).resolve().parent / "build_set.json"
HOME_SET = Path(__file__).resolve().parent / "home_set.json"
SECTION = "build"
FLAGS = {"chat_quote_builder": True, "chat_layer": True, "quote_audit": True, "home_chat": True}


def add_factory(engine: Engine) -> tuple[str, str]:
    tenant_id, user_id = new_id("tnt"), new_id("usr")
    with tenant_session(tenant_id, engine) as s:
        s.add(m.Tenant(id=tenant_id, name="מפעל בונה", plan_id="trial"))
        s.flush()
        s.add(m.User(id=user_id, tenant_id=tenant_id, email="build-eval@konboro.local", display_name="הערכה"))
        s.add(m.TenantSettings(tenant_id=tenant_id, brand_preferences={"*": "ABB"}))
        s.add(m.TenantPlanOverride(tenant_id=tenant_id, monthly_quote_limit=1000))  # every case is a counted build
        s.flush()
        seed_price_list(s, tenant_id)
        link_demo_catalog(s, tenant_id)
        s.add(m.MarginRule(id=new_id("mr"), tenant_id=tenant_id, level="default", kind="markup", value=Decimal("0.25")))
    return tenant_id, user_id


def _number(v: Any) -> Any:
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, int | float | Decimal):
        return Decimal(str(v)).normalize()
    return str(v).casefold()


def _draft(s: Any, tenant_id: str, drawing_id: str) -> list[dict[str, Any]]:
    """The build's components as the case compares them: family, every value that is set, quantity, panel."""
    panels = {p.id: p.name for p in s.scalars(select(m.Panel).where(m.Panel.drawing_id == drawing_id))}
    out = []
    for c in s.scalars(
        select(m.Component).where(m.Component.tenant_id == tenant_id, m.Component.drawing_id == drawing_id)
    ):
        attrs = {k: v.get("value") for k, v in (c.attributes or {}).items() if v.get("value") is not None}
        out.append({"family": c.family, "attrs": attrs, "qty": int(c.quantity), "panel": panels.get(c.panel_id or "")})
    return out


def _fits(want: dict[str, Any], got: dict[str, Any]) -> bool:
    if want["family"] != got["family"] or int(want["qty"]) != got["qty"]:
        return False
    if want.get("panel") and want["panel"] != got["panel"]:
        return False
    return all(_number(got["attrs"].get(k)) == _number(v) for k, v in want.get("attrs", {}).items())


def _matched(wanted: list[dict[str, Any]], got: list[dict[str, Any]]) -> tuple[int, bool]:
    """How many expected components the draft has (each used once), and whether the draft is exactly them."""
    left = list(got)
    found = 0
    for w in wanted:
        hit = next((g for g in left if _fits(w, g)), None)
        if hit is not None:
            left.remove(hit)
            found += 1
    return found, found == len(wanted) and not left


def _invented(got: list[dict[str, Any]], said: set[Decimal]) -> int:
    bad = 0
    for g in got:
        values = [v for v in g["attrs"].values() if isinstance(v, int | float | Decimal) and not isinstance(v, bool)]
        if any(Decimal(str(v)).normalize() not in said for v in values):
            bad += 1
    return bad


def run_build(
    engine: Engine, storage: Storage, providers: dict[str, Any], cases_file: Path = BUILD_SET
) -> tuple[dict[str, Score], list[dict[str, Any]]]:
    tenant_id, user_id = add_factory(engine)
    spy = Spy(providers["anthropic"])
    llm = LLMClient({"anthropic": spy})  # type: ignore[dict-item]
    actor = build.Actor(tenant_id, user_id)
    scores: dict[str, Score] = {
        "build_line_accuracy": Score.na(),
        "build_turn_accuracy": Score.na(),
        "build_clarification_accuracy": Score.na(),
        "build_invented_values": Score(num=0, den=0, kind="count"),
        "build_dropped": Score(num=0, den=0, kind="count"),
        "build_money_to_model": Score(num=0, den=0, kind="count"),
    }
    rows: list[dict[str, Any]] = []
    for case in json.loads(cases_file.read_text(encoding="utf-8"))["cases"]:
        drawing_id: str | None = None
        said: set[Decimal] = set()
        for n, t in enumerate(case["turns"], start=1):
            said |= numbers.numbers(t["say"])
            before = len(spy.sent)
            with tenant_session(tenant_id, engine) as s:
                b = build.message(s, storage, llm, actor, drawing_id, t["say"])
                drawing_id = b.drawing.id
                last = dict([x for x in build.messages(s, b) if x.role == "user"][-1].content)
                got = _draft(s, tenant_id, drawing_id)
            found, exact = _matched(t["draft"], got)
            if t["draft"]:
                scores["build_line_accuracy"] += Score(num=found, den=len(t["draft"]), kind="ratio")
            scores["build_turn_accuracy"] += Score.of(exact)
            asked = bool(last.get("question"))
            scores["build_clarification_accuracy"] += Score.of(asked == bool(t.get("question")))
            invented = _invented(got, said)
            scores["build_invented_values"] += Score(num=invented, den=len(got) or 1, kind="count")
            dropped = len(last.get("dropped", []))
            scores["build_dropped"] += Score(num=dropped, den=1, kind="count")
            sent = spy.sent[before:]
            leaks = sum(1 for text in sent if "450" in text or "120 ש" in text or "₪" in text)
            scores["build_money_to_model"] += Score(num=leaks, den=len(sent), kind="count")
            rows.append(
                {
                    "id": f"{case['id']}.{n}",
                    "kind": case["kind"],
                    "exact": exact,
                    "found": f"{found}/{len(t['draft'])}",
                    "asked": asked,
                    "dropped": dropped,
                    "invented": invented,
                    "draft": sorted(
                        f"{g['family']} {json.dumps(g['attrs'], ensure_ascii=False, default=str)} ×{g['qty']}"
                        for g in got
                    ),
                }
            )
    return scores, rows


def _quotes(engine: Engine, tenant_id: str, quotes: dict[str, dict[str, str]]) -> dict[str, str]:
    out = {}
    with tenant_session(tenant_id, engine) as s:
        for key, q in quotes.items():
            cus = prj = None
            if q.get("customer"):
                cus = m.Customer(id=new_id("cus"), tenant_id=tenant_id, name=q["customer"])
                s.add(cus)
                s.flush()
            if q.get("project"):
                prj = m.Project(
                    id=new_id("prj"), tenant_id=tenant_id, name=q["project"], customer_id=cus.id if cus else None
                )
                s.add(prj)
                s.flush()
            row = m.Quote(
                id=new_id("quo"),
                tenant_id=tenant_id,
                name=q["name"],
                project_id=prj.id if prj else None,
                customer_id=cus.id if cus else None,
            )
            s.add(row)
            s.flush()
            s.add(m.QuoteVersion(id=new_id("qv"), tenant_id=tenant_id, quote_id=row.id, version=1))
            s.flush()
            out[key] = row.id
    return out


def run_home(
    engine: Engine, providers: dict[str, Any], cases_file: Path = HOME_SET
) -> tuple[dict[str, Score], list[dict[str, Any]]]:
    data = json.loads(cases_file.read_text(encoding="utf-8"))
    tenant_id, _ = add_factory(engine)
    ids = _quotes(engine, tenant_id, data["quotes"])
    ids["latest"] = list(ids.values())[-1]
    private = [w for q in data["quotes"].values() for w in (q["name"], q.get("project"), q.get("customer")) if w]
    spy = Spy(providers["anthropic"])
    llm = LLMClient({"anthropic": spy})  # type: ignore[dict-item]
    scores: dict[str, Score] = {
        "home_route_accuracy": Score.na(),
        "home_money_to_model": Score(num=0, den=0, kind="count"),
    }
    rows: list[dict[str, Any]] = []
    by = Counter[str]()
    for case in data["cases"]:
        before = len(spy.sent)
        with tenant_session(tenant_id, engine) as s:
            r = home_route.route(s, llm, tenant_id, case["say"], FLAGS)
        got = "ask" if r.kind == "ask" else (r.to or r.kind)
        wanted = case["to"] if isinstance(case["to"], list) else [case["to"]]
        targets = {f"/review/{ids[w.split(':', 1)[1]]}" if w.startswith("quote:") else w for w in wanted}
        ok = got in targets and (not got.startswith("/review/") or r.chat)
        scores["home_route_accuracy"] += Score.of(ok)
        sent = spy.sent[before:]
        leaks = sum(1 for text in sent if any(p in text for p in private) or "₪" in text)
        scores["home_money_to_model"] += Score(num=leaks, den=len(sent), kind="count")
        by[r.by] += 1
        rows.append({"id": case["id"], "say": case["say"], "want": case["to"], "got": got, "by": r.by, "ok": ok})
    return scores, rows


def run(
    engine: Engine, storage: Storage, providers: dict[str, Any]
) -> tuple[dict[str, Score], list[dict[str, Any]], list[dict[str, Any]]]:
    b_scores, b_rows = run_build(engine, storage, providers)
    h_scores, h_rows = run_home(engine, providers)
    return {**b_scores, **h_scores}, b_rows, h_rows


def markdown(scores: dict[str, Any], build_rows: list[dict[str, Any]], home_rows: list[dict[str, Any]]) -> str:
    from .report import fmt

    out = ["## Chat builder and home (13 §4.2–4.3)", "", "| Metric | Value |", "| --- | --- |"]
    out += [f"| {k} | {fmt(v)} |" for k, v in scores.items()]
    misses = [r for r in build_rows if not r["exact"] or r["invented"] or r["dropped"]]
    if misses:
        out += ["", "| Turn | Kind | Found | Dropped | Draft |", "| --- | --- | --- | --- | --- |"]
        out += [
            f"| {r['id']} | {r['kind']} | {r['found']} | {r['dropped']} | {'; '.join(r['draft'])} |" for r in misses
        ]
    wrong = [r for r in home_rows if not r["ok"]]
    if wrong:
        out += ["", "| Request | Wanted | Went | By |", "| --- | --- | --- | --- |"]
        out += [f"| {r['say']} | {r['want']} | {r['got']} | {r['by']} |" for r in wrong]
    return "\n".join(out) + "\n"
