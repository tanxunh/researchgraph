from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentChunk
from app.models.evaluation import EvaluationRun
from app.services.evaluation.metrics import category_metrics, summarize
from app.services.indexing.version_chunks import membership_query
from app.services.retrieval.retrieval_service import ResearchRetrievalService

# Existing API modes remain compatible; the baseline runner explicitly selects CORE_MODES.
MODES = ["vector", "hybrid", "graph_enhanced"]
CORE_MODES = ["bm25", "dense", "hybrid"]
BACKEND_ROOT = Path(__file__).resolve().parents[3]


class RetrievalEvaluator:
    def __init__(self, db: Session) -> None:
        self.db = db

    def run(self, dataset_path: str, top_k: int = 10, report_name: str = "retrieval_evaluation",
            *, modes: list[str] | None = None, dataset_kind: str = "unverified",
            retrieval=None, timing_metadata: dict | None = None) -> dict:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        modes = MODES if modes is None else modes
        if not modes or any(mode not in {*MODES, *CORE_MODES, "auto"} for mode in modes):
            raise ValueError("Unsupported evaluation mode")
        path = self._dataset_path(dataset_path)
        cases = self._load_cases(str(path))
        gold_ids = {str(key) for c in cases for key in c.get("relevant_chunk_ids", []) if key}
        active_gold = set()
        keys = sorted(gold_ids)
        for start in range(0, len(keys), 200):
            active_gold.update(self.db.scalars(membership_query().with_only_columns(DocumentChunk.stable_chunk_id)
                .where(Document.status == "ready", DocumentChunk.stable_chunk_id.in_(keys[start:start+200]))).all())
        for case in cases:
            gold = case.get("relevant_chunk_ids", [])
            reason = case.get("invalid_reason")
            if not gold:
                reason = reason or "empty_gold"
            elif not set(gold).issubset(active_gold):
                reason = reason or "gold_not_in_current_index"
            if not isinstance(case.get("query"), str) or not case["query"].strip():
                reason = reason or "empty_query"
            case["invalid_reason"] = reason
        retrieval = retrieval or ResearchRetrievalService(self.db)
        mode_reports = {}
        # Evaluate at least ten ranks to make fixed @5/@10 labels meaningful.
        effective_k = max(10, top_k)
        for mode in modes:
            rows = []
            for case in cases:
                valid = case["invalid_reason"] is None
                returned, latency = [], None
                graph_returned, routing = [], {}
                if valid:
                    started = time.perf_counter()
                    result = retrieval.search(case["query"], mode=mode, top_k=effective_k)
                    latency = (time.perf_counter() - started) * 1000
                    returned = [item["chunk_id"] for item in result["results"]]
                    graph_returned = [item["chunk_id"] for item in result["results"] if item.get("graph_paths")]
                    routing = result.get("routing", {})
                rows.append({**case, "valid": valid, "returned_chunk_ids": returned, "latency_ms": latency,
                             "graph_returned_chunk_ids": graph_returned, "routing": routing})
            metrics = summarize(rows)
            metrics.update(cases=rows, category_metrics=category_metrics(rows),
                           failure_examples=[c for c in rows if c["valid"] and
                                             not set(c["relevant_chunk_ids"]).issubset(c["returned_chunk_ids"])][:3])
            mode_reports[mode] = metrics
        valid_count = sum(c["invalid_reason"] is None for c in cases)
        embedding = getattr(retrieval, "_vector_store", None)
        provider = getattr(embedding, "embedding", None)
        report = {
            "dataset_path": str(path), "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "dataset_kind": dataset_kind, "case_count": len(cases), "total_cases": len(cases),
            "valid_scored_cases": valid_count, "invalid_cases": len(cases)-valid_count,
            "status": "scored" if valid_count else "unscored",
            "requested_top_k": top_k, "evaluated_top_k": effective_k,
            "category_counts": {key: value["count"] for key, value in category_metrics(next(iter(mode_reports.values()))["cases"]).items()},
            "modes": mode_reports, "metric_version": "retrieval-macro-v2",
            "embedding": {"provider": getattr(provider, "provider_name", None),
                          "model": getattr(provider, "model_name", None),
                          "dimension": getattr(provider, "dimension", None)},
            "timing": timing_metadata or {"warmup": False, "cold_start_in_query_latency": "depends_on_process_state"},
            "notes": "Empty/unresolved gold is unscored. Macro Recall differs from HitRate. Graph gain is removed. "
                     "Dataset provenance must be verified separately; historical reports are not comparable.",
        }
        self._write_reports(report, report_name)
        run = EvaluationRun(status=report["status"], dataset_path=str(path),
                            metrics_json=json.dumps(self._persistable_report(report), ensure_ascii=False),
                            report_path=f"reports/{report_name}.md")
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        report["evaluation_run_id"] = run.id
        return report

    def latest(self) -> dict | None:
        run = self.db.query(EvaluationRun).order_by(EvaluationRun.created_at.desc()).first()
        if not run:
            return None
        data = json.loads(run.metrics_json)
        data["evaluation_run_id"] = run.id
        data["created_at"] = run.created_at.isoformat()
        if data.get("metric_version") != "retrieval-macro-v2":
            data["status"] = "historical_unverified"
            data["notes"] = "Historical metric implementation; not a trustworthy quality baseline."
        return data

    def _persistable_report(self, report: dict) -> dict:
        return {**report, "modes": {mode: {key: value for key, value in data.items() if key != "cases"}
                                   for mode, data in report["modes"].items()}}

    def _dataset_path(self, dataset_path: str) -> Path:
        path = Path(dataset_path)
        if path.is_file():
            return path
        # Preserve the old API default when the working directory is backend.
        relative = Path(*path.parts[1:]) if path.parts and path.parts[0] == "backend" else path
        fallback = BACKEND_ROOT / relative
        if fallback.is_file():
            return fallback
        raise FileNotFoundError(f"Evaluation dataset not found: {dataset_path}")

    def _load_cases(self, dataset_path: str) -> list[dict]:
        cases = []
        for index, line in enumerate(Path(dataset_path).read_text(encoding="utf-8-sig").splitlines(), 1):
            if not line.strip():
                continue
            case = json.loads(line)
            gold = case.get("relevant_chunk_ids", [])
            if not isinstance(gold, list) or any(not isinstance(key, str) or not key.strip() for key in gold):
                case["invalid_reason"] = "malformed_gold"
                gold = []
            case["relevant_chunk_ids"] = sorted(set(gold))
            case["id"] = case.get("id", f"line-{index}")
            case["query_type"] = case.get("query_type") or case.get("category") or "uncategorized"
            case["category"] = case["query_type"]
            cases.append(case)
        return cases

    def _write_reports(self, report: dict, report_name: str) -> None:
        if Path(report_name).name != report_name:
            raise ValueError("report_name must be a filename stem")
        reports = Path("reports")
        reports.mkdir(exist_ok=True)
        (reports / f"{report_name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        lines = ["# Retrieval Evaluation", "", f"Dataset kind: {report['dataset_kind']}",
                 f"Cases: {report['total_cases']}; valid: {report['valid_scored_cases']}; invalid: {report['invalid_cases']}",
                 f"Metric version: {report['metric_version']}", "",
                 "| Mode | HitRate@5 | Recall@5 | Recall@10 | MRR@10 | p50 ms | p95 ms |",
                 "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for mode, values in report["modes"].items():
            cells = [values[k] for k in ("HitRate@5", "Recall@5", "Recall@10", "MRR@10", "P50 Latency", "P95 Latency")]
            lines.append("| " + " | ".join([mode] + [str(c) if c is not None else "unscored" for c in cells]) + " |")
        lines.extend(["", report["notes"], "", "Timing: " + json.dumps(report["timing"])])
        (reports / f"{report_name}.md").write_text("\n".join(lines), encoding="utf-8")
