"""Finite, isolated synthetic retrieval baseline. Never imports business data or calls an LLM."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path



RELATIONS = ["EVALUATED_ON", "COMPARES_WITH", "TARGETS", "REPORTS", "USES"]
ENTITY_TYPES = {
    "Paper Atlas Trial": "Paper", "Paper Beacon Note": "Paper", "Paper Cascade Brief": "Paper", "Paper Delta Memo": "Paper",
    "Paper Echo Report": "Paper", "Paper Flux Note": "Paper", "Paper Gradient Card": "Paper", "Paper Harbor Sheet": "Paper",
    "AtlasRetriever": "Method", "BeaconPlanner": "Method", "CascadeReader": "Method", "DeltaIndexer": "Method",
    "EchoGraph": "Method", "FluxRank": "Method", "GradientMemo": "Method", "HarborQA": "Method",
    "AuroraSet": "Dataset", "WorkshopCards": "Dataset", "CitationWeave": "Dataset", "LabNotes-42": "Dataset",
    "ScholarToy": "Dataset", "MetroReviews": "Dataset", "TimelineQA": "Dataset",
    "Literature Mapping": "Task", "Study Planning": "Task", "Cross Paper Evidence": "Task", "Incremental Note Search": "Task",
    "Citation Trace": "Task", "Method Comparison": "Task", "Experiment Recall": "Task", "Dataset Grounding": "Task",
    "Source Hit Rate": "Metric", "Complete Evidence Recall": "Metric", "MRR@10": "Metric", "Recall@5": "Metric",
    "Graph Path Validity": "Metric", "Latency P95": "Metric",
    "Graph Expansion": "Concept", "Evidence Stitching": "Concept", "Relation Path": "Concept", "Chunk Stability": "Concept",
    "Query Paraphrase": "Concept", "Semantic Drift": "Concept",
}


class HardEvalMockExtractor:
    def extract(self, text: str) -> ChunkGraphExtraction:
        from app.services.graph.extraction_schema import ChunkGraphExtraction, ExtractedEntity, ExtractedRelation
        names = [name for name in ENTITY_TYPES if name in text]
        entities = [ExtractedEntity(name=name, entity_type=ENTITY_TYPES[name], aliases=[], description="Synthetic hard-eval entity", confidence=0.95) for name in sorted(names, key=len, reverse=True)]
        relations = []
        for relation_type in RELATIONS:
            if relation_type not in text:
                continue
            for source in sorted(names, key=len, reverse=True):
                for target in sorted(names, key=len, reverse=True):
                    if source == target:
                        continue
                    match = re.search(re.escape(source) + r".{0,80}" + relation_type + r".{0,80}" + re.escape(target), text)
                    if match:
                        relations.append(ExtractedRelation(source_name=source, relation_type=relation_type, target_name=target, evidence_text=match.group(0), confidence=0.9))
        return ChunkGraphExtraction(entities=entities, relations=relations)



def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["fake", "bge"], default="bge")
    parser.add_argument("--report-name", default="phase5_graph_ablation")
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="lifeflow-baseline-")).resolve()
    os.environ.update(APP_ENV="test", DATABASE_URL=f"sqlite:///{root / 'benchmark.db'}",
                      CHROMA_HOST="", CHROMA_PERSIST_DIR=str(root / "chroma"),
                      SOURCE_STORAGE_ROOT=str(root / "sources"), EMBEDDING_PROVIDER=args.provider,
                      EMBEDDING_DIMENSION="8" if args.provider == "fake" else "512",
                      EMBEDDING_MODEL="BAAI/bge-small-zh-v1.5",
                      EMBEDDING_VERSION="phase5-ablation-v1", GRAPH_EXTRACTOR_MODE="mock",
                      LLM_API_KEY="", LLM_BASE_URL="http://127.0.0.1:1/v1",
                      ANONYMIZED_TELEMETRY="FALSE")
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.core.database import SessionLocal, create_db_tables
    from app.services.evaluation.retrieval_evaluator import RetrievalEvaluator
    CORE_MODES = ["hybrid", "graph_enhanced", "auto"]
    from app.services.graph.extraction_schema import ChunkGraphExtraction
    from app.services.indexing.incremental_indexer import IncrementalIndexer
    from app.services.indexing.version_chunks import version_chunks
    from app.services.parsing.base import ParsedDocument, ParsedSection
    from app.services.retrieval.retrieval_service import ResearchRetrievalService
    from app.vectorstore.chroma_store import ChromaStore
    from app.vectorstore.embeddings import get_embedding_provider

    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/hard_eval"
    manifest = json.loads((fixture / "manifest.json").read_text(encoding="utf-8-sig"))
    cases = [json.loads(line) for line in (fixture / "cases.jsonl").read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    create_db_tables()
    provider = get_embedding_provider()
    started = time.perf_counter()
    if args.provider == "bge":
        provider._get_model()  # Time cold model acquisition explicitly, separately from query latency.
    load_ms = (time.perf_counter()-started)*1000
    store = ChromaStore(provider)
    digest = hashlib.sha256((fixture / "manifest.json").read_bytes() + (fixture / "cases.jsonl").read_bytes())
    with SessionLocal() as db:
        indexer = IncrementalIndexer(store, HardEvalMockExtractor())
        logical = {}
        started = time.perf_counter()
        chunk_count = 0
        for entry in manifest["documents"]:
            data = (fixture / entry["path"]).read_bytes()
            digest.update(data)
            raw = data.decode("utf-8-sig")
            headings = list(re.finditer(r"^##\s+([^\n]+)\n", raw, re.MULTILINE))
            sections = []
            for index, match in enumerate(headings):
                section = match.group(1).strip().split()[0]
                end = headings[index+1].start() if index+1 < len(headings) else len(raw)
                sections.append(ParsedSection(text=raw[match.end():end].strip(), order=index, section_title=section))
            parsed = ParsedDocument(title=entry["title"], source_type="text",
                                    source_uri="phase3:" + entry["document_key"],
                                    text="\n\n".join(s.text for s in sections), sections=sections,
                                    metadata={"synthetic_test_corpus": True})
            result = indexer.import_parsed(db, parsed)
            chunks = version_chunks(db, result["document_id"], result["version"])
            chunk_count += len(chunks)
            for section in entry["sections"]:
                marker = f"DOCUMENT_KEY={entry['document_key']}; SECTION_KEY={section}"
                matches = [c for c in chunks if c.section_title == section and marker in c.text]
                # Never guess gold from chunk ordinal or partially resolve an ambiguous key.
                logical[entry["document_key"] + ":" + section] = matches[0].stable_chunk_id if len(matches) == 1 else None
        build_ms = (time.perf_counter()-started)*1000
        for case in cases:
            keys = case.get("relevant_chunk_keys", [])
            resolved = [logical.get(key) for key in keys]
            if not keys or any(value is None for value in resolved):
                case["invalid_reason"] = "unresolved_or_ambiguous_gold_key"
                case["relevant_chunk_ids"] = []
            else:
                case["relevant_chunk_ids"] = resolved
            case["query_type"] = {"semantic_paraphrase": "semantic", "exact_terminology": "exact_term",
                                  "cross_document_relation": "cross_document"}.get(case.get("category"), case.get("category", "unknown"))
        path = root / "resolved_cases.jsonl"
        path.write_text("\n".join(json.dumps(case) for case in cases), encoding="utf-8")
        report = RetrievalEvaluator(db).run(
            str(path), modes=CORE_MODES, dataset_kind="synthetic_existing_gold_keys_unreviewed",
            report_name=args.report_name, retrieval=ResearchRetrievalService(db, store),
            timing_metadata={"warmup": False, "query_repetitions": 1, "mode_order": CORE_MODES,
                             "cold_model_load_ms": round(load_ms, 3), "index_build_ms": round(build_ms, 3),
                             "cold_start_in_query_latency": False, "model_loaded_during_setup": True,
                             "fixture_sha256": digest.hexdigest(), "document_count": len(manifest["documents"]),
                             "chunk_count": chunk_count,
                             "note": "One sequential pass per mode; model load/index build measured separately. No best-run selection."})
        from app.services.evaluation.graph_ablation import graph_gain
        report["graph_config"] = {name: getattr(get_settings(), name) for name in (
            "graph_max_hops", "graph_max_neighbors", "graph_max_paths", "graph_max_expanded_entities",
            "graph_hop_decay", "graph_rrf_weight", "graph_min_relation_confidence")}
        report["ablation"] = {}
        baseline = report["modes"]["hybrid"]["cases"]
        for mode in CORE_MODES:
            rows = report["modes"][mode]["cases"]
            report["ablation"][mode] = {"overall": graph_gain(baseline, rows)}
            for kind in ("factual", "semantic", "exact_term", "relational", "cross_document"):
                subset = [c for c in rows if c["query_type"] == kind]
                report["ablation"][mode][kind] = graph_gain(baseline, subset)
            report["modes"][mode]["graph_enabled_queries"] = sum(
                c.get("routing", {}).get("graph_enabled", False) for c in rows)
        RetrievalEvaluator(db)._write_reports(report, args.report_name)
        print(json.dumps({key: value for key, value in report.items() if key != "modes"}, ensure_ascii=False))
        print("ablation=" + json.dumps(report["ablation"]))
        for mode, metrics in report["modes"].items():
            print(mode + ": " + json.dumps({key: metrics[key] for key in
                  ("valid_scored_cases", "invalid_cases", "HitRate@5", "Recall@5", "Recall@10", "MRR@10", "P50 Latency", "P95 Latency")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
