"""Read-only runner for an already indexed, isolated real-paper benchmark corpus."""
from __future__ import annotations
import argparse
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version as package_version, PackageNotFoundError
import platform


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', default='benchmarks/real_research/manifest.json')
    parser.add_argument('--output', default='reports/phase6_real_benchmark')
    parser.add_argument('--with-reranker', action='store_true')
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    os.environ.update(LLM_API_KEY='', LLM_BASE_URL='http://127.0.0.1:1/v1', RERANKER_ENABLED='false')
    from app.core.config import get_settings
    from app.services.evaluation.real_benchmark import load_dataset, validate_queries, evaluate, write_report
    from app.services.retrieval.reranker import get_reranker
    from app.schemas.real_benchmark import QUERY_TYPES
    settings = get_settings()
    runtime = {'python': platform.python_version(), 'device': settings.reranker_device}
    for package in ('sentence-transformers', 'transformers', 'torch', 'chromadb'):
        try:
            runtime[package] = package_version(package)
        except PackageNotFoundError:
            runtime[package] = None
    manifest, raw, errors, digest = load_dataset(args.manifest)
    rows = [{**r, 'valid': False, 'invalid_reason': 'corpus_required'} for r in raw]
    report = dict(benchmark_version=manifest.benchmark_version, dataset_sha256=digest,
        run_timestamp=datetime.now(timezone.utc).isoformat(), corpus_size=len(manifest.documents),
        corpus=[d.model_dump() for d in manifest.documents], query_count=len(raw), runtime=runtime,
        query_type_distribution={k: sum(r.get('query_type') == k for r in raw) for k in QUERY_TYPES},
        language_counts={k: sum(r.get('language') == k for r in raw) for k in ('zh', 'en', 'mixed')},
        embedding={k: v for k, v in settings.model_dump().items() if k.startswith('embedding_')},
        retrieval_config={'rrf_k': settings.rrf_k, 'dense_top_k': settings.dense_top_k,
                          'candidate_limit': 200, 'candidate_n': 20, 'ranking_metric_k': 10},
        graph_config={k: v for k, v in settings.model_dump().items() if k.startswith('graph_')},
        reranker_config={k: v for k, v in settings.model_dump().items() if k.startswith('reranker_')},
        timing={'embedding_cold_load_ms': None, 'reranker_cold_load_ms': None,
                'query_repetitions': 1, 'query_warmup': False}, modes={})
    report['reranker_config']['experiment_enabled'] = args.with_reranker
    if manifest.documents:
        url = os.environ.get('BENCHMARK_DATABASE_URL', '')
        if not url.startswith('mysql+pymysql://'):
            raise ValueError('Set BENCHMARK_DATABASE_URL to an existing isolated benchmark MySQL schema')
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session
        from app.models.document import Document, DocumentVersion
        from app.services.retrieval.retrieval_service import ResearchRetrievalService
        from app.vectorstore.embeddings import get_embedding_provider
        engine = create_engine(url, pool_pre_ping=True)
        with Session(engine) as db:
            active_ids = set(db.scalars(select(Document.id).where(Document.status == 'ready')).all())
            if active_ids - {d.document_id for d in manifest.documents} or len({d.document_id for d in manifest.documents}) != len(manifest.documents):
                raise ValueError('Unexpected ready documents or duplicate manifest IDs; use an isolated benchmark database')
            for doc in manifest.documents:
                version = db.get(DocumentVersion, doc.document_version_id)
                if not version or version.document_id != doc.document_id or version.source_checksum != doc.sha256:
                    errors[doc.document_id] = 'corpus_version_checksum_mismatch'
            rows = validate_queries(db, manifest, raw, errors)
            if errors:
                for row in rows:
                    if row['valid']:
                        row.update(valid=False, invalid_reason='corpus_not_fully_verified')
            if any(r['valid'] for r in rows) and not args.validate_only:
                if settings.embedding_provider != 'bge':
                    raise ValueError('Real benchmark requires BGE; Fake is test-only')
                started = time.perf_counter()
                get_embedding_provider()._get_model()
                report['timing']['embedding_cold_load_ms'] = (time.perf_counter()-started)*1000
                scorer = get_reranker(settings) if args.with_reranker else None
                if scorer:
                    try:
                        scorer.load()
                    except Exception:
                        pass  # Every attempted query is explicitly marked fallback.
                    report['timing']['reranker_cold_load_ms'] = scorer.cold_load_ms
                report['modes'] = evaluate(rows, ResearchRetrievalService(db), scorer, settings.reranker_final_k)
        engine.dispose()
    report['corpus_errors'] = errors
    report['annotation_validation'] = [{k: r.get(k) for k in ('query_id', 'valid', 'invalid_reason')} for r in rows]
    valid = sum(r['valid'] for r in rows)
    report.update(valid_queries=valid, invalid_queries=len(rows)-valid,
        invalid_reasons=dict(Counter(r['invalid_reason'] for r in rows if not r['valid'])),
        gold_source='HUMAN-CURATED' if valid and valid == len(rows) else
                    'PARTIALLY HUMAN-CURATED' if valid else 'MISSING',
        status='MEASURED_REQUIRES_HUMAN_QUALITY_REVIEW' if report['modes'] else
               'REAL_BENCHMARK_DATA_REQUIRED' if not valid else 'VALIDATED_NOT_RUN',
        reranker_decision='NOT ENOUGH REAL DATA' if not report['modes'] else 'KEEP OPTIONAL')
    write_report(report, args.output)
    print(json.dumps({k: report[k] for k in ('status', 'corpus_size', 'query_count', 'valid_queries', 'invalid_queries')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
