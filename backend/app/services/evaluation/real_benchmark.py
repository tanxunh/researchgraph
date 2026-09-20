"""Read-only authoritative annotation validation and paired candidate experiment."""
from __future__ import annotations

import hashlib
import json
import statistics
import time
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from app.models.document import Document, DocumentChunk
from app.schemas.real_benchmark import QUERY_TYPES, ResearchManifest, ResearchQuery
from app.services.evaluation.metrics import score_ranking, summarize
from app.services.indexing.version_chunks import membership_query
from app.services.retrieval.reranker import rerank_candidates


def local_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('benchmark_path_outside_root')
    return path


def load_dataset(manifest_path):
    path = Path(manifest_path)
    manifest = ResearchManifest.model_validate_json(path.read_text(encoding='utf-8-sig'))
    queries = local_path(path.parent, manifest.queries_path)
    raw = []
    for index, line in enumerate(queries.read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            raw.append(item if isinstance(item, dict) else {'query_id': f'line-{index}'})
        except ValueError:
            raw.append({'query_id': f'line-{index}'})
    errors = {}
    for doc in manifest.documents:
        try:
            source = local_path(path.parent, doc.path)
            if hashlib.sha256(source.read_bytes()).hexdigest() != doc.sha256:
                errors[doc.document_id] = 'corpus_hash_mismatch'
        except (OSError, ValueError):
            errors[doc.document_id] = 'corpus_file_missing_or_invalid'
    digest = hashlib.sha256(path.read_bytes() + queries.read_bytes()).hexdigest()
    return manifest, raw, errors, digest


def validate_queries(db, manifest, raw, corpus_errors):
    documents = {d.document_id: d for d in manifest.documents}
    counts = Counter(str(c.get('query_id', '')).strip() for c in raw)
    rows = []
    for item in raw:
        row = {**item, 'valid': False, 'invalid_reason': None,
               'returned_chunk_ids': [], 'relevant_chunk_ids': [], 'latency_ms': None}
        try:
            query = ResearchQuery.model_validate(item)
            reason = None
            if counts[query.query_id] > 1:
                reason = 'duplicate_query_id'
            elif not query.gold_evidence:
                reason = 'empty_gold'
            elif query.annotation_status != 'human_reviewed' or not query.annotator:
                reason = 'human_gold_required'
            elif set(query.gold_document_ids) != {g.document_id for g in query.gold_evidence}:
                reason = 'gold_document_mismatch'
            for gold in query.gold_evidence:
                doc = documents.get(gold.document_id)
                if not doc or doc.document_version_id != gold.document_version_id:
                    reason = reason or 'document_not_in_manifest'
                    continue
                if gold.document_id in corpus_errors:
                    reason = reason or corpus_errors[gold.document_id]
                    continue
                resolved = db.execute(membership_query().where(
                    Document.status == 'ready', Document.id == gold.document_id,
                    DocumentChunk.stable_chunk_id == gold.chunk_id)).all()
                matches = [(c, m, v, d) for c, m, v, d in resolved
                           if v.id == gold.document_version_id and m.page_number == gold.page
                           and m.section_title == gold.section]
                if len(matches) != 1:
                    reason = reason or 'invalid_current_version_chunk_locator'
            row.update(query.model_dump(), relevant_chunk_ids=sorted({g.chunk_id for g in query.gold_evidence}),
                       invalid_reason=reason, valid=reason is None,
                       cross_document=query.query_type in ('cross_document', 'multi_hop'))
        except ValidationError:
            row['invalid_reason'] = 'invalid_annotation_schema'
        rows.append(row)
    return rows


def aggregate(rows):
    result = summarize(rows)
    valid = [r for r in rows if r['valid']]
    result['Candidate Recall@20'] = (round(statistics.mean(
        score_ranking(r['candidate_chunk_ids'], r['relevant_chunk_ids'], 20)['Recall']
        for r in valid), 4) if valid else None)
    routed = [r for r in valid if r.get('routing')]
    result['graph_activation_rate'] = (sum(bool(r['routing']['graph_enabled']) for r in routed) / len(routed)
                                       if routed else None)
    result['reranker_failed_queries'] = sum(r.get('reranker', {}).get('reranker_failed', False) for r in valid)
    return result


def evaluate(rows, retrieval, scorer=None, final_k=10, *,
             baseline_modes=('bm25', 'dense', 'hybrid', 'auto'), rerank_mode='auto',
             progress=None):
    # Reranking reuses the exact fetched Top20, without another retrieval call.
    if scorer is not None and rerank_mode not in baseline_modes:
        raise ValueError('rerank_mode must be a selected baseline')
    modes = {m: [] for m in baseline_modes}
    paired_mode = f'{rerank_mode}_reranker'
    if scorer is not None:
        modes[paired_mode] = []
    for mode in baseline_modes:
        for row in rows:
            case = {**row, 'retrieval_mode': mode, 'candidate_chunk_ids': [], 'candidates': [], 'routing': {}}
            if row['valid']:
                start = time.perf_counter()
                result = retrieval.search(row['question'], mode=mode, top_k=20, rerank=False)
                candidates = result['results']
                case.update(latency_ms=(time.perf_counter()-start)*1000,
                            candidate_locators=[{'document_id': c['document']['id'],
                                'document_version_id': c['document_version_id'], 'chunk_id': c['chunk_id']}
                                for c in candidates],
                            candidates=candidates, candidate_chunk_ids=[c['chunk_id'] for c in candidates],
                            returned_chunk_ids=[c['chunk_id'] for c in candidates[:10]], routing=result.get('routing', {}))
            modes[mode].append(case)
            if mode == rerank_mode and scorer is not None:
                reranked = {**case, 'retrieval_mode': paired_mode}
                if row['valid']:
                    start = time.perf_counter()
                    ordered, metadata = rerank_candidates(row['question'], case['candidates'], scorer)
                    reranked.update(candidates=ordered, returned_chunk_ids=[c['chunk_id'] for c in ordered[:10]],
                                    final_evidence_chunk_ids=[c['chunk_id'] for c in ordered[:final_k]],
                                    latency_ms=case['latency_ms']+(time.perf_counter()-start)*1000,
                                    reranker=metadata)
                modes[paired_mode].append(reranked)
            if progress:
                progress(mode, row['query_id'])
    reports = {}
    for mode, cases in modes.items():
        bad = []
        for c in cases:
            category = None
            if not c['valid']:
                category = 'gold_invalid'
            elif not set(c['relevant_chunk_ids']).issubset(c['candidate_chunk_ids']):
                category = 'retrieval_miss'
            elif not set(c['relevant_chunk_ids']).issubset(c['returned_chunk_ids'][:5]):
                category = 'ranking_failure'
            if category and len(bad) < 10:
                # Limited candidates; no full text, credentials or LLM trace.
                bad.append({**{k: c.get(k) for k in ('query_id', 'question', 'query_type', 'gold_evidence',
                             'invalid_reason', 'routing', 'retrieval_mode', 'reranker')},
                            'failure_category': category,
                            'candidates': [{'rank': i, 'chunk_id': v['chunk_id'],
                                            'document': v['document'], 'scores': v['scores']}
                                           for i, v in enumerate(c['candidates'], 1)]})
        reports[mode] = {**aggregate(cases), 'category_metrics': {
            kind: aggregate([c for c in cases if c.get('query_type') == kind]) for kind in QUERY_TYPES},
            'bad_cases': bad, 'query_diagnostics': [{k: c.get(k) for k in (
                'query_id', 'query_type', 'valid', 'invalid_reason', 'routing', 'candidate_chunk_ids',
                'returned_chunk_ids', 'relevant_chunk_ids', 'gold_evidence', 'candidate_locators',
                'final_evidence_chunk_ids', 'latency_ms', 'reranker')} for c in cases]}
    return reports


def write_report(report, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix('.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# Real research benchmark', '', report['status'], '',
             '| Mode | HitRate@5 | Recall@5 | Recall@10 | MRR@10 | Candidate Recall@20 | p50 ms | p95 ms |',
             '| --- | --- | --- | --- | --- | --- | --- | --- |']
    keys = ('HitRate@5', 'Recall@5', 'Recall@10', 'MRR@10', 'Candidate Recall@20', 'P50 Latency', 'P95 Latency')
    for mode, metrics in report['modes'].items():
        lines.append('| ' + ' | '.join([mode] + [str(metrics[k]) for k in keys]) + ' |')
    lines += ['', '| Mode/category | n | Recall@5 | Recall@10 | MRR@10 | Candidate Recall@20 |',
              '| --- | --- | --- | --- | --- | --- |']
    for mode, metrics in report['modes'].items():
        for kind, subset in metrics['category_metrics'].items():
            lines.append('| ' + ' | '.join([f'{mode}/{kind}', str(subset['count'])] +
                [str(subset[k]) for k in ('Recall@5', 'Recall@10', 'MRR@10', 'Candidate Recall@20')]) + ' |')
    lines += ['', 'Metadata:', '```json', json.dumps({k: v for k, v in report.items() if k != 'modes'}, indent=2), '```']
    output.with_suffix('.md').write_text('\n'.join(lines), encoding='utf-8')
