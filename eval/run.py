"""`make eval`: run the pipeline on every golden drawing, score it, write the report, compare with the baseline.

    EVAL_MODE=replay (default)  the model's answers come from eval/cassettes/: deterministic and free (CI)
    EVAL_MODE=live              real Claude (ANTHROPIC_API_KEY); with EVAL_RECORD=1 its answers become cassettes
    EVAL_RECORD=missing         live, but only calls with no cassette yet go to the model (S10)
    EVAL_MAX_USD=20             a live run stops once its calls cost this much at list prices

Each run recreates the `konboro_eval` database and uploads every drawing to one throwaway tenant, as a user would.
Then the coordinator's own stage code runs every stage in order in this process (`Pipeline.run_inline`), with no
queue. Needs `make up`.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from konboro.contracts.extraction import ExtractionResult
from konboro.contracts.intake import IntakeResult
from konboro.contracts.merge import MergeResult
from konboro.contracts.pricing import QuoteVersionResult
from konboro.db import models as m
from konboro.db.admin import database_dsn, fresh_database
from konboro.db.ids import new_id
from konboro.db.seed import seed_global
from konboro.db.session import app_engine, tenant_session
from konboro.pipeline.context import M
from konboro.pipeline.coordinator import Pipeline
from konboro.services import drawings
from konboro.services.llm import EvalMode, eval_providers
from konboro.services.queue import Queue, StageMessage
from konboro.services.storage import Storage
from konboro.settings import Settings

from . import compare, report
from .canonical import GoldenDrawing, Prediction
from .normalizers import GOLDEN, load_all
from .predict import prediction

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


def add_tenant(engine: Engine) -> tuple[str, str]:
    tenant_id, user_id = new_id("tnt"), new_id("usr")
    with tenant_session(tenant_id, engine) as s:
        s.add(m.Tenant(id=tenant_id, name="מפעל הערכה", plan_id="trial"))
        s.flush()
        s.add(m.User(id=user_id, tenant_id=tenant_id, email="eval@konboro.local", display_name="הערכה"))
        s.add(m.TenantSettings(tenant_id=tenant_id))
        s.add(m.TenantPlanOverride(tenant_id=tenant_id, monthly_quote_limit=1000))
    return tenant_id, user_id


def run_drawing(pipeline: Pipeline, tenant_id: str, user_id: str, label: GoldenDrawing, golden: Path) -> Prediction:
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

    return prediction(
        output(1, IntakeResult), output(4, MergeResult), output(7, QuoteVersionResult), output(2, ExtractionResult)
    )


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
    results = [(label, run_drawing(pipeline, tenant_id, user_id, label, golden)) for label in labels]
    engine.dispose()
    return report.build(results)


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

    md = report.markdown(result)
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
