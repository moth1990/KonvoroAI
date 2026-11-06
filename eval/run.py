"""`make eval`: run the pipeline on every golden drawing, score it, write the report, compare with the baseline.

    EVAL_MODE=replay (default)  the model's answers come from eval/cassettes/: deterministic and free (CI)
    EVAL_MODE=live              real Claude (ANTHROPIC_API_KEY); with EVAL_RECORD=1 its answers become cassettes
    EVAL_RECORD=missing         live, but only calls with no cassette yet go to the model (S10)
    EVAL_MAX_USD=20             a live run stops once its calls cost this much at list prices
    EVAL_CATALOG_LINES=1        the eval factory has `catalog_lines` on (S27b, 13 §3 rule 6: both states of a flag
                                that moves the pipeline); the committed baseline is the flag off

Each run recreates the `konboro_eval` database and uploads every drawing to one throwaway tenant, as a user would.
Then the coordinator's own stage code runs every stage in order in this process (`Pipeline.run_inline`), with no
queue. Needs `make up`.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Engine, create_engine, select, update
from sqlalchemy.orm import Session

from konboro.contracts.detection import DetectionResult
from konboro.contracts.extraction import ExtractionResult
from konboro.contracts.intake import IntakeResult
from konboro.contracts.matching import MatchingResult
from konboro.contracts.merge import MergeResult
from konboro.contracts.pricing import QuoteVersionResult
from konboro.contracts.validation import ValidationResult
from konboro.db import models as m
from konboro.db.admin import database_dsn, fresh_database
from konboro.db.ids import new_id
from konboro.db.seed import seed_global
from konboro.db.session import app_engine, tenant_session
from konboro.pipeline.audit.differences import Outcome, audit
from konboro.pipeline.audit.step import drawn_components, read_quote_bytes
from konboro.pipeline.context import M
from konboro.pipeline.coordinator import Pipeline
from konboro.pipeline.pricing import load as pricing_load
from konboro.pipeline.validation import pack as rule_pack
from konboro.services import drawings
from konboro.services.intake import detect_format
from konboro.services.llm import EvalMode, eval_providers, usage_recorder
from konboro.services.queue import Queue, StageMessage
from konboro.services.storage import Storage
from konboro.settings import Settings
from konboro_llm import LLMClient

from . import backtest, chat, compare, report
from . import build as builder
from .canonical import GoldenDrawing, Prediction
from .labelled import labelled_matches
from .normalizers import GOLDEN, load_all
from .predict import prediction
from .validation import canon_findings, labelled_validation, validation_counts

EVAL = Path(__file__).resolve().parent
CASSETTES = EVAL / "cassettes"
REPORTS = EVAL / "reports"
DATABASE = "konboro_eval"


def eval_settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,  # hermetic: a developer's .env must not change the scores
        env="test",
        s3_endpoint=os.environ.get("KONBORO_S3_ENDPOINT", "http://localhost:9000"),
        sqs_endpoint=os.environ.get("KONBORO_SQS_ENDPOINT", "http://localhost:9324"),
        sqs_queue_prefix="eval-",  # never used: no stage goes through a queue here
        s3_bucket="konboro-eval",  # its own bucket, emptied at start (Storage.reset_local_bucket)
    )


def prepare() -> Engine:
    """A fresh, migrated konboro_eval with plans, flags and VAT. Returns the app-role engine."""
    owner = create_engine(fresh_database(DATABASE))
    with Session(owner) as s, s.begin():
        seed_global(s)
    owner.dispose()
    return app_engine(database_dsn(DATABASE, role="app"))


# Stage 5's factory (S20): the golden set's factories quote ABB; Schneider may stand in; a breaker's curve C and 6 kA,
# an RCD's type A, when the drawing writes none. No price list: every brand counts as priced (`matching.query`).
FACTORY: dict[str, Any] = {
    "brand_preferences": {"*": "ABB"},
    "attribute_defaults": {"circuit_breaker": {"curve": "C", "breaking_capacity_ka": 6}, "rcd": {"rcd_type": "A"}},
    "matching": {"alternate_brands": {"*": ["Schneider"]}},
    "enclosure_includes_default": backtest.INCLUDES,  # the golden quotes' factory (S22 decision 1)
}


def add_tenant(engine: Engine) -> tuple[str, str]:
    tenant_id, user_id = new_id("tnt"), new_id("usr")
    with tenant_session(tenant_id, engine) as s:
        s.add(m.Tenant(id=tenant_id, name="מפעל הערכה", plan_id="trial"))
        s.flush()
        s.add(m.User(id=user_id, tenant_id=tenant_id, email="eval@konboro.local", display_name="הערכה"))
        s.add(m.TenantSettings(tenant_id=tenant_id, **FACTORY))
        # no price list here, so every SKU would lack a cost: the factory turns the check off (06 §6.5 item 2)
        s.add(m.TenantRuleOverride(tenant_id=tenant_id, rule_id="DATA_NO_COST_PRICE", enabled=False))
        s.add(m.TenantPlanOverride(tenant_id=tenant_id, monthly_quote_limit=1000))
        if backtest.CATALOG_LINES:  # S27b: one line per product, a product not in the catalog waits (13 §4.10)
            s.add(m.TenantFeatureOverride(tenant_id=tenant_id, flag_key="catalog_lines", enabled=True, reason="eval"))
        s.flush()
        # it quotes no labor, terminals, labels, rails or consumables as lines: only the enclosure rule (S22 decision 1)
        pricing_load.ensure_rules(s, tenant_id)
        s.execute(update(m.DerivedItemRule).where(m.DerivedItemRule.rule_key != "enclosure").values(enabled=False))
    return tenant_id, user_id


def run_drawing(
    pipeline: Pipeline, tenant_id: str, user_id: str, label: GoldenDrawing, golden: Path
) -> tuple[Prediction, backtest.Material | None]:
    data = (golden / label.id / label.file).read_bytes()
    with tenant_session(tenant_id, pipeline.engine) as s:
        upload = drawings.create_upload(
            s, pipeline.storage, tenant_id=tenant_id, user_id=user_id, files=[(label.file, data)], project_name=label.id
        )
        drawing_id, trace_id = upload.drawing.id, upload.drawing.trace_id
    pipeline.run_inline(StageMessage(drawing_id=drawing_id, tenant_id=tenant_id, stage=1, trace_id=str(trace_id)))

    def output(stage: int, model: type[M]) -> M:
        with tenant_session(tenant_id, pipeline.engine) as s:
            key = s.scalar(
                select(m.StageRun.output_key).where(m.StageRun.drawing_id == drawing_id, m.StageRun.stage == stage)
            )
        assert key is not None, f"stage {stage} of {label.id} wrote nothing"  # noqa: S101
        return model.model_validate_json(pipeline.storage.get(tenant_id, key))

    intake, merge = output(1, IntakeResult), output(4, MergeResult)
    folder = golden / label.id
    outcome = audit_golden(pipeline, tenant_id, drawing_id, intake, merge, folder) if label.audit else None
    differences = outcome.differences if outcome is not None else None
    labelled, lab = labelled_matches(pipeline, tenant_id, drawing_id, label, intake)
    with tenant_session(tenant_id, pipeline.engine) as s:
        pack = rule_pack.for_tenant(s, tenant_id)
    checked = output(6, ValidationResult)
    matched = output(5, MatchingResult)
    material = None
    if outcome is not None:
        with tenant_session(tenant_id, pipeline.engine) as s:
            items = pricing_load.catalog_items(s, matched, pricing_load.DERIVED_FAMILIES)
        material = backtest.Material(
            label.id, intake, merge, matched, checked, items, pricing_load.requirements(intake), outcome.lines
        )
    labelled_findings, injected = labelled_validation(lab, pack)
    pred = prediction(
        intake,
        merge,
        output(7, QuoteVersionResult),
        output(2, ExtractionResult),
        output(3, DetectionResult),
        differences,
        matched,
        labelled,
    )
    return pred.model_copy(
        update={
            "findings": canon_findings(checked, merge.components, pack),
            "validation": validation_counts(checked),
            "labelled_findings": labelled_findings,
            "injected": injected,
        }
    ), material


AUXILIARY = frozenset({"terminal"})  # a new tenant's default (S15 decision 4)
BACKTEST_DATE = date(2026, 11, 3)


def audit_golden(
    pipeline: Pipeline, tenant_id: str, drawing_id: str, intake: IntakeResult, merge: MergeResult, folder: Path
) -> Outcome | None:
    """The audit of the factory's real quote (11 §10), on this run's own stage 1 and 4: the same code as the audit
    step, without a second run of stages 1–4. The quote is read as the step reads it, through the cassettes."""
    quote = next(iter(sorted(folder.glob("actual_quote_*.*"))), None)
    if quote is None:
        return None
    data = quote.read_bytes()
    fmt = detect_format(data)
    assert fmt is not None and fmt not in ("dwg", "dxf", "zip"), quote  # noqa: S101
    llm = LLMClient(pipeline.llm_providers, on_call=usage_recorder(pipeline.engine, tenant_id, drawing_id))
    read = read_quote_bytes(llm, tenant_id, fmt, data, new_id("fil"), hashlib.sha256(data).hexdigest())
    pages = {p.page_id: p.page_no for p in intake.pages}
    return audit(read, drawn_components(pages, merge), AUXILIARY)


def evaluate(
    mode: EvalMode = "replay",
    *,
    record: bool | Literal["missing"] = False,
    max_usd: float | None = None,
    golden: Path = GOLDEN,
) -> report.Report:
    # a bad mode fails before the database is dropped
    providers = eval_providers(mode, CASSETTES, record=record, max_usd=max_usd)
    settings = eval_settings()
    engine = prepare()
    storage = Storage(settings)
    storage.reset_local_bucket()
    pipeline = Pipeline(settings, engine, storage, Queue(settings), llm_providers=providers)
    tenant_id, user_id = add_tenant(engine)
    labels = load_all(golden)
    runs = [(label, *run_drawing(pipeline, tenant_id, user_id, label, golden)) for label in labels]
    chat_scores, chat_rows = chat.run(engine, storage, providers)  # the chat's test set (08 §13.1, S25)
    build_scores, build_rows, home_rows = builder.run(engine, storage, providers)  # 13 §4.2–4.3 (S27)
    engine.dispose()
    # the backtest's date is fixed, so a replay prices the same to the agora (07 §10.1)
    priced = backtest.run([mat for _, _, mat in runs if mat is not None], BACKTEST_DATE)
    results = [(label, _with_backtest(pred, priced.get(label.id))) for label, pred, _ in runs]
    out = report.build(results)
    out["totals"]["all"][chat.SECTION] = {k: v.model_dump() for k, v in chat_scores.items()}
    out["chat_cases"] = chat_rows
    out["totals"]["all"][builder.SECTION] = {k: v.model_dump() for k, v in build_scores.items()}
    out["build_cases"] = build_rows
    out["home_cases"] = home_rows
    return out


def _with_backtest(pred: Prediction, priced: dict[str, str | None] | None) -> Prediction:
    """The backtest's own-quote total is the drawing's predicted total (07 §10.2)."""
    if priced is None:
        return pred
    return pred.model_copy(update={"quote_total": Decimal(priced["own_total"] or 0), "backtest": priced})


def _commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            cwd=EVAL,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Golden-set evaluation (dev-strategy §6)")
    parser.add_argument("--out", type=Path, default=REPORTS, help="where <timestamp>.json and .md go")
    parser.add_argument("--baseline", type=Path, default=compare.BASELINE)
    parser.add_argument("--no-compare", action="store_true")
    parser.add_argument("--allow-regression", action="store_true")
    parser.add_argument("--write-baseline", action="store_true", help="make this run's metrics the new baseline")
    args = parser.parse_args(argv)

    mode = os.environ.get("EVAL_MODE", "replay")
    if mode not in ("replay", "live"):
        parser.error(f"EVAL_MODE must be replay or live, not {mode!r}")
    flag = os.environ.get("EVAL_RECORD")
    record: bool | Literal["missing"] = "missing" if flag == "missing" else flag == "1"
    max_usd = float(os.environ["EVAL_MAX_USD"]) if os.environ.get("EVAL_MAX_USD") else None
    now = datetime.now(UTC)
    result = evaluate(mode, record=record, max_usd=max_usd)  # type: ignore[arg-type]
    result["meta"] = {
        "created_at": now.isoformat(timespec="seconds"),
        "mode": mode,
        "record": record,
        "commit": _commit(),
    }

    md = report.markdown(result) + "\n" + chat.markdown(result["totals"]["all"][chat.SECTION], result["chat_cases"])
    md += "\n" + builder.markdown(result["totals"]["all"][builder.SECTION], result["build_cases"], result["home_cases"])
    comparison = None
    if not args.no_compare and args.baseline.exists():
        comparison = compare.compare(result, json.loads(args.baseline.read_text(encoding="utf-8")))
        md += "\n" + compare.markdown(comparison)

    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.out / now.strftime("%Y%m%dT%H%M%SZ")
    stem.with_suffix(".json").write_text(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2) + "\n")
    stem.with_suffix(".md").write_text(md, encoding="utf-8")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as f:
            f.write(md)
    if args.write_baseline:
        args.baseline.write_text(report.metrics_json(result) + "\n", encoding="utf-8")
    print(md)
    print(f"report: {stem}.json and .md")

    if comparison is not None and not comparison.ok:
        print(f"{len(comparison.regressions)} metric(s) got worse than the baseline.", file=sys.stderr)
        return 0 if args.allow_regression else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
