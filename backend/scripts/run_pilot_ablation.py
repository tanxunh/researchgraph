"""Frozen Phase 6D pilot: read-only SQL validation and paired Hybrid reranking."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import platform
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_pilot(benchmark, manifest_path, papers):
    from app.schemas.real_benchmark import ResearchManifest, ResearchQuery
    from app.services.evaluation.real_benchmark import local_path
    frozen = json.loads(Path(benchmark).read_text(encoding='utf-8-sig'))
    docs = json.loads(Path(manifest_path).read_text(encoding='utf-8-sig'))['documents']
    mapping = {d['benchmark_document_id']: d for d in docs}
    if len(mapping) != len(docs):
        raise ValueError('duplicate corpus IDs')
    if frozen['status'] != 'FINALIZED' or frozen['annotation_source'] != 'HUMAN_CURATED':
        raise ValueError('finalized human benchmark required')
    raw = []
    for q in frozen['queries']:
        if q['annotation_status'] != 'HUMAN_APPROVED':
            raise ValueError('unapproved query')
        for g in q['gold_evidence']:
            d = mapping[g['benchmark_document_id']]
            if (g['document_id'], g['document_version_id']) != (d['document_id'], d['document_version_id']):
                raise ValueError('gold corpus identity mismatch')
        projected = {**q, 'gold_document_ids': [mapping[k]['document_id'] for k in q['gold_document_ids']],
            'gold_evidence': [{k: v for k, v in g.items() if k != 'benchmark_document_id'} for g in q['gold_evidence']],
            'annotation_status': 'human_reviewed', 'annotation_notes': ''}
        raw.append(ResearchQuery.model_validate(projected).model_dump())
    if len(raw) != frozen['query_count'] or len(docs) != frozen['corpus']['paper_count']:
        raise ValueError('benchmark count mismatch')
    manifest = ResearchManifest(benchmark_version=frozen['benchmark_id'], corpus_kind='real_papers',
        queries_path=Path(benchmark).name, documents=[dict(document_id=d['document_id'],
            document_version_id=d['document_version_id'], title=d['title'],
            source_reference='local-user-provided:' + d['source_filename'], path=d['source_filename'],
            sha256=d['source_sha256']) for d in docs])
    for d in manifest.documents:
        if sha(local_path(Path(papers), d.path)) != d.sha256:
            raise ValueError('corpus file checksum mismatch')
    return frozen, manifest, raw


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--benchmark', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--papers', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    os.environ.update(LLM_API_KEY='', LLM_BASE_URL='http://127.0.0.1:1/v1', RERANKER_ENABLED='false')
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from app.core.config import get_settings
    from app.models.document import Document, DocumentVersion
    from app.services.evaluation.real_benchmark import validate_queries, evaluate, write_report
    from app.services.retrieval.retrieval_service import ResearchRetrievalService
    from app.services.retrieval.reranker import get_reranker
    from app.vectorstore.embeddings import get_embedding_provider
    digest = sha(args.benchmark)
    frozen, manifest, raw = load_pilot(args.benchmark, args.manifest, args.papers)
    settings = get_settings()
    if (settings.embedding_provider, settings.embedding_model, settings.embedding_dimension,
        settings.embedding_device, settings.reranker_model, settings.reranker_device,
        settings.reranker_candidate_n, settings.reranker_final_k) != (
        'bge', 'BAAI/bge-small-zh-v1.5', 512, 'cpu', 'BAAI/bge-reranker-base', 'cpu', 20, 10):
        raise ValueError('Phase 6D fixed model or candidate settings violated')
    url = os.environ.get('BENCHMARK_DATABASE_URL', '')
    if not url.startswith('mysql+pymysql://'):
        raise ValueError('isolated benchmark MySQL required')
    report = dict(benchmark_id=frozen['benchmark_id'], benchmark_sha256=digest,
        manifest_sha256=sha(args.manifest), run_timestamp=datetime.now(timezone.utc).isoformat(),
        query_language='English', gold_source='HUMAN-CURATED', corpus_size=len(manifest.documents),
        query_count=len(raw), auto='NOT RUN', graph='NOT RUN',
        graph_reason='GRAPH_INDEX_PENDING_EXTERNAL_LLM',
        embedding={k: v for k, v in settings.model_dump().items() if k.startswith('embedding_')},
        reranker_config={k: v for k, v in settings.model_dump().items() if k.startswith('reranker_')},
        retrieval_config=dict(candidate_n=20, final_k=10, rrf_k=settings.rrf_k,
            dense_top_k=settings.dense_top_k, candidate_limit=200),
        timing=dict(query_repetitions=1, query_warmup=False, model_download_excluded=True),
        metric_definition='Macro average of per-query unique Gold chunk recall; SQL validates document/version/chunk locators. No document-only credit.',
        corpus=[d.model_dump() for d in manifest.documents],
        runtime={p: version(p) for p in ('torch', 'sentence-transformers', 'transformers', 'chromadb', 'sentencepiece', 'protobuf')},
        status='RUNNING', modes={}, reranker_decision='PENDING_RESULT_REVIEW')
    report['runtime']['python'] = platform.python_version()
    report['code_sha256'] = {str(p): sha(p) for base in ('app/services/retrieval', 'app/services/evaluation', 'app/vectorstore')
                             for p in sorted(Path(base).glob('*.py'))}
    report['code_sha256'][str(Path(__file__))] = sha(__file__)
    engine = create_engine(url, pool_pre_ping=True)
    with Session(engine) as db:
        def verify():
            active = set(db.execute(select(Document.id, DocumentVersion.id).join(DocumentVersion, (DocumentVersion.document_id == Document.id) & (DocumentVersion.version == Document.current_version)).where(Document.status == 'ready')).all())
            if active != {(d.document_id, d.document_version_id) for d in manifest.documents}:
                raise ValueError('active corpus differs from frozen manifest')
            for d in manifest.documents:
                v = db.get(DocumentVersion, d.document_version_id)
                if not v or v.document_id != d.document_id or v.source_checksum != d.sha256:
                    raise ValueError('SQL source checksum mismatch')
            rows = validate_queries(db, manifest, raw, {})
            if not all(r['valid'] for r in rows):
                raise ValueError('all human Gold locators must validate before scoring')
            return rows
        rows = verify()
        report['annotation_validation'] = dict(approved=len(rows), pending=0, invalid=0, locator_validation='ALL PASS')
        start = time.perf_counter()
        get_embedding_provider()._get_model()
        report['timing']['embedding_cold_load_ms'] = (time.perf_counter()-start)*1000
        scorer = get_reranker(settings)
        scorer.load()  # Do not present a missing-model fallback as a measured ablation.
        report['timing']['reranker_cold_load_ms'] = scorer.cold_load_ms
        import torch
        report['runtime']['torch_num_threads'] = torch.get_num_threads()
        report['runtime']['torch_interop_threads'] = torch.get_num_interop_threads()
        print('Models loaded; starting BM25, Dense, Hybrid + paired reranker', flush=True)
        report['modes'] = evaluate(rows, ResearchRetrievalService(db), scorer, 10,
            baseline_modes=('bm25', 'dense', 'hybrid'), rerank_mode='hybrid',
            progress=lambda mode, qid: print(f'{mode} {qid} complete', flush=True))
        db.rollback()  # End the snapshot; verify the current committed corpus again.
        db.expire_all()
        verify()
    engine.dispose()
    if digest != sha(args.benchmark) or report['manifest_sha256'] != sha(args.manifest):
        raise ValueError('frozen inputs changed during run')
    if any(sha(p) != h for p, h in report['code_sha256'].items()):
        raise ValueError('code changed during run')
    for metrics in report['modes'].values():
        metrics['benchmark_sha256'] = digest
    report['benchmark_sha256_after'] = sha(args.benchmark)
    report['status'] = ('MEASURED_RERANKER_FAILURES_REVIEW_REQUIRED' if
        report['modes']['hybrid_reranker']['reranker_failed_queries'] else 'MEASURED')
    write_report(report, args.output)
    print(json.dumps({m: {k: v[k] for k in ('HitRate@5', 'Recall@5', 'Recall@10', 'MRR@10', 'Candidate Recall@20', 'P50 Latency', 'P95 Latency')}
                      for m, v in report['modes'].items()}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
