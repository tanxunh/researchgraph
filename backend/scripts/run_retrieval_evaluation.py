from __future__ import annotations

from app.core.database import SessionLocal
from app.services.evaluation.retrieval_evaluator import RetrievalEvaluator


if __name__ == "__main__":
    db = SessionLocal()
    try:
        report = RetrievalEvaluator(db).run("backend/tests/fixtures/retrieval_eval_cases.jsonl", top_k=10)
        print(f"evaluation_run_id={report.get('evaluation_run_id')} case_count={report['case_count']}")
        for mode, metrics in report["modes"].items():
            print(f"{mode}: Recall@10={metrics['Recall@10']} MRR@10={metrics['MRR@10']} AvgLatency={metrics['Average Latency']}ms")
    finally:
        db.close()
