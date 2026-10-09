"""Run the frozen ResearchGraph V2 baseline on isolated real infrastructure."""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from pathlib import Path


def append_experiments(path: Path, report: dict) -> None:
    rows = []
    for mode, metrics in report['tracks']['global']['modes'].items():
        rows.append({
            'experiment_id': f'v2-baseline-{mode}',
            'date': report['metadata']['run_timestamp'],
            'corpus_version': report['metadata']['corpus_version'],
            'split': report['metadata']['split'],
            'embedding': report['metadata']['embedding']['model'],
            'chunking': report['metadata']['chunking']['version'],
            'bm25_k': 100,
            'dense_k': 100,
            'fusion': 'none' if mode in {'bm25', 'dense'} else 'RRF',
            'rrf_k': report['metadata']['retrieval']['rrf_k'] if 'hybrid' in mode else '',
            'reranker': report['metadata']['reranker']['model'] if mode == 'hybrid_reranker' else 'OFF',
            'rerank_k': 20 if mode == 'hybrid_reranker' else '',
            'Hit@5': metrics['HitRate@5'],
            'Recall@5': metrics['Recall@5'],
            'Recall@10': metrics['Recall@10'],
            'MRR@10': metrics['MRR@10'],
            'CandidateRecall@20': metrics['Candidate Recall@20'],
            'CandidateRecall@50': metrics['Candidate Recall@50'],
            'p50': metrics['P50 Latency'],
            'p95': metrics['P95 Latency'],
            'notes': 'Frozen V1-style baseline on provisional DEV annotations; TEST untouched.',
        })
    with path.open('a', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='../benchmarks/real_research/v2')
    parser.add_argument('--split', choices=('dev', 'test'), default='dev')
    parser.add_argument('--output', default='../benchmarks/real_research/v2/results/baseline.json')
    parser.add_argument('--error-analysis', default='../benchmarks/real_research/v2/error_analysis_baseline.csv')
    args = parser.parse_args()

    if os.environ.get('V2_BASELINE_ISOLATED') != '1':
        raise ValueError('V2_BASELINE_ISOLATED=1 is required')
    os.environ.update(LLM_API_KEY='', GRAPH_EXTRACTION_ENABLED='false', RERANKER_ENABLED='false')

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.core.config import get_settings
    from app.services.evaluation.v2_benchmark import (
        build_metadata,
        ensure_corpus_state,
        load_inputs,
        run_track,
        validate_queries,
        write_miss_csv,
    )
    from app.services.retrieval.reranker import get_reranker
    from app.services.retrieval.retrieval_service import ResearchRetrievalService
    from app.vectorstore.embeddings import get_embedding_provider

    root = Path(args.root).resolve()
    output = Path(args.output).resolve()
    error_output = Path(args.error_analysis).resolve()
    if output.exists():
        raise FileExistsError(f'baseline_result_is_immutable: {output}')

    settings = get_settings()
    if not settings.database_url.startswith('mysql+pymysql://'):
        raise ValueError('V2 baseline requires real MySQL')
    if settings.embedding_provider != 'bge' or settings.embedding_model != 'BAAI/bge-small-zh-v1.5':
        raise ValueError('V2 baseline must use BAAI/bge-small-zh-v1.5')
    if settings.graph_extraction_enabled:
        raise ValueError('V2 baseline requires GRAPH_EXTRACTION_ENABLED=false')

    corpus, split_manifest, raw = load_inputs(root, args.split)
    for item in corpus['documents']:
        source = root.parent / 'papers' / item['filename']
        from app.services.evaluation.v2_benchmark import sha256
        if not source.is_file() or sha256(source) != item['sha256']:
            raise ValueError(f"corpus_file_hash_mismatch: {item['paper_id']}")

    cold = {'embedding_ms': None, 'reranker_ms': None}
    started = time.perf_counter()
    get_embedding_provider()._get_model()
    cold['embedding_ms'] = round((time.perf_counter() - started) * 1000, 3)
    scorer = get_reranker(settings)
    started = time.perf_counter()
    scorer.load()
    cold['reranker_ms'] = round((time.perf_counter() - started) * 1000, 3)

    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with Session(engine) as db:
            ensure_corpus_state(db, corpus)
            rows = validate_queries(db, corpus, raw, require_human=args.split == 'test')
            invalid = [row for row in rows if not row['valid']]
            if invalid:
                reasons = {row['query_id']: row['invalid_reason'] for row in invalid}
                raise ValueError(f'benchmark_query_validation_failed: {reasons}')
            retrieval = ResearchRetrievalService(db)
            global_modes, global_diagnostics, global_misses, global_cases = run_track(
                rows, retrieval, scorer, scoped=False,
            )
            scoped_modes, scoped_diagnostics, scoped_misses, scoped_cases = run_track(
                rows, retrieval, scorer, scoped=True,
            )
    finally:
        engine.dispose()

    misses = [dict(track='global', **row) for row in global_misses]
    misses.extend(dict(track='scoped', **row) for row in scoped_misses)
    report = {
        'status': 'V2_CORPUS_BASELINE_DEV_PROVISIONAL' if args.split == 'dev' else 'V2_CORPUS_BASELINE_TEST',
        'metadata': build_metadata(settings, args.split, corpus, split_manifest, cold),
        'integrity': {
            'corpus_manifest_sha256': split_manifest['files']['corpus_manifest.json'],
            'query_file_sha256': split_manifest['files'][f'queries_{args.split}.jsonl'],
            'split_frozen': split_manifest['frozen'],
            'gold_frozen_for_experiment': True,
            'test_untouched': args.split != 'test',
            'human_verified_queries': sum(row['human_verified'] for row in rows),
            'provisional_queries': sum(not row['human_verified'] for row in rows),
        },
        'corpus': {
            key: corpus[key]
            for key in ('pdf_count', 'page_count', 'chunk_count', 'average_chunks_per_page', 'failed_imports')
        },
        'tracks': {
            'global': {'modes': global_modes, 'candidate_diagnostics': global_diagnostics, 'query_cases': global_cases},
            'scoped': {'modes': scoped_modes, 'candidate_diagnostics': scoped_diagnostics, 'query_cases': scoped_cases},
        },
        'error_analysis': {
            'file': error_output.name,
            'classification_version': 'v2-primary-signal-1',
            'definitions': {
                'EMBEDDING_MISS': 'Gold is in BM25@100 and absent from Dense@100.',
                'LEXICAL_MISMATCH': 'Gold is in Dense@100 and absent from BM25@100.',
                'FUSION_DROPPED': 'Gold is in both or either raw candidate list but outside RRF Top-10.',
                'CROSS_DOCUMENT_CONFUSION': 'Cross-document gold is absent from both raw Top-100 lists.',
                'OTHER': 'Non-cross-document gold is absent from both raw Top-100 lists.',
            },
            'counts': dict(__import__('collections').Counter(row['primary_category'] for row in misses)),
            'counts_by_track': {
                track: dict(__import__('collections').Counter(
                    row['primary_category'] for row in misses if row['track'] == track
                ))
                for track in ('global', 'scoped')
            },
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    write_miss_csv(error_output, misses)
    append_experiments(root / 'experiments.csv', report)
    print(json.dumps({
        'status': report['status'],
        'split': args.split,
        'queries': len(raw),
        'global': report['tracks']['global']['modes'],
        'scoped': report['tracks']['scoped']['modes'],
    }, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
