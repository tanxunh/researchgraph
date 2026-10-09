"""Frozen-split V2 retrieval evaluation over authoritative evidence locators."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentChunk
from app.schemas.real_benchmark import QUERY_TYPES, V2ResearchQuery
from app.services.evaluation.metrics import score_ranking
from app.services.indexing.version_chunks import membership_query
from app.services.retrieval.reranker import rerank_candidates

DIAGNOSTIC_K = (10, 20, 30, 50, 100)
BASELINE_MODES = ('bm25', 'dense', 'hybrid')


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f'query_line_{line_number}_must_be_object')
        rows.append(value)
    return rows


def load_inputs(root: Path, split: str) -> tuple[dict, dict, list[dict]]:
    corpus = json.loads((root / 'corpus_manifest.json').read_text(encoding='utf-8'))
    split_manifest = json.loads((root / 'split_manifest.json').read_text(encoding='utf-8'))
    query_path = root / f'queries_{split}.jsonl'
    expected = split_manifest['files'][query_path.name]
    if sha256(query_path) != expected:
        raise ValueError(f'{split}_split_hash_mismatch')
    if sha256(root / 'corpus_manifest.json') != split_manifest['files']['corpus_manifest.json']:
        raise ValueError('corpus_manifest_hash_mismatch')
    return corpus, split_manifest, load_jsonl(query_path)


def validate_queries(db: Session, corpus: dict, raw: list[dict], *, require_human: bool) -> list[dict]:
    docs = {item['document_id']: item for item in corpus['documents']}
    counts = Counter(str(item.get('query_id', '')).strip() for item in raw)
    rows = []
    for item in raw:
        base = {
            **item,
            'valid': False,
            'invalid_reason': None,
            'relevant_chunk_ids': [],
            'gold_document_ids': [],
        }
        try:
            query = V2ResearchQuery.model_validate(item)
            reason = None
            if counts[query.query_id] != 1:
                reason = 'duplicate_query_id'
            elif require_human and not query.human_verified:
                reason = 'human_verification_required_for_test'
            scope = query.scoped_document_ids
            if scope is not None and not scope:
                reason = reason or 'empty_document_scope'
            gold_document_ids = {gold.document_id for gold in query.gold_evidence}
            if scope is not None and not gold_document_ids.issubset(scope):
                reason = reason or 'gold_outside_document_scope'
            for gold in query.gold_evidence:
                manifest_doc = docs.get(gold.document_id)
                if manifest_doc is None or manifest_doc['document_version_id'] != gold.document_version_id:
                    reason = reason or 'document_not_in_corpus_manifest'
                    continue
                if manifest_doc['paper_id'] != gold.paper_id:
                    reason = reason or 'paper_document_identity_mismatch'
                    continue
                resolved = db.execute(membership_query().where(
                    Document.status == 'ready',
                    Document.id == gold.document_id,
                    DocumentChunk.stable_chunk_id == gold.chunk_id,
                )).all()
                matches = [
                    (chunk, membership, version, document)
                    for chunk, membership, version, document in resolved
                    if version.id == gold.document_version_id
                    and membership.page_number == gold.page
                    and membership.section_title == gold.section
                ]
                if len(matches) != 1:
                    reason = reason or 'invalid_current_version_chunk_locator'
            base.update(
                query.model_dump(),
                relevant_chunk_ids=sorted({gold.chunk_id for gold in query.gold_evidence}),
                gold_document_ids=sorted(gold_document_ids),
                valid=reason is None,
                invalid_reason=reason,
            )
        except (ValidationError, ValueError):
            base['invalid_reason'] = 'invalid_query_schema'
        rows.append(base)
    return rows


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[math.ceil(len(ordered) * fraction) - 1], 3)


def aggregate(cases: list[dict]) -> dict:
    valid = [case for case in cases if case['valid']]
    result = {
        'count': len(cases),
        'valid_scored_cases': len(valid),
        'invalid_cases': len(cases) - len(valid),
    }
    for k in (5, 10):
        scores = [score_ranking(case['returned_chunk_ids'], case['relevant_chunk_ids'], k) for case in valid]
        for metric in ('HitRate', 'Recall', 'MRR'):
            result[f'{metric}@{k}'] = round(statistics.mean(score[metric] for score in scores), 4) if scores else None
    for k in (20, 50):
        recalls = [
            score_ranking(case['candidate_chunk_ids'], case['relevant_chunk_ids'], k)['Recall']
            for case in valid
        ]
        result[f'Candidate Recall@{k}'] = round(statistics.mean(recalls), 4) if recalls else None
    end_to_end = [case['latency_ms'] for case in valid if case.get('latency_ms') is not None]
    retrieval = [case['retrieval_latency_ms'] for case in valid if case.get('retrieval_latency_ms') is not None]
    reranker = [case['reranker_latency_ms'] for case in valid if case.get('reranker_latency_ms') is not None]
    result['P50 Latency'] = percentile(end_to_end, 0.50)
    result['P95 Latency'] = percentile(end_to_end, 0.95)
    result['retrieval_latency_ms'] = {'p50': percentile(retrieval, 0.50), 'p95': percentile(retrieval, 0.95)}
    result['reranker_latency_ms'] = {'p50': percentile(reranker, 0.50), 'p95': percentile(reranker, 0.95)}
    result['end_to_end_latency_ms'] = {'p50': percentile(end_to_end, 0.50), 'p95': percentile(end_to_end, 0.95)}
    return result


def compact_candidate(candidate: dict, rank: int) -> dict:
    return {
        'rank': rank,
        'chunk_id': candidate['chunk_id'],
        'document_id': candidate['document']['id'],
        'document_version_id': candidate['document_version_id'],
        'scores': candidate['scores'],
    }


def evaluate_mode(rows: list[dict], retrieval, mode: str, *, scoped: bool) -> list[dict]:
    valid = [row for row in rows if row['valid']]
    if valid:
        warm = valid[0]
        document_ids = warm['document_scope'] if scoped and warm['document_scope'] != 'global' else None
        retrieval.search(warm['query'], mode=mode, top_k=100, rerank=False, document_ids=document_ids)
    cases = []
    for row in rows:
        case = {
            **row,
            'retrieval_mode': mode,
            'candidate_chunk_ids': [],
            'returned_chunk_ids': [],
            'candidates': [],
            'latency_ms': None,
            'retrieval_latency_ms': None,
            'reranker_latency_ms': None,
        }
        if row['valid']:
            document_ids = row['document_scope'] if scoped and row['document_scope'] != 'global' else None
            started = time.perf_counter()
            result = retrieval.search(row['query'], mode=mode, top_k=100, rerank=False, document_ids=document_ids)
            elapsed = (time.perf_counter() - started) * 1000
            candidates = result['results']
            case.update(
                candidate_chunk_ids=[candidate['chunk_id'] for candidate in candidates],
                returned_chunk_ids=[candidate['chunk_id'] for candidate in candidates[:10]],
                candidates=[compact_candidate(candidate, rank) for rank, candidate in enumerate(candidates, 1)],
                raw_candidates=candidates,
                latency_ms=elapsed,
                retrieval_latency_ms=elapsed,
                routing=result.get('routing', {}),
            )
        cases.append(case)
    return cases


def evaluate_reranker(hybrid_cases: list[dict], scorer, final_k: int = 10) -> list[dict]:
    first = next((case for case in hybrid_cases if case['valid']), None)
    if first:
        rerank_candidates(first['query'], first['raw_candidates'][:20], scorer)
    cases = []
    for source in hybrid_cases:
        case = {**source, 'retrieval_mode': 'hybrid_reranker', 'reranker_latency_ms': None}
        if source['valid']:
            started = time.perf_counter()
            ordered, metadata = rerank_candidates(source['query'], source['raw_candidates'][:20], scorer)
            reranker_ms = (time.perf_counter() - started) * 1000
            case.update(
                returned_chunk_ids=[candidate['chunk_id'] for candidate in ordered[:final_k]],
                candidates=[compact_candidate(candidate, rank) for rank, candidate in enumerate(ordered, 1)],
                latency_ms=source['retrieval_latency_ms'] + reranker_ms,
                reranker_latency_ms=reranker_ms,
                reranker=metadata,
            )
        cases.append(case)
    return cases


def raw_union(left: list[str], right: list[str], per_source_k: int) -> list[str]:
    """Deduplicated union of each retriever's top-K candidates.

    The resulting pool may contain up to ``2 * K`` items. Truncating the
    merged list back to K would no longer be raw-union recall and could make
    the diagnostic lower than either contributing retriever.
    """
    return list(dict.fromkeys(left[:per_source_k] + right[:per_source_k]))


def candidate_diagnostics(mode_cases: dict[str, list[dict]]) -> dict:
    by_mode = {
        mode: {case['query_id']: case for case in cases if case['valid']}
        for mode, cases in mode_cases.items()
        if mode in BASELINE_MODES
    }
    query_ids = sorted(set(by_mode['bm25']) & set(by_mode['dense']) & set(by_mode['hybrid']))
    metrics = {}
    per_query = []
    for k in DIAGNOSTIC_K:
        values = {'BM25 Recall': [], 'Dense Recall': [], 'UNION Recall': [], 'RRF Recall': []}
        for query_id in query_ids:
            bm25 = by_mode['bm25'][query_id]
            dense = by_mode['dense'][query_id]
            hybrid = by_mode['hybrid'][query_id]
            union = raw_union(bm25['candidate_chunk_ids'], dense['candidate_chunk_ids'], k)
            gold = hybrid['relevant_chunk_ids']
            values['BM25 Recall'].append(score_ranking(bm25['candidate_chunk_ids'], gold, k)['Recall'])
            values['Dense Recall'].append(score_ranking(dense['candidate_chunk_ids'], gold, k)['Recall'])
            values['UNION Recall'].append(score_ranking(union, gold, k)['Recall'])
            values['RRF Recall'].append(score_ranking(hybrid['candidate_chunk_ids'], gold, k)['Recall'])
        metrics[str(k)] = {name: round(statistics.mean(items), 4) for name, items in values.items()}
    for query_id in query_ids:
        bm25 = by_mode['bm25'][query_id]
        dense = by_mode['dense'][query_id]
        hybrid = by_mode['hybrid'][query_id]
        per_query.append({
            'query_id': query_id,
            'query_type': hybrid['query_type'],
            'gold': hybrid['relevant_chunk_ids'],
            'bm25': bm25['candidate_chunk_ids'],
            'dense': dense['candidate_chunk_ids'],
            'rrf': hybrid['candidate_chunk_ids'],
        })
    return {
        'union_definition': 'deduplicated BM25[:K] union Dense[:K]; pool size <= 2K',
        'at_k': metrics,
        'per_query': per_query,
    }


def categorize_misses(mode_cases: dict[str, list[dict]]) -> list[dict]:
    by_mode = {
        mode: {case['query_id']: case for case in cases if case['valid']}
        for mode, cases in mode_cases.items()
        if mode in BASELINE_MODES
    }
    rows = []
    for query_id, hybrid in by_mode['hybrid'].items():
        bm25 = by_mode['bm25'][query_id]
        dense = by_mode['dense'][query_id]
        top10 = set(hybrid['candidate_chunk_ids'][:10])
        for gold in hybrid['gold_evidence']:
            chunk_id = gold['chunk_id']
            if chunk_id in top10:
                continue
            bm25_rank = _rank(bm25['candidate_chunk_ids'], chunk_id)
            dense_rank = _rank(dense['candidate_chunk_ids'], chunk_id)
            rrf_rank = _rank(hybrid['candidate_chunk_ids'], chunk_id)
            top_documents = {candidate['document_id'] for candidate in hybrid['candidates'][:10]}
            if bm25_rank and not dense_rank:
                category = 'EMBEDDING_MISS'
            elif dense_rank and not bm25_rank:
                category = 'LEXICAL_MISMATCH'
            elif bm25_rank or dense_rank:
                category = 'FUSION_DROPPED'
            elif hybrid['query_type'] == 'cross_document' and not set(hybrid['gold_document_ids']).issubset(top_documents):
                category = 'CROSS_DOCUMENT_CONFUSION'
            else:
                category = 'OTHER'
            rows.append({
                'query_id': query_id,
                'query_type': hybrid['query_type'],
                'missing_gold_chunk_id': chunk_id,
                'gold_document_id': gold['document_id'],
                'bm25_rank_at_100': bm25_rank,
                'dense_rank_at_100': dense_rank,
                'rrf_rank_at_100': rrf_rank,
                'primary_category': category,
                'human_verified': hybrid['human_verified'],
                'review_note': 'Signal-based baseline classification; inspect evidence before changing retrieval.',
            })
    return rows


def _rank(items: list[str], target: str) -> int | None:
    try:
        return items.index(target) + 1
    except ValueError:
        return None


def summarize_modes(mode_cases: dict[str, list[dict]]) -> dict:
    result = {}
    for mode, cases in mode_cases.items():
        metrics = aggregate(cases)
        metrics['category_metrics'] = {
            query_type: aggregate([case for case in cases if case.get('query_type') == query_type])
            for query_type in QUERY_TYPES
        }
        result[mode] = metrics
    return result


def strip_runtime_fields(mode_cases: dict[str, list[dict]]) -> dict[str, list[dict]]:
    keep = (
        'query_id', 'query_type', 'human_verified', 'valid', 'invalid_reason',
        'relevant_chunk_ids', 'candidate_chunk_ids', 'returned_chunk_ids',
        'latency_ms', 'retrieval_latency_ms', 'reranker_latency_ms', 'routing', 'reranker',
    )
    return {mode: [{key: case.get(key) for key in keep} for case in cases] for mode, cases in mode_cases.items()}


def run_track(rows: list[dict], retrieval, scorer, *, scoped: bool) -> tuple[dict, dict, list[dict], dict]:
    cases = {mode: evaluate_mode(rows, retrieval, mode, scoped=scoped) for mode in BASELINE_MODES}
    cases['hybrid_reranker'] = evaluate_reranker(cases['hybrid'], scorer)
    diagnostics = candidate_diagnostics(cases)
    misses = categorize_misses(cases)
    return summarize_modes(cases), diagnostics, misses, strip_runtime_fields(cases)


def build_metadata(settings, split: str, corpus: dict, split_manifest: dict, cold: dict) -> dict:
    return {
        'benchmark_id': corpus['benchmark_id'],
        'corpus_version': corpus['corpus_version'],
        'split': split,
        'split_seed': split_manifest['split_seed'],
        'run_timestamp': datetime.now(timezone.utc).isoformat(),
        'runtime': {'python': platform.python_version(), 'platform': platform.platform()},
        'embedding': {
            'provider': settings.embedding_provider,
            'model': settings.embedding_model,
            'dimension': settings.embedding_dimension,
            'device': settings.embedding_device,
            'normalize': settings.embedding_normalize,
        },
        'chunking': {'version': settings.chunker_version, 'size': settings.chunk_size, 'overlap': settings.chunk_overlap},
        'retrieval': {'candidate_depth': 100, 'final_k': 10, 'rrf_k': settings.rrf_k},
        'reranker': {'model': settings.reranker_model, 'candidate_n': 20, 'final_k': 10},
        'graph_extraction_enabled': settings.graph_extraction_enabled,
        'cold_start_ms': cold,
        'latency_protocol': {'warmup_per_mode_and_track': 1, 'timed_samples_per_mode': split_manifest[f'{split}_count']},
        'test_untouched': split != 'test',
    }


def write_miss_csv(path: Path, misses: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        'track', 'query_id', 'query_type', 'missing_gold_chunk_id', 'gold_document_id',
        'bm25_rank_at_100', 'dense_rank_at_100', 'rrf_rank_at_100', 'primary_category',
        'human_verified', 'review_note',
    ]
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(misses)


def ensure_corpus_state(db: Session, corpus: dict) -> None:
    ready = {document.id for document in db.query(Document).filter(Document.status == 'ready').all()}
    expected = {item['document_id'] for item in corpus['documents']}
    if ready != expected:
        raise ValueError('isolated_corpus_ready_document_mismatch')
    if corpus['failed_imports'] or any(item['import_status'] != 'ready' for item in corpus['documents']):
        raise ValueError('corpus_contains_failed_import')
