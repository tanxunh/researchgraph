from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ["APP_ENV"] = "test"
os.environ["EMBEDDING_PROVIDER"] = "fake"
os.environ["EMBEDDING_DIMENSION"] = "8"
os.environ["EMBEDDING_VERSION"] = "hard-eval-v1"
os.environ["GRAPH_EXTRACTOR_MODE"] = "mock"
os.environ["GRAPH_EXTRACTOR_VERSION"] = "hard-eval-mock-v1"
os.environ["DATABASE_URL"] = os.environ.get("HARD_EVAL_DATABASE_URL", "sqlite:////tmp/lifeflow_hard_eval.db")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal, create_db_tables  # noqa: E402
from app.services.evaluation.retrieval_evaluator import RetrievalEvaluator  # noqa: E402
from scripts.seed_hard_evaluation import current_counts, reset_seeded_docs, resolve_cases, seed_docs  # noqa: E402

RESOLVED_CASES_PATH = BACKEND_ROOT / "tests" / "fixtures" / "hard_eval" / "resolved_cases.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--seed", action="store_true")
    parser.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()
    create_db_tables()
    db = SessionLocal()
    try:
        if args.reset:
            print("reset=" + json.dumps(reset_seeded_docs(db), ensure_ascii=False))
        if args.seed:
            print("seed=" + json.dumps(seed_docs(db), ensure_ascii=False))
            print("resolve=" + json.dumps(resolve_cases(db), ensure_ascii=False))
        if args.evaluate:
            if not RESOLVED_CASES_PATH.exists():
                raise RuntimeError("resolved_cases.jsonl is missing; run with --seed first")
            report = RetrievalEvaluator(db).run(str(RESOLVED_CASES_PATH), top_k=10, report_name="hard_retrieval_evaluation")
            print(f"evaluation_run_id={report.get('evaluation_run_id')} case_count={report['case_count']}")
            for mode, metrics in report["modes"].items():
                print(
                    f"{mode}: Recall@5={metrics['Recall@5']} Recall@10={metrics['Recall@10']} "
                    f"MRR@10={metrics['MRR@10']} CompleteEvidence={metrics['Complete Evidence Recall']} "
                    f"HitRate@5={metrics['HitRate@5']} Valid={metrics['valid_scored_cases']} "
                    f"AvgLatency={metrics['Average Latency']}ms P95={metrics['P95 Latency']}ms"
                )
            print("reports=reports/hard_retrieval_evaluation.json,reports/hard_retrieval_evaluation.md")
        if not (args.reset or args.seed or args.evaluate):
            print("counts=" + json.dumps(current_counts(db), ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    main()
